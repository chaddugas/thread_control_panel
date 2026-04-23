#include "panel_app.h"
#include "panel_config.h"
#include "panel_lidar.h"
#include "panel_net.h"
#include "panel_sensors.h"
#include "panel_uart.h"

#include <stdio.h>

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

static void publish_proximity(int dist_cm, int strength)
{
    char mqtt_payload[64];
    int n = snprintf(mqtt_payload, sizeof(mqtt_payload),
                     "{\"value\":%d,\"strength\":%d}",
                     dist_cm, strength);
    panel_net_publish(TOPIC_STATE_PROXIMITY, mqtt_payload, n, 0, 1);

    char uart_payload[96];
    int u = snprintf(uart_payload, sizeof(uart_payload),
                     "{\"type\":\"sensor\",\"name\":\"proximity\","
                     "\"value\":%d,\"strength\":%d}",
                     dist_cm, strength);
    (void)panel_uart_send_line(uart_payload, u);
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

    char mqtt_payload[96];
    int n = snprintf(mqtt_payload, sizeof(mqtt_payload),
                     "{\"value\":%d,\"raw\":%d,\"mv\":%d}",
                     pct, raw, mv);
    panel_net_publish(TOPIC_STATE_AMBIENT, mqtt_payload, n, 0, 1);

    char uart_payload[128];
    int u = snprintf(uart_payload, sizeof(uart_payload),
                     "{\"type\":\"sensor\",\"name\":\"ambient\","
                     "\"value\":%d,\"raw\":%d,\"mv\":%d}",
                     pct, raw, mv);
    (void)panel_uart_send_line(uart_payload, u);
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

    // POC: forward the raw line to a debug MQTT topic so the full
    // Pi → UART → C6 → MQTT → HA path can be verified before the real
    // command schema lands.
    int msg_id = panel_net_publish(PANEL_TOPIC_FROM_PI, line, (int)len, 0, 0);
    if (msg_id < 0)
    {
        ESP_LOGW(TAG, "UART line dropped — MQTT not connected");
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
    int msg_id = esp_mqtt_client_subscribe(client, PANEL_TOPIC_ECHO, 0);
    ESP_LOGI(TAG, "Subscribed to %s, msg_id=%d", PANEL_TOPIC_ECHO, msg_id);

    msg_id = esp_mqtt_client_publish(client, PANEL_TOPIC_HELLO,
                                     PANEL_HELLO_PAYLOAD, 0, 1, 0);
    ESP_LOGI(TAG, "Published hello message, msg_id=%d", msg_id);
}

void panel_app_on_data(esp_mqtt_client_handle_t client,
                       const char *topic, int topic_len,
                       const char *data, int data_len)
{
    (void)client;
    ESP_LOGI(TAG, "Data on %.*s: %.*s",
             topic_len, topic, data_len, data);

    // POC: forward MQTT payloads to the Pi so the reverse path is also
    // provable. Pi can ignore lines it doesn't care about.
    (void)panel_uart_send_line(data, (size_t)data_len);
}
