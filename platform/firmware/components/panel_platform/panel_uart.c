#include "panel_uart.h"
#include "panel_platform_config.h"

#include <string.h>

#include "driver/uart.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/semphr.h"

static const char *TAG = "panel_uart";

#define RX_RING_BYTES    1024
#define TX_RING_BYTES    1024
#define LINE_BUF_BYTES   1024
#define RX_CHUNK_BYTES   64
#define RX_TASK_STACK    4096
#define RX_TASK_PRIORITY 10

static panel_uart_line_cb_t s_on_line = NULL;
static SemaphoreHandle_t s_tx_mutex = NULL;
static bool s_initialized = false;

static void rx_task(void *arg)
{
    (void)arg;
    char line[LINE_BUF_BYTES];
    size_t len = 0;
    uint8_t chunk[RX_CHUNK_BYTES];

    for (;;)
    {
        int n = uart_read_bytes((uart_port_t)PANEL_UART_PORT, chunk,
                                sizeof(chunk), pdMS_TO_TICKS(100));
        if (n <= 0)
        {
            continue;
        }

        for (int i = 0; i < n; i++)
        {
            char c = (char)chunk[i];
            if (c == '\n')
            {
                // Strip trailing '\r' for CRLF-sending peers.
                if (len > 0 && line[len - 1] == '\r')
                {
                    len--;
                }
                line[len] = '\0';
                if (len > 0 && s_on_line)
                {
                    s_on_line(line, len);
                }
                len = 0;
            }
            else if (len < LINE_BUF_BYTES - 1)
            {
                line[len++] = c;
            }
            else
            {
                // Overflow — drop the partial line and resync on the next '\n'.
                ESP_LOGW(TAG, "RX line exceeded %d bytes, dropping", LINE_BUF_BYTES - 1);
                len = 0;
            }
        }
    }
}

esp_err_t panel_uart_init(panel_uart_line_cb_t on_line)
{
    if (s_initialized)
    {
        s_on_line = on_line;
        return ESP_OK;
    }

    s_on_line = on_line;

    const uart_config_t cfg = {
        .baud_rate  = PANEL_UART_BAUD,
        .data_bits  = UART_DATA_8_BITS,
        .parity     = UART_PARITY_DISABLE,
        .stop_bits  = UART_STOP_BITS_1,
        .flow_ctrl  = UART_HW_FLOWCTRL_DISABLE,
        .source_clk = UART_SCLK_DEFAULT,
    };

    esp_err_t err = uart_driver_install((uart_port_t)PANEL_UART_PORT,
                                        RX_RING_BYTES, TX_RING_BYTES,
                                        0, NULL, 0);
    if (err != ESP_OK)
    {
        ESP_LOGE(TAG, "uart_driver_install failed: %s", esp_err_to_name(err));
        return err;
    }

    err = uart_param_config((uart_port_t)PANEL_UART_PORT, &cfg);
    if (err != ESP_OK)
    {
        ESP_LOGE(TAG, "uart_param_config failed: %s", esp_err_to_name(err));
        return err;
    }

    err = uart_set_pin((uart_port_t)PANEL_UART_PORT,
                       PANEL_UART_TX_PIN, PANEL_UART_RX_PIN,
                       UART_PIN_NO_CHANGE, UART_PIN_NO_CHANGE);
    if (err != ESP_OK)
    {
        ESP_LOGE(TAG, "uart_set_pin failed: %s", esp_err_to_name(err));
        return err;
    }

    s_tx_mutex = xSemaphoreCreateMutex();
    if (!s_tx_mutex)
    {
        ESP_LOGE(TAG, "Failed to create TX mutex");
        return ESP_ERR_NO_MEM;
    }

    BaseType_t ok = xTaskCreate(rx_task, "panel_uart_rx",
                                RX_TASK_STACK, NULL,
                                RX_TASK_PRIORITY, NULL);
    if (ok != pdPASS)
    {
        ESP_LOGE(TAG, "Failed to spawn RX task");
        return ESP_FAIL;
    }

    s_initialized = true;
    ESP_LOGI(TAG, "UART%d up on TX=%d RX=%d @ %d baud",
             PANEL_UART_PORT, PANEL_UART_TX_PIN, PANEL_UART_RX_PIN, PANEL_UART_BAUD);
    return ESP_OK;
}

esp_err_t panel_uart_send_line(const char *line, size_t len)
{
    if (!s_initialized)
    {
        return ESP_ERR_INVALID_STATE;
    }

    xSemaphoreTake(s_tx_mutex, portMAX_DELAY);
    int w1 = uart_write_bytes((uart_port_t)PANEL_UART_PORT, line, len);
    int w2 = uart_write_bytes((uart_port_t)PANEL_UART_PORT, "\n", 1);
    xSemaphoreGive(s_tx_mutex);

    return (w1 == (int)len && w2 == 1) ? ESP_OK : ESP_FAIL;
}
