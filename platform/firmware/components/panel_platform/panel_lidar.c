#include "panel_lidar.h"
#include "panel_platform_config.h"

#include <stdint.h>

#include "driver/uart.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static const char *TAG = "panel_lidar";

// TF-Mini Plus protocol — 9-byte frames at 100 Hz by default.
// Layout: 0x59 0x59 dist_lo dist_hi strength_lo strength_hi temp_lo temp_hi checksum
// Checksum is sum of the first 8 bytes, low byte only.
#define LIDAR_FRAME_BYTES   9
#define LIDAR_HEADER_BYTE   0x59
#define LIDAR_RX_RING_BYTES 256
#define LIDAR_TASK_STACK    3072
#define LIDAR_TASK_PRIORITY 6

// Volatile so the smoketest task / future consumers see fresh values without
// memory barriers; aligned 32-bit reads on the C6 are atomic.
static volatile int s_distance_cm = -1;
static volatile int s_strength = -1;
static bool s_initialized = false;
static TaskHandle_t s_lidar_task = NULL;
static bool s_paused = false;

static void lidar_task(void *arg)
{
    (void)arg;
    uint8_t frame[LIDAR_FRAME_BYTES];
    int idx = 0;

    for (;;)
    {
        uint8_t b;
        int n = uart_read_bytes((uart_port_t)PANEL_LIDAR_UART_PORT,
                                &b, 1, pdMS_TO_TICKS(100));
        if (n != 1)
        {
            continue;
        }

        // Two-byte header sync: need 0x59 0x59 to begin a frame.
        if (idx == 0)
        {
            if (b == LIDAR_HEADER_BYTE)
            {
                frame[idx++] = b;
            }
            continue;
        }
        if (idx == 1)
        {
            if (b == LIDAR_HEADER_BYTE)
            {
                frame[idx++] = b;
            }
            else
            {
                idx = 0;  // resync: this byte might be the next header start
                if (b == LIDAR_HEADER_BYTE)
                {
                    frame[idx++] = b;
                }
            }
            continue;
        }

        frame[idx++] = b;
        if (idx < LIDAR_FRAME_BYTES)
        {
            continue;
        }

        // Full frame — verify checksum.
        uint16_t sum = 0;
        for (int i = 0; i < LIDAR_FRAME_BYTES - 1; i++)
        {
            sum += frame[i];
        }
        if ((sum & 0xFF) != frame[LIDAR_FRAME_BYTES - 1])
        {
            ESP_LOGD(TAG, "checksum mismatch, dropping frame");
            idx = 0;
            continue;
        }

        s_distance_cm = (int)(frame[2] | ((uint16_t)frame[3] << 8));
        s_strength    = (int)(frame[4] | ((uint16_t)frame[5] << 8));
        idx = 0;
    }
}

esp_err_t panel_lidar_init(void)
{
    if (s_initialized)
    {
        return ESP_OK;
    }

    const uart_config_t cfg = {
        .baud_rate  = PANEL_LIDAR_UART_BAUD,
        .data_bits  = UART_DATA_8_BITS,
        .parity     = UART_PARITY_DISABLE,
        .stop_bits  = UART_STOP_BITS_1,
        .flow_ctrl  = UART_HW_FLOWCTRL_DISABLE,
        .source_clk = UART_SCLK_DEFAULT,
    };

    esp_err_t err = uart_driver_install((uart_port_t)PANEL_LIDAR_UART_PORT,
                                        LIDAR_RX_RING_BYTES, 0, 0, NULL, 0);
    if (err != ESP_OK)
    {
        ESP_LOGE(TAG, "uart_driver_install failed: %s", esp_err_to_name(err));
        return err;
    }

    err = uart_param_config((uart_port_t)PANEL_LIDAR_UART_PORT, &cfg);
    if (err != ESP_OK)
    {
        ESP_LOGE(TAG, "uart_param_config failed: %s", esp_err_to_name(err));
        return err;
    }

    err = uart_set_pin((uart_port_t)PANEL_LIDAR_UART_PORT,
                       PANEL_LIDAR_TX_PIN, PANEL_LIDAR_RX_PIN,
                       UART_PIN_NO_CHANGE, UART_PIN_NO_CHANGE);
    if (err != ESP_OK)
    {
        ESP_LOGE(TAG, "uart_set_pin failed: %s", esp_err_to_name(err));
        return err;
    }

    BaseType_t ok = xTaskCreate(lidar_task, "panel_lidar",
                                LIDAR_TASK_STACK, NULL,
                                LIDAR_TASK_PRIORITY, &s_lidar_task);
    if (ok != pdPASS)
    {
        ESP_LOGE(TAG, "task create failed");
        return ESP_FAIL;
    }

    s_initialized = true;
    ESP_LOGI(TAG, "LiDAR up on UART%d RX=%d (D3) @ %d baud",
             PANEL_LIDAR_UART_PORT, PANEL_LIDAR_RX_PIN, PANEL_LIDAR_UART_BAUD);
    return ESP_OK;
}

int panel_lidar_get_distance_cm(void)
{
    return s_distance_cm;
}

int panel_lidar_get_strength(void)
{
    return s_strength;
}

void panel_lidar_pause(void)
{
    if (!s_initialized || s_paused)
    {
        return;
    }
    ESP_LOGI(TAG, "Pausing LiDAR (OTA in progress)");
    // Disable RX interrupts before suspending the task — otherwise the
    // hardware FIFO would still raise interrupts as bytes arrive (~900
    // bytes/s) for nothing to consume them.
    (void)uart_disable_rx_intr((uart_port_t)PANEL_LIDAR_UART_PORT);
    if (s_lidar_task)
    {
        vTaskSuspend(s_lidar_task);
    }
    s_paused = true;
}

void panel_lidar_resume(void)
{
    if (!s_initialized || !s_paused)
    {
        return;
    }
    ESP_LOGI(TAG, "Resuming LiDAR");
    // Drain any stale bytes the hardware FIFO captured before we masked
    // the interrupt. The parser self-resyncs on the 0x59 0x59 header so
    // a few dropped frames after resume are expected.
    (void)uart_flush_input((uart_port_t)PANEL_LIDAR_UART_PORT);
    (void)uart_enable_rx_intr((uart_port_t)PANEL_LIDAR_UART_PORT);
    if (s_lidar_task)
    {
        vTaskResume(s_lidar_task);
    }
    s_paused = false;
}
