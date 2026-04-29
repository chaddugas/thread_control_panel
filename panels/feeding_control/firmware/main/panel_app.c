#include "panel_app.h"
#include "panel_config.h"
#include "panel_lidar.h"
#include "panel_net.h"
#include "panel_sensors.h"
#include "panel_uart.h"

#include <stdbool.h>
#include <stdio.h>
#include <string.h>

#include "esp_err.h"
#include "esp_http_client.h"
#include "esp_log.h"
#include "esp_ota_ops.h"
#include "esp_partition.h"
#include "esp_system.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "mqtt_client.h"

static const char *TAG = "panel_app";

// Panel-itself state topics for this product. Compile-time concat of
// PANEL_ID (from panel_config.h) into the platform topic structure.
#define TOPIC_STATE_PROXIMITY  "thread_panel/" PANEL_ID "/state/proximity"
#define TOPIC_STATE_AMBIENT    "thread_panel/" PANEL_ID "/state/ambient_brightness"

// Sensor publish/forward cadence.
#define SENSOR_TICK_MS         1000
#define AMBIENT_PERIOD_TICKS   5     // publish ambient every 5 ticks (5 s)

// Ambient normalization ceiling: mV reading that maps to 100%. Tune this
// to the brightest "normal indoor" value the sensor produces — anything
// above saturates at 100% (fine for "dim the display when it's bright").
// Start at 500 mV; nudge if your room readings don't spread meaningfully.
#define AMBIENT_MV_CEILING     500

// Readiness of the HA integration, mirrored from ha_availability retained
// topic. Start offline so we don't publish into the void before we've heard
// from HA. Only MQTT publishes are gated; UART forwards to the Pi always go
// through because the local UI is served regardless of HA state.
static bool s_ha_online = false;

// Set to true while an OTA download is running. Periodic sensor publishes
// are suppressed during this window so the download isn't fighting for
// Thread bandwidth with our own chatter. UART forwards still go out — the
// Pi needs sensor updates regardless of OTA state.
static volatile bool s_ota_active = false;

static void publish_proximity(int dist_cm, int strength)
{
    char uart_payload[96];
    int u = snprintf(uart_payload, sizeof(uart_payload),
                     "{\"type\":\"sensor\",\"name\":\"proximity\","
                     "\"value\":%d,\"strength\":%d}",
                     dist_cm, strength);
    (void)panel_uart_send_line(uart_payload, u);

    if (!s_ha_online || s_ota_active)
    {
        return;
    }
    char mqtt_payload[64];
    int n = snprintf(mqtt_payload, sizeof(mqtt_payload),
                     "{\"value\":%d,\"strength\":%d}",
                     dist_cm, strength);
    panel_net_publish(TOPIC_STATE_PROXIMITY, mqtt_payload, n, 0, 1);
}

static void publish_ambient(int raw, int mv)
{
    // Normalize mV → 0..100 against AMBIENT_MV_CEILING. Sensor isn't
    // perfectly linear in lux, but this gives a usable "brightness
    // percent" for backlight curves.
    int pct = -1;
    if (mv >= 0)
    {
        pct = mv * 100 / AMBIENT_MV_CEILING;
        if (pct < 0) pct = 0;
        if (pct > 100) pct = 100;
    }

    char uart_payload[128];
    int u = snprintf(uart_payload, sizeof(uart_payload),
                     "{\"type\":\"sensor\",\"name\":\"ambient\","
                     "\"value\":%d,\"raw\":%d,\"mv\":%d}",
                     pct, raw, mv);
    (void)panel_uart_send_line(uart_payload, u);

    if (!s_ha_online || s_ota_active)
    {
        return;
    }
    char mqtt_payload[96];
    int n = snprintf(mqtt_payload, sizeof(mqtt_payload),
                     "{\"value\":%d,\"raw\":%d,\"mv\":%d}",
                     pct, raw, mv);
    panel_net_publish(TOPIC_STATE_AMBIENT, mqtt_payload, n, 0, 1);
}

// Periodic publisher: proximity every tick, ambient every AMBIENT_PERIOD_TICKS.
// Each call also logs the values so the console stays a useful status feed.
static void sensors_publish_task(void *arg)
{
    (void)arg;
    int ticks = 0;
    while (true)
    {
        int dist     = panel_lidar_get_distance_cm();
        int strength = panel_lidar_get_strength();
        if (dist >= 0)
        {
            publish_proximity(dist, strength);
        }

        bool ambient_due = (ticks % AMBIENT_PERIOD_TICKS) == 0;
        int amb_raw = -1, amb_mv = -1;
        if (ambient_due)
        {
            amb_raw = panel_ambient_read_raw();
            amb_mv  = panel_ambient_read_mv();
            if (amb_raw >= 0)
            {
                publish_ambient(amb_raw, amb_mv);
            }
        }

        if (ambient_due)
        {
            ESP_LOGI(TAG,
                     "ambient raw=%d mv=%d  lidar dist=%d cm strength=%d",
                     amb_raw, amb_mv, dist, strength);
        }
        else
        {
            ESP_LOGD(TAG, "lidar dist=%d cm strength=%d", dist, strength);
        }

        ticks++;
        vTaskDelay(pdMS_TO_TICKS(SENSOR_TICK_MS));
    }
}

static void on_uart_line(const char *line, size_t len)
{
    ESP_LOGI(TAG, "UART RX (%u bytes): %s", (unsigned)len, line);

    if (!s_ha_online)
    {
        ESP_LOGW(TAG, "UART line dropped — ha_availability is offline");
        return;
    }

    // Route by message type. Substring match is sufficient because the
    // bridge emits these as flat objects; nothing else would legitimately
    // contain that pattern.
    if (strstr(line, "\"type\":\"call_service\"") != NULL)
    {
        int msg_id = panel_net_publish(PANEL_TOPIC_CMD_CALL_SERVICE,
                                       line, (int)len, 0, 0);
        if (msg_id < 0)
        {
            ESP_LOGW(TAG, "call_service publish failed — MQTT not connected");
        }
        return;
    }

    // panel_state: bridge reports current value of a panel-itself control.
    // Extract the name from the envelope to build the state/<name> topic,
    // then publish the whole line retained. Receivers (HA entity classes)
    // ignore the type/name fields and read value directly.
    if (strstr(line, "\"type\":\"panel_state\"") != NULL)
    {
        const char *name_start = strstr(line, "\"name\":\"");
        if (name_start == NULL)
        {
            ESP_LOGW(TAG, "panel_state missing name field, dropping");
            return;
        }
        name_start += strlen("\"name\":\"");
        const char *name_end = strchr(name_start, '"');
        if (name_end == NULL)
        {
            ESP_LOGW(TAG, "panel_state name field unterminated, dropping");
            return;
        }
        int name_len = (int)(name_end - name_start);

        char topic[128];
        int tn = snprintf(topic, sizeof(topic), "%s%.*s",
                          PANEL_TOPIC_STATE_PREFIX, name_len, name_start);
        if (tn <= 0 || tn >= (int)sizeof(topic))
        {
            ESP_LOGW(TAG, "panel_state topic overflow, dropping");
            return;
        }

        int msg_id = panel_net_publish(topic, line, (int)len, 1, 1);
        if (msg_id < 0)
        {
            ESP_LOGW(TAG, "panel_state publish failed — MQTT not connected");
        }
        return;
    }

    // panel_cmd: bridge wants to fire an outbound command on the C6's
    // behalf. Same name-extraction shape as panel_state, but published to
    // cmd/<name> non-retained (commands are events, not state). The first
    // user is `cmd/resync`, fired by the bridge whenever the UART link
    // first comes up — asks the integration to republish every entity
    // snapshot so the kiosk catches up after the boot-time race where the
    // Pi wasn't ready to read UART when the C6 first subscribed to MQTT.
    if (strstr(line, "\"type\":\"panel_cmd\"") != NULL)
    {
        const char *name_start = strstr(line, "\"name\":\"");
        if (name_start == NULL)
        {
            ESP_LOGW(TAG, "panel_cmd missing name field, dropping");
            return;
        }
        name_start += strlen("\"name\":\"");
        const char *name_end = strchr(name_start, '"');
        if (name_end == NULL)
        {
            ESP_LOGW(TAG, "panel_cmd name field unterminated, dropping");
            return;
        }
        int name_len = (int)(name_end - name_start);

        char topic[128];
        int tn = snprintf(topic, sizeof(topic), "%s%.*s",
                          PANEL_TOPIC_CMD_PREFIX, name_len, name_start);
        if (tn <= 0 || tn >= (int)sizeof(topic))
        {
            ESP_LOGW(TAG, "panel_cmd topic overflow, dropping");
            return;
        }

        int msg_id = panel_net_publish(topic, line, (int)len, 0, 0);
        if (msg_id < 0)
        {
            ESP_LOGW(TAG, "panel_cmd publish failed — MQTT not connected");
        }
        return;
    }

    ESP_LOGW(TAG, "UART line has no known routing, dropping: %s", line);
}

// Forward the current ha_availability value to the Pi bridge so the WS
// layer (and UI) can gate commands and render a loading/offline state.
static void forward_ha_availability_to_uart(bool online)
{
    char line[64];
    int n = snprintf(line, sizeof(line),
                     "{\"type\":\"ha_availability\",\"value\":\"%s\"}",
                     online ? "online" : "offline");
    (void)panel_uart_send_line(line, n);
}

// On offline→online transition, republish current cached sensor values once
// so the retained state topics are fresh. Normal cadence resumes on the
// next sensors_publish_task iteration.
static void republish_current_sensor_values(void)
{
    int dist = panel_lidar_get_distance_cm();
    int strength = panel_lidar_get_strength();
    if (dist >= 0)
    {
        publish_proximity(dist, strength);
    }
    int raw = panel_ambient_read_raw();
    int mv  = panel_ambient_read_mv();
    if (raw >= 0)
    {
        publish_ambient(raw, mv);
    }
}

// Download firmware from `url` and write into the idle OTA partition.
// Returns ESP_OK on success (caller should reboot); any other return
// code is a logged error and the current image stays running.
static esp_err_t download_ota_image(const char *url)
{
    const esp_partition_t *update = esp_ota_get_next_update_partition(NULL);
    if (update == NULL)
    {
        ESP_LOGE(TAG, "OTA: no update partition available");
        return ESP_FAIL;
    }
    ESP_LOGI(TAG, "OTA: target partition '%s' @ 0x%" PRIx32 " size 0x%" PRIx32,
             update->label, update->address, update->size);

    esp_http_client_config_t http_cfg = {
        .url = url,
        .timeout_ms = 10000,
        .keep_alive_enable = true,
    };
    esp_http_client_handle_t client = esp_http_client_init(&http_cfg);
    if (client == NULL)
    {
        ESP_LOGE(TAG, "OTA: esp_http_client_init failed");
        return ESP_FAIL;
    }

    esp_ota_handle_t ota_handle = 0;
    bool ota_begun = false;
    esp_err_t err = esp_http_client_open(client, 0);
    if (err != ESP_OK)
    {
        ESP_LOGE(TAG, "OTA: http open failed: %s", esp_err_to_name(err));
        goto cleanup;
    }

    int content_length = esp_http_client_fetch_headers(client);
    if (content_length <= 0)
    {
        ESP_LOGE(TAG, "OTA: invalid content_length %d", content_length);
        err = ESP_FAIL;
        goto cleanup;
    }
    int status = esp_http_client_get_status_code(client);
    if (status != 200)
    {
        ESP_LOGE(TAG, "OTA: server returned HTTP %d", status);
        err = ESP_FAIL;
        goto cleanup;
    }
    ESP_LOGI(TAG, "OTA: downloading %d bytes", content_length);

    err = esp_ota_begin(update, content_length, &ota_handle);
    if (err != ESP_OK)
    {
        ESP_LOGE(TAG, "OTA: esp_ota_begin: %s", esp_err_to_name(err));
        goto cleanup;
    }
    ota_begun = true;

    char buf[1024];
    int total = 0;
    int last_log = 0;
    while (true)
    {
        int n = esp_http_client_read(client, buf, sizeof(buf));
        if (n < 0)
        {
            ESP_LOGE(TAG, "OTA: http read failed");
            err = ESP_FAIL;
            goto cleanup;
        }
        if (n == 0)
        {
            break;  // EOF
        }
        err = esp_ota_write(ota_handle, buf, n);
        if (err != ESP_OK)
        {
            ESP_LOGE(TAG, "OTA: esp_ota_write: %s", esp_err_to_name(err));
            goto cleanup;
        }
        total += n;
        if (total - last_log >= content_length / 10)
        {
            ESP_LOGI(TAG, "OTA: %d / %d bytes", total, content_length);
            last_log = total;
        }
    }

    if (total != content_length)
    {
        ESP_LOGE(TAG, "OTA: short read: %d / %d bytes", total, content_length);
        err = ESP_FAIL;
        goto cleanup;
    }

    err = esp_ota_end(ota_handle);
    ota_begun = false;  // esp_ota_end finalizes the handle either way
    if (err != ESP_OK)
    {
        ESP_LOGE(TAG, "OTA: esp_ota_end (image invalid?): %s", esp_err_to_name(err));
        goto cleanup;
    }

    err = esp_ota_set_boot_partition(update);
    if (err != ESP_OK)
    {
        ESP_LOGE(TAG, "OTA: set_boot_partition: %s", esp_err_to_name(err));
    }

cleanup:
    if (ota_begun)
    {
        esp_ota_abort(ota_handle);
    }
    esp_http_client_close(client);
    esp_http_client_cleanup(client);
    return err;
}

// OTA download runs in its own task so it doesn't block the MQTT event
// loop. The URL is heap-allocated by the caller and freed here.
static void ota_task(void *arg)
{
    char *url = (char *)arg;
    ESP_LOGI(TAG, "OTA: starting download from %s", url);

    // Suppress our own sensor publishes while downloading so they don't
    // compete with the HTTP stream for Thread bandwidth.
    s_ota_active = true;
    esp_err_t err = download_ota_image(url);
    if (err == ESP_OK)
    {
        ESP_LOGW(TAG, "OTA: success, rebooting into new image");
        // Let MQTT flush any pending publishes before the hard reset.
        vTaskDelay(pdMS_TO_TICKS(1000));
        esp_restart();
    }
    else
    {
        ESP_LOGE(TAG, "OTA: failed: %s — staying on current image",
                 esp_err_to_name(err));
    }
    s_ota_active = false;

    free(url);
    vTaskDelete(NULL);
}

// cmd/ota payload is `{"url":"http://..."}` (or with whitespace after the
// colon, depending on the publisher). Pull the URL out tolerantly: find
// the "url": key, skip whitespace, expect an opening quote, read until
// the closing quote.
static void handle_ota_command(const char *data, int data_len)
{
    const char key[] = "\"url\":";
    const char *p = data;
    const char *end = data + data_len;
    const char *after_key = NULL;
    for (; p + sizeof(key) - 1 <= end; p++)
    {
        if (memcmp(p, key, sizeof(key) - 1) == 0)
        {
            after_key = p + sizeof(key) - 1;
            break;
        }
    }
    if (after_key == NULL)
    {
        ESP_LOGW(TAG, "cmd/ota: no url field, dropping");
        return;
    }
    while (after_key < end && (*after_key == ' ' || *after_key == '\t'))
    {
        after_key++;
    }
    if (after_key >= end || *after_key != '"')
    {
        ESP_LOGW(TAG, "cmd/ota: url value not a string, dropping");
        return;
    }
    const char *url_start = after_key + 1;
    const char *url_end = memchr(url_start, '"', end - url_start);
    if (url_end == NULL)
    {
        ESP_LOGW(TAG, "cmd/ota: url field unterminated, dropping");
        return;
    }
    size_t url_len = url_end - url_start;
    char *url = malloc(url_len + 1);
    if (url == NULL)
    {
        ESP_LOGE(TAG, "cmd/ota: out of memory for url");
        return;
    }
    memcpy(url, url_start, url_len);
    url[url_len] = '\0';

    if (xTaskCreate(ota_task, "ota", 8192, url, 5, NULL) != pdPASS)
    {
        ESP_LOGE(TAG, "cmd/ota: failed to spawn ota task");
        free(url);
    }
}

static void on_ha_availability(const char *data, int data_len)
{
    bool was_online = s_ha_online;
    bool is_online = (data_len == 6 && memcmp(data, "online", 6) == 0);

    s_ha_online = is_online;
    forward_ha_availability_to_uart(is_online);

    if (is_online && !was_online)
    {
        ESP_LOGI(TAG, "ha_availability → online; republishing sensor state");
        republish_current_sensor_values();
    }
    else if (!is_online && was_online)
    {
        ESP_LOGI(TAG, "ha_availability → offline; suppressing MQTT publishes");
    }
}

void panel_app_init(void)
{
    // Tell the platform which topic to use for availability — must happen
    // before panel_net_start() so the MQTT client is configured with the
    // corresponding LWT.
    panel_net_set_availability_topic(PANEL_TOPIC_AVAILABILITY);

    ESP_ERROR_CHECK(panel_uart_init(on_uart_line));
    ESP_ERROR_CHECK(panel_sensors_init());
    ESP_ERROR_CHECK(panel_lidar_init());

    xTaskCreate(sensors_publish_task, "sensors_pub",
                4096, NULL, 5, NULL);
}

void panel_app_on_connected(esp_mqtt_client_handle_t client)
{
    // Readiness signal. Retained message delivers immediately if HA is
    // already online.
    int msg_id = esp_mqtt_client_subscribe(client,
                                           PANEL_TOPIC_HA_AVAILABILITY, 0);
    ESP_LOGI(TAG, "Subscribed to %s, msg_id=%d",
             PANEL_TOPIC_HA_AVAILABILITY, msg_id);

    // Forwarded HA entities + roster. Retained state for each declared
    // entity_id is redelivered on subscribe, so we hand the Pi a complete
    // snapshot as a side effect.
    msg_id = esp_mqtt_client_subscribe(client,
                                       PANEL_TOPIC_STATE_ENTITY_WILDCARD, 0);
    ESP_LOGI(TAG, "Subscribed to %s, msg_id=%d",
             PANEL_TOPIC_STATE_ENTITY_WILDCARD, msg_id);

    msg_id = esp_mqtt_client_subscribe(client, PANEL_TOPIC_STATE_ROSTER, 0);
    ESP_LOGI(TAG, "Subscribed to %s, msg_id=%d",
             PANEL_TOPIC_STATE_ROSTER, msg_id);

    // Panel-itself set/* wildcard — HA-driven changes to panel-owned
    // state. Wrap each and forward to the Pi over UART.
    msg_id = esp_mqtt_client_subscribe(client, PANEL_TOPIC_SET_WILDCARD, 0);
    ESP_LOGI(TAG, "Subscribed to %s, msg_id=%d",
             PANEL_TOPIC_SET_WILDCARD, msg_id);

    // C6 self-reboot command.
    msg_id = esp_mqtt_client_subscribe(client, PANEL_TOPIC_CMD_REBOOT_C6, 0);
    ESP_LOGI(TAG, "Subscribed to %s, msg_id=%d",
             PANEL_TOPIC_CMD_REBOOT_C6, msg_id);

    // Pi-side reboot command — forwarded over UART for the bridge to act on.
    msg_id = esp_mqtt_client_subscribe(client, PANEL_TOPIC_CMD_REBOOT_PI, 0);
    ESP_LOGI(TAG, "Subscribed to %s, msg_id=%d",
             PANEL_TOPIC_CMD_REBOOT_PI, msg_id);

    // OTA firmware download command.
    msg_id = esp_mqtt_client_subscribe(client, PANEL_TOPIC_CMD_OTA, 0);
    ESP_LOGI(TAG, "Subscribed to %s, msg_id=%d",
             PANEL_TOPIC_CMD_OTA, msg_id);

    // Wi-Fi management — forwarded to Pi as panel_cmd envelopes.
    msg_id = esp_mqtt_client_subscribe(client, PANEL_TOPIC_CMD_WIFI_CONNECT, 0);
    ESP_LOGI(TAG, "Subscribed to %s, msg_id=%d",
             PANEL_TOPIC_CMD_WIFI_CONNECT, msg_id);

    msg_id = esp_mqtt_client_subscribe(client, PANEL_TOPIC_CMD_WIFI_SCAN, 0);
    ESP_LOGI(TAG, "Subscribed to %s, msg_id=%d",
             PANEL_TOPIC_CMD_WIFI_SCAN, msg_id);
}

// Buffer size for the wrapped UART line we forward to the Pi. Must be big
// enough for:
//   - the largest retained entity_state snapshot (entities declared with
//     `attributes: all` can reach 1.5 KB for a multi-plan schedule)
//   - the roster, which grows linearly with the manifest entity count —
//     ~160 bytes per entity, so 16 entities ≈ 2.5 KB. Bumped from 2048
//     to 4096 after observing `roster envelope overflow (2529 bytes),
//     dropping` on the Front Room Smart Feeder roster.
//
// Allocated on the stack inside each forward_* helper. The MQTT task's
// stack (CONFIG_MQTT_TASK_STACK_SIZE, default 6144) is the upper bound;
// going past ~5 KB here would risk overflow. If a future panel grows the
// roster past ~3.5 KB, switch the roster forwarder to heap allocation
// rather than bumping this further.
#define FORWARD_BUF_SIZE 4096

static void forward_entity_state(const char *entity_id, int entity_id_len,
                                 const char *data, int data_len)
{
    // The retained payload is a well-formed JSON object
    // `{"state":"...","attributes":{...}}`. We strip the outer braces and
    // inline the inner fields alongside type + entity_id to match the
    // UART protocol in docs/build_plan_v1.md.
    if (data_len < 2 || data[0] != '{' || data[data_len - 1] != '}')
    {
        ESP_LOGW(TAG, "entity_state payload malformed (%.*s), dropping",
                 data_len, data);
        return;
    }

    char buf[FORWARD_BUF_SIZE];
    int n = snprintf(buf, sizeof(buf),
                     "{\"type\":\"entity_state\",\"entity_id\":\"%.*s\",%.*s}",
                     entity_id_len, entity_id,
                     data_len - 2, data + 1);
    if (n <= 0 || n >= (int)sizeof(buf))
    {
        ESP_LOGW(TAG, "entity_state envelope overflow (%d bytes), dropping", n);
        return;
    }
    (void)panel_uart_send_line(buf, n);
}

static void forward_roster(const char *data, int data_len)
{
    if (data_len < 2 || data[0] != '{' || data[data_len - 1] != '}')
    {
        ESP_LOGW(TAG, "roster payload malformed, dropping");
        return;
    }

    char buf[FORWARD_BUF_SIZE];
    int n = snprintf(buf, sizeof(buf),
                     "{\"type\":\"roster\",%.*s}",
                     data_len - 2, data + 1);
    if (n <= 0 || n >= (int)sizeof(buf))
    {
        ESP_LOGW(TAG, "roster envelope overflow (%d bytes), dropping", n);
        return;
    }
    (void)panel_uart_send_line(buf, n);
}

// Panel-itself set/<name>: wrap with a panel_set envelope that names the
// control, then forward over UART for the bridge to act on. Payload from
// HA is a raw JSON object like {"value": 50}; we splice that in alongside
// the control name so the Pi gets a single self-describing line.
static void forward_panel_set(const char *name, int name_len,
                              const char *data, int data_len)
{
    if (data_len < 2 || data[0] != '{' || data[data_len - 1] != '}')
    {
        ESP_LOGW(TAG, "panel_set payload malformed, dropping");
        return;
    }

    char buf[FORWARD_BUF_SIZE];
    int n = snprintf(buf, sizeof(buf),
                     "{\"type\":\"panel_set\",\"name\":\"%.*s\",%.*s}",
                     name_len, name,
                     data_len - 2, data + 1);
    if (n <= 0 || n >= (int)sizeof(buf))
    {
        ESP_LOGW(TAG, "panel_set envelope overflow (%d bytes), dropping", n);
        return;
    }
    (void)panel_uart_send_line(buf, n);
}

// Panel-itself cmd/<name>: wrap with a panel_cmd envelope and forward over
// UART. Empty/missing payload (the typical "{}" reboot case) sends a bare
// envelope; payloads with fields (wifi_connect: ssid+password) get spliced
// in alongside the name. Either way the bridge's dispatch_cmd routes by
// name to the right control handler.
static void forward_panel_cmd(const char *name, int name_len,
                              const char *data, int data_len)
{
    char buf[FORWARD_BUF_SIZE];
    int n;

    bool has_payload = (data_len > 2 &&
                        data[0] == '{' &&
                        data[data_len - 1] == '}');
    if (has_payload)
    {
        n = snprintf(buf, sizeof(buf),
                     "{\"type\":\"panel_cmd\",\"name\":\"%.*s\",%.*s}",
                     name_len, name,
                     data_len - 2, data + 1);
    }
    else
    {
        n = snprintf(buf, sizeof(buf),
                     "{\"type\":\"panel_cmd\",\"name\":\"%.*s\"}",
                     name_len, name);
    }
    if (n <= 0 || n >= (int)sizeof(buf))
    {
        ESP_LOGW(TAG, "panel_cmd envelope overflow (%d bytes), dropping", n);
        return;
    }
    (void)panel_uart_send_line(buf, n);
}

void panel_app_on_data(esp_mqtt_client_handle_t client,
                       const char *topic, int topic_len,
                       const char *data, int data_len)
{
    (void)client;

    // ha_availability: flag update + UART forward + transition republish.
    const size_t ha_topic_len = strlen(PANEL_TOPIC_HA_AVAILABILITY);
    if ((size_t)topic_len == ha_topic_len &&
        memcmp(topic, PANEL_TOPIC_HA_AVAILABILITY, ha_topic_len) == 0)
    {
        ESP_LOGI(TAG, "ha_availability: %.*s", data_len, data);
        on_ha_availability(data, data_len);
        return;
    }

    // state/entity/<entity_id>: forward to Pi as entity_state envelope.
    const size_t entity_prefix_len = strlen(PANEL_TOPIC_STATE_ENTITY_PREFIX);
    if ((size_t)topic_len > entity_prefix_len &&
        memcmp(topic, PANEL_TOPIC_STATE_ENTITY_PREFIX, entity_prefix_len) == 0)
    {
        const char *entity_id = topic + entity_prefix_len;
        int entity_id_len = topic_len - (int)entity_prefix_len;
        ESP_LOGI(TAG, "entity_state %.*s: %.*s",
                 entity_id_len, entity_id, data_len, data);
        forward_entity_state(entity_id, entity_id_len, data, data_len);
        return;
    }

    // state/_roster: forward to Pi as roster envelope.
    const size_t roster_topic_len = strlen(PANEL_TOPIC_STATE_ROSTER);
    if ((size_t)topic_len == roster_topic_len &&
        memcmp(topic, PANEL_TOPIC_STATE_ROSTER, roster_topic_len) == 0)
    {
        ESP_LOGI(TAG, "roster: %.*s", data_len, data);
        forward_roster(data, data_len);
        return;
    }

    // set/<name>: HA-driven change to a panel-itself control. Forward to
    // Pi for the bridge to act on.
    const size_t set_prefix_len = strlen(PANEL_TOPIC_SET_PREFIX);
    if ((size_t)topic_len > set_prefix_len &&
        memcmp(topic, PANEL_TOPIC_SET_PREFIX, set_prefix_len) == 0)
    {
        const char *name = topic + set_prefix_len;
        int name_len = topic_len - (int)set_prefix_len;
        ESP_LOGI(TAG, "panel_set %.*s: %.*s",
                 name_len, name, data_len, data);
        forward_panel_set(name, name_len, data, data_len);
        return;
    }

    // cmd/reboot_c6: self-reboot. No Pi involvement.
    const size_t reboot_c6_topic_len = strlen(PANEL_TOPIC_CMD_REBOOT_C6);
    if ((size_t)topic_len == reboot_c6_topic_len &&
        memcmp(topic, PANEL_TOPIC_CMD_REBOOT_C6, reboot_c6_topic_len) == 0)
    {
        ESP_LOGW(TAG, "cmd/reboot_c6 received — restarting");
        esp_restart();
        return;  // unreachable but keeps the shape consistent
    }

    // cmd/reboot_pi: forward to Pi as a panel_cmd.
    const size_t reboot_pi_topic_len = strlen(PANEL_TOPIC_CMD_REBOOT_PI);
    if ((size_t)topic_len == reboot_pi_topic_len &&
        memcmp(topic, PANEL_TOPIC_CMD_REBOOT_PI, reboot_pi_topic_len) == 0)
    {
        ESP_LOGI(TAG, "panel_cmd reboot_pi");
        forward_panel_cmd("reboot_pi", (int)strlen("reboot_pi"),
                          data, data_len);
        return;
    }

    // cmd/ota: start a firmware update from the URL in the payload.
    const size_t ota_topic_len = strlen(PANEL_TOPIC_CMD_OTA);
    if ((size_t)topic_len == ota_topic_len &&
        memcmp(topic, PANEL_TOPIC_CMD_OTA, ota_topic_len) == 0)
    {
        ESP_LOGW(TAG, "cmd/ota received: %.*s", data_len, data);
        handle_ota_command(data, data_len);
        return;
    }

    // cmd/wifi_connect: forward to Pi as panel_cmd with ssid+password+security.
    const size_t wifi_connect_topic_len = strlen(PANEL_TOPIC_CMD_WIFI_CONNECT);
    if ((size_t)topic_len == wifi_connect_topic_len &&
        memcmp(topic, PANEL_TOPIC_CMD_WIFI_CONNECT, wifi_connect_topic_len) == 0)
    {
        // Don't log the payload — it carries the cleartext password.
        ESP_LOGI(TAG, "panel_cmd wifi_connect (%d byte payload)", data_len);
        forward_panel_cmd("wifi_connect", (int)strlen("wifi_connect"),
                          data, data_len);
        return;
    }

    // cmd/wifi_scan: trigger an immediate rescan + republish on the Pi.
    const size_t wifi_scan_topic_len = strlen(PANEL_TOPIC_CMD_WIFI_SCAN);
    if ((size_t)topic_len == wifi_scan_topic_len &&
        memcmp(topic, PANEL_TOPIC_CMD_WIFI_SCAN, wifi_scan_topic_len) == 0)
    {
        ESP_LOGI(TAG, "panel_cmd wifi_scan");
        forward_panel_cmd("wifi_scan", (int)strlen("wifi_scan"),
                          data, data_len);
        return;
    }

    // Unmatched topic — log only. Shouldn't happen in practice unless a
    // subscription list is added above without a matching handler.
    ESP_LOGW(TAG, "Data on unhandled topic %.*s: %.*s",
             topic_len, topic, data_len, data);
}
