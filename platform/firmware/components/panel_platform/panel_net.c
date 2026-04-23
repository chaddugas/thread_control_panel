#include "panel_net.h"
#include "panel_app.h"
#include "panel_platform_config.h"

#include <stdio.h>
#include <string.h>

#include "esp_log.h"
#include "esp_event.h"
#include "esp_ota_ops.h"
#include "esp_partition.h"
#include "mqtt_client.h"
#include "esp_tls.h"
#include "sdkconfig.h"

#include "lwip/dns.h"
#include "lwip/ip_addr.h"

#include "esp_openthread.h"
#include "esp_openthread_lock.h"
#include "openthread/dns_client.h"
#include "openthread/instance.h"
#include "openthread/ip6.h"
#include "openthread/thread.h"

static const char *TAG = "panel_net";

// Embedded CA certificate — see the CMakeLists.txt EMBED_TXTFILES entry
// CA: ISRG Root X1 (Let's Encrypt root), valid until 2035-06-04.
// Source: https://letsencrypt.org/certs/isrgrootx1.pem
extern const uint8_t ca_cert_pem_start[] asm("_binary_ca_cert_pem_start");
extern const uint8_t ca_cert_pem_end[] asm("_binary_ca_cert_pem_end");

static bool s_mqtt_started = false;
static esp_mqtt_client_handle_t s_client = NULL;
static volatile bool s_connected = false;
static const char *s_availability_topic = NULL;

static void log_error_if_nonzero(const char *message, int error_code)
{
    if (error_code != 0)
    {
        ESP_LOGE(TAG, "Last error %s: 0x%x", message, error_code);
    }
}

static void configure_thread_dns(void)
{
    // PANEL_DNS_SERVER comes from panel_platform_config.h — currently
    // AdGuard's static ULA on the HA box. We override OpenThread's
    // discovered DNS (Google public DNS by default) because we rely on
    // AdGuard's split-horizon rewrite to resolve the broker hostname
    // to HA's LAN IPv6, which Google DNS doesn't know about.
    ip_addr_t dns_addr;
    if (!ip6addr_aton(PANEL_DNS_SERVER, &dns_addr))
    {
        ESP_LOGE(TAG, "Failed to parse DNS server address: %s", PANEL_DNS_SERVER);
        return;
    }
    dns_setserver(0, &dns_addr);

    ESP_LOGI(TAG, "Configured lwIP DNS server: %s", PANEL_DNS_SERVER);
}

static void mqtt_event_handler(void *handler_args, esp_event_base_t base,
                               int32_t event_id, void *event_data)
{
    ESP_LOGD(TAG, "Event dispatched from event loop base=%s, event_id=%" PRIi32,
             base, event_id);
    esp_mqtt_event_handle_t event = event_data;
    esp_mqtt_client_handle_t client = event->client;

    switch ((esp_mqtt_event_id_t)event_id)
    {
    case MQTT_EVENT_CONNECTED:
        ESP_LOGI(TAG, "MQTT_EVENT_CONNECTED — broker reached");
        s_connected = true;
        // If this is the first boot after an OTA (partition state ==
        // PENDING_VERIFY), the fact that we got this far — Thread attach,
        // DNS, TLS, MQTT auth — is enough to commit the new image.
        // Silently no-op for USB-flashed or already-committed apps.
        {
            const esp_partition_t *running = esp_ota_get_running_partition();
            esp_ota_img_states_t state;
            if (running != NULL &&
                esp_ota_get_state_partition(running, &state) == ESP_OK &&
                state == ESP_OTA_IMG_PENDING_VERIFY)
            {
                ESP_LOGI(TAG, "OTA: marking running partition valid — first "
                             "successful MQTT connect after update");
                esp_ota_mark_app_valid_cancel_rollback();
            }
        }
        // Announce presence. LWT handles the offline flip on an unclean
        // disconnect; this publish covers the clean-connect case.
        if (s_availability_topic)
        {
            esp_mqtt_client_publish(client, s_availability_topic,
                                    "online", 6, 1, 1);
        }
        panel_app_on_connected(client);
        break;

    case MQTT_EVENT_DISCONNECTED:
        ESP_LOGW(TAG, "MQTT_EVENT_DISCONNECTED");
        s_connected = false;
        break;

    case MQTT_EVENT_SUBSCRIBED:
        ESP_LOGI(TAG, "MQTT_EVENT_SUBSCRIBED, msg_id=%d", event->msg_id);
        break;

    case MQTT_EVENT_PUBLISHED:
        ESP_LOGI(TAG, "MQTT_EVENT_PUBLISHED, msg_id=%d", event->msg_id);
        break;

    case MQTT_EVENT_DATA:
        panel_app_on_data(client,
                          event->topic, event->topic_len,
                          event->data, event->data_len);
        break;

    case MQTT_EVENT_ERROR:
        ESP_LOGE(TAG, "MQTT_EVENT_ERROR");
        if (event->error_handle->error_type == MQTT_ERROR_TYPE_TCP_TRANSPORT)
        {
            log_error_if_nonzero("reported from esp-tls",
                                 event->error_handle->esp_tls_last_esp_err);
            log_error_if_nonzero("reported from tls stack",
                                 event->error_handle->esp_tls_stack_err);
            log_error_if_nonzero("captured as transport's socket errno",
                                 event->error_handle->esp_transport_sock_errno);
        }
        break;

    default:
        ESP_LOGI(TAG, "Other event id:%" PRIi32, event_id);
        break;
    }
}

static void start_mqtt_client(void)
{
    configure_thread_dns();

    ESP_LOGI(TAG, "Starting MQTT client, connecting to %s",
             CONFIG_MQTT_BROKER_URI);

    esp_mqtt_client_config_t mqtt_cfg = {
        .broker = {
            .address.uri = CONFIG_MQTT_BROKER_URI,
            .verification = {
                .certificate = (const char *)ca_cert_pem_start,
            },
        },
        .credentials = {
            .username = CONFIG_MQTT_USERNAME,
            .client_id = CONFIG_MQTT_CLIENT_ID,
            .authentication = {.password = CONFIG_MQTT_PASSWORD},
        },
        .session = {
            // When s_availability_topic is NULL, .topic is NULL, which
            // esp-mqtt treats as "no LWT." Otherwise the broker will
            // publish "offline" retained on our ungraceful disconnect.
            .last_will = {
                .topic = s_availability_topic,
                .msg = "offline",
                .msg_len = 7,
                .qos = 1,
                .retain = 1,
            },
        },
    };

    s_client = esp_mqtt_client_init(&mqtt_cfg);
    esp_mqtt_client_register_event(s_client, ESP_EVENT_ANY_ID,
                                   mqtt_event_handler, NULL);
    esp_mqtt_client_start(s_client);
}

// "Attached" (role == child/router/leader) is necessary but not sufficient
// to reach the broker: OTBR's RA still has to propagate so the C6 acquires
// an OMR address via SLAAC. Without that, getaddrinfo() to AdGuard's ULA
// fails. Mesh-local and link-local addresses have origin THREAD; only the
// OMR address is SLAAC + preferred.
static bool has_routable_address(otInstance *instance)
{
    for (const otNetifAddress *a = otIp6GetUnicastAddresses(instance);
         a != NULL; a = a->mNext)
    {
        if (a->mAddressOrigin == OT_ADDRESS_ORIGIN_SLAAC && a->mPreferred)
        {
            return true;
        }
    }
    return false;
}

static bool thread_attached(otInstance *instance)
{
    otDeviceRole role = otThreadGetDeviceRole(instance);
    return role == OT_DEVICE_ROLE_CHILD ||
           role == OT_DEVICE_ROLE_ROUTER ||
           role == OT_DEVICE_ROLE_LEADER;
}

static void maybe_start_mqtt(otInstance *instance)
{
    if (s_mqtt_started)
    {
        return;
    }
    if (thread_attached(instance) && has_routable_address(instance))
    {
        s_mqtt_started = true;
        ESP_LOGI(TAG, "Attached + OMR address acquired, starting MQTT");
        start_mqtt_client();
    }
}

static void thread_state_changed_callback(otChangedFlags flags, void *context)
{
    otInstance *instance = (otInstance *)context;

    if (flags & OT_CHANGED_THREAD_ROLE)
    {
        ESP_LOGI(TAG, "Thread role changed: %s",
                 otThreadDeviceRoleToString(otThreadGetDeviceRole(instance)));
    }

    // Recheck on any change — covers role transitions, address adds (OMR
    // arriving via SLAAC), and netdata updates from OTBR.
    maybe_start_mqtt(instance);
}

void panel_net_start(void)
{
    otInstance *instance = esp_openthread_get_instance();
    if (!instance)
    {
        ESP_LOGE(TAG, "OpenThread instance not ready when registering callback");
        return;
    }

    // OpenThread requires the stack lock to be held when registering callbacks.
    esp_openthread_lock_acquire(portMAX_DELAY);
    otError err = otSetStateChangedCallback(instance,
                                            thread_state_changed_callback,
                                            instance);
    esp_openthread_lock_release();

    if (err != OT_ERROR_NONE)
    {
        ESP_LOGE(TAG, "Failed to register state callback: %d", err);
        return;
    }

    // If we're already attached and have an OMR address by the time we
    // register (unlikely on cold boot but possible on reconnect), kick off
    // MQTT immediately rather than waiting for the next state change.
    maybe_start_mqtt(instance);

    ESP_LOGI(TAG, "Waiting for Thread attach + OMR address before starting MQTT");
}

int panel_net_publish(const char *topic, const char *data, int len,
                      int qos, int retain)
{
    if (!s_connected || !s_client)
    {
        return -1;
    }
    return esp_mqtt_client_publish(s_client, topic, data, len, qos, retain);
}

void panel_net_set_availability_topic(const char *topic)
{
    s_availability_topic = topic;
}
