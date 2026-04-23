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
#include "esp_log.h"
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

// Readiness of the HA integration, mirrored from ha_availability retained
// topic. Start offline so we don't publish into the void before we've heard
// from HA. Only MQTT publishes are gated; UART forwards to the Pi always go
// through because the local UI is served regardless of HA state.
static bool s_ha_online = false;

static void publish_proximity(int dist_cm, int strength)
{
    char uart_payload[96];
    int u = snprintf(uart_payload, sizeof(uart_payload),
                     "{\"type\":\"sensor\",\"name\":\"proximity\","
                     "\"value\":%d,\"strength\":%d}",
                     dist_cm, strength);
    (void)panel_uart_send_line(uart_payload, u);

    if (!s_ha_online)
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
    // Normalize mV → 0..100 against the ADC's effective full-scale (~3100 mV
    // at DB_12 attenuation). Sensor isn't perfectly linear in lux, but this
    // gives a usable "brightness percent" for backlight curves.
    int pct = -1;
    if (mv >= 0)
    {
        pct = mv * 100 / 3100;
        if (pct < 0) pct = 0;
        if (pct > 100) pct = 100;
    }

    char uart_payload[128];
    int u = snprintf(uart_payload, sizeof(uart_payload),
                     "{\"type\":\"sensor\",\"name\":\"ambient\","
                     "\"value\":%d,\"raw\":%d,\"mv\":%d}",
                     pct, raw, mv);
    (void)panel_uart_send_line(uart_payload, u);

    if (!s_ha_online)
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

    // Route by message type. For V1 the Pi only sends call_service
    // commands; add new branches here when other outbound types appear.
    // Substring match is sufficient because the bridge emits these as
    // flat objects; nothing else would legitimately contain that pattern.
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
}

// Buffer size for the wrapped UART line we forward to the Pi. Must be big
// enough for the largest retained entity snapshot — entities declared with
// `attributes: all` can reach several hundred bytes, and the envelope adds
// ~60 bytes on top.
#define FORWARD_BUF_SIZE 2048

static void forward_entity_state(const char *entity_id, int entity_id_len,
                                 const char *data, int data_len)
{
    // The retained payload is a well-formed JSON object
    // `{"state":"...","attributes":{...}}`. We strip the outer braces and
    // inline the inner fields alongside type + entity_id to match the
    // UART protocol in docs/build_plan.md.
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

    // Unmatched topic — log only. Shouldn't happen in practice unless a
    // subscription list is added above without a matching handler.
    ESP_LOGW(TAG, "Data on unhandled topic %.*s: %.*s",
             topic_len, topic, data_len, data);
}
