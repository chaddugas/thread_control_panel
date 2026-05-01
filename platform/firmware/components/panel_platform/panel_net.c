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
#include "nvs.h"
#include "nvs_flash.h"
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

// MQTT credentials live in NVS rather than CONFIG_MQTT_USERNAME /
// CONFIG_MQTT_PASSWORD so published firmware.bin artifacts carry no
// credentials. Provisioning happens over UART via panel_set_creds (see
// panel_app.c), which calls panel_net_set_credentials() below.
#define MQTT_CREDS_NVS_NAMESPACE "panel_mqtt"
#define MQTT_CREDS_NVS_KEY_USER  "user"
#define MQTT_CREDS_NVS_KEY_PASS  "pass"

// In-memory copies populated from NVS at boot (or by
// panel_net_set_credentials at runtime). esp-mqtt holds pointers into
// these for the lifetime of the client, so the buffers must be static.
// Sized to match the install-pi.sh validation caps (64 user, 128 pass)
// plus a null terminator.
#define MQTT_USER_MAX_LEN 65
#define MQTT_PASS_MAX_LEN 129
static char s_mqtt_user[MQTT_USER_MAX_LEN] = {0};
static char s_mqtt_pass[MQTT_PASS_MAX_LEN] = {0};

static bool s_mqtt_started = false;
static esp_mqtt_client_handle_t s_client = NULL;
static volatile bool s_connected = false;
static const char *s_availability_topic = NULL;

static bool creds_present(void)
{
    return s_mqtt_user[0] != '\0' && s_mqtt_pass[0] != '\0';
}

// Pull username + password from the NVS panel_mqtt namespace into the
// static in-memory globals. Returns true iff both keys loaded
// successfully — partial reads (one key present, the other missing)
// are treated as "unprovisioned" and the in-memory copies stay empty.
static bool load_creds_from_nvs(void)
{
    nvs_handle_t h;
    esp_err_t err = nvs_open(MQTT_CREDS_NVS_NAMESPACE, NVS_READONLY, &h);
    if (err != ESP_OK)
    {
        // First boot or post-erase — no namespace yet. Not an error.
        return false;
    }

    char user_buf[MQTT_USER_MAX_LEN] = {0};
    char pass_buf[MQTT_PASS_MAX_LEN] = {0};
    size_t user_len = sizeof(user_buf);
    size_t pass_len = sizeof(pass_buf);

    bool ok = true;
    if (nvs_get_str(h, MQTT_CREDS_NVS_KEY_USER, user_buf, &user_len) != ESP_OK)
    {
        ok = false;
    }
    if (nvs_get_str(h, MQTT_CREDS_NVS_KEY_PASS, pass_buf, &pass_len) != ESP_OK)
    {
        ok = false;
    }
    nvs_close(h);

    if (!ok)
    {
        return false;
    }

    // Atomically install both into the in-memory globals. snprintf
    // is overkill but matches the codebase's idiom for length-bounded
    // string copies and guarantees null termination.
    snprintf(s_mqtt_user, sizeof(s_mqtt_user), "%s", user_buf);
    snprintf(s_mqtt_pass, sizeof(s_mqtt_pass), "%s", pass_buf);
    return true;
}

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

    ESP_LOGI(TAG, "Starting MQTT client, connecting to %s as %s",
             CONFIG_MQTT_BROKER_URI, s_mqtt_user);

    esp_mqtt_client_config_t mqtt_cfg = {
        .broker = {
            .address.uri = CONFIG_MQTT_BROKER_URI,
            .verification = {
                .certificate = (const char *)ca_cert_pem_start,
            },
        },
        .credentials = {
            .username = s_mqtt_user,
            .client_id = CONFIG_MQTT_CLIENT_ID,
            .authentication = {.password = s_mqtt_pass},
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
        .buffer = {
            // Default is 1024. Forwarded HA entity snapshots can exceed
            // that — e.g. the PetLibro feeding schedule with N plans, or a
            // select with many options. Anything larger arrives fragmented
            // across multiple MQTT_EVENT_DATA callbacks, and panel_app's
            // forwarders treat each chunk as a complete message and drop
            // both. Bumping the input buffer keeps payloads contiguous.
            //
            // 8 KB rather than just 4 KB to give headroom for the burst
            // case: cmd/resync (see panel_app.c) tells the integration to
            // republish every declared entity back-to-back, and esp-mqtt
            // shares the in/out buffer space for staging while the UART
            // forwarder drains. Cheap RAM on the C6, expensive to be
            // wrong about it.
            .size = 8192,
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
    if (!creds_present())
    {
        // Provisioning hasn't completed yet — bridge will send
        // panel_set_creds shortly after the UART link comes up. Stay
        // idle (Thread up, no MQTT) until that arrives.
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
    // Load MQTT credentials from NVS if previously provisioned. If the
    // namespace doesn't exist yet (first boot, post-erase, etc.), we
    // stay in the "unprovisioned" state — MQTT won't start until
    // panel_net_set_credentials() is called via panel_set_creds UART.
    if (load_creds_from_nvs())
    {
        ESP_LOGI(TAG, "Loaded MQTT credentials from NVS (user=%s)", s_mqtt_user);
    }
    else
    {
        ESP_LOGW(TAG, "MQTT credentials not in NVS — waiting for "
                      "provisioning over UART (panel_set_creds)");
    }

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

    ESP_LOGI(TAG, "Waiting for Thread attach + OMR address + creds before starting MQTT");
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

void panel_net_pause(void)
{
    if (!s_client || !s_mqtt_started)
    {
        return;
    }
    ESP_LOGI(TAG, "Pausing MQTT client (OTA in progress)");
    esp_mqtt_client_stop(s_client);
    s_mqtt_started = false;
    s_connected = false;
}

void panel_net_resume(void)
{
    if (!s_client || s_mqtt_started)
    {
        return;
    }
    ESP_LOGI(TAG, "Resuming MQTT client");
    esp_mqtt_client_start(s_client);
    s_mqtt_started = true;
}

esp_err_t panel_net_set_credentials(const char *user, const char *pass)
{
    if (!user || !pass || user[0] == '\0' || pass[0] == '\0')
    {
        return ESP_ERR_INVALID_ARG;
    }
    if (strlen(user) >= MQTT_USER_MAX_LEN || strlen(pass) >= MQTT_PASS_MAX_LEN)
    {
        return ESP_ERR_INVALID_SIZE;
    }

    // No-op when in-memory copies already match — avoids unnecessary
    // NVS writes on every bridge restart, which the bridge does
    // unconditionally to keep the provisioning path simple.
    if (strcmp(s_mqtt_user, user) == 0 && strcmp(s_mqtt_pass, pass) == 0)
    {
        ESP_LOGD(TAG, "panel_net_set_credentials: unchanged, ignoring");
        return ESP_OK;
    }

    nvs_handle_t h;
    esp_err_t err = nvs_open(MQTT_CREDS_NVS_NAMESPACE, NVS_READWRITE, &h);
    if (err != ESP_OK)
    {
        ESP_LOGE(TAG, "nvs_open(%s, RW) failed: %s",
                 MQTT_CREDS_NVS_NAMESPACE, esp_err_to_name(err));
        return err;
    }

    err = nvs_set_str(h, MQTT_CREDS_NVS_KEY_USER, user);
    if (err == ESP_OK)
    {
        err = nvs_set_str(h, MQTT_CREDS_NVS_KEY_PASS, pass);
    }
    if (err == ESP_OK)
    {
        err = nvs_commit(h);
    }
    nvs_close(h);

    if (err != ESP_OK)
    {
        ESP_LOGE(TAG, "Persisting MQTT credentials to NVS failed: %s",
                 esp_err_to_name(err));
        return err;
    }

    // Now that NVS holds the new values, install them in-memory.
    snprintf(s_mqtt_user, sizeof(s_mqtt_user), "%s", user);
    snprintf(s_mqtt_pass, sizeof(s_mqtt_pass), "%s", pass);
    ESP_LOGI(TAG, "MQTT credentials updated in NVS (user=%s)", s_mqtt_user);

    // Bring (or rebring) the MQTT client up against the new creds. If
    // it was already running we tear it down first; esp-mqtt holds
    // pointers into our strings but the destroy here is followed by a
    // fresh init in start_mqtt_client, so there's no aliasing issue.
    if (s_client)
    {
        ESP_LOGI(TAG, "Restarting MQTT client with new credentials");
        esp_mqtt_client_stop(s_client);
        esp_mqtt_client_destroy(s_client);
        s_client = NULL;
        s_mqtt_started = false;
        s_connected = false;
    }

    otInstance *instance = esp_openthread_get_instance();
    if (instance)
    {
        // If Thread is already attached + has OMR, MQTT starts now.
        // Otherwise the OpenThread state-change callback will do it
        // when those conditions are met.
        maybe_start_mqtt(instance);
    }

    return ESP_OK;
}
