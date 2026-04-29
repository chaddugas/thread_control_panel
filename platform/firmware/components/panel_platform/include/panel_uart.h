#pragma once

#include <stddef.h>
#include <stdint.h>
#include "esp_err.h"

#ifdef __cplusplus
extern "C"
{
#endif

    /**
     * Callback fired by the UART RX task for each complete line received.
     * The line is null-terminated and stripped of trailing '\r'/'\n'; `len`
     * is the length of that payload (matches strlen(line)).
     *
     * The callback runs on the RX task — do not block for long.
     */
    typedef void (*panel_uart_line_cb_t)(const char *line, size_t len);

    /**
     * Callback fired by the UART RX task for raw byte chunks while raw mode
     * is active. The callback runs on the RX task — do not block for long.
     * For OTA writes specifically, push bytes into a stream buffer and let a
     * separate worker task drain them onto flash.
     */
    typedef void (*panel_uart_raw_cb_t)(const uint8_t *data, size_t len, void *user);

    /**
     * Configure UART and spawn the RX task. Idempotent on repeated calls.
     * `on_line` may be NULL (RX bytes are consumed and dropped).
     */
    esp_err_t panel_uart_init(panel_uart_line_cb_t on_line);

    /**
     * Write `len` bytes of `line` followed by a single '\n'. Thread-safe
     * with respect to other panel_uart_send_line callers.
     */
    esp_err_t panel_uart_send_line(const char *line, size_t len);

    /**
     * Write `len` raw bytes — no framing, no newline. Used during OTA after
     * raw mode + high baud has been negotiated. Thread-safe.
     */
    esp_err_t panel_uart_write_raw(const uint8_t *data, size_t len);

    /**
     * Switch the RX task into raw byte-pass-through mode. Subsequent UART
     * input bypasses line accumulation and is delivered as-is to `cb`. Use
     * panel_uart_clear_raw_mode() to switch back to the line callback.
     *
     * Returns ESP_ERR_INVALID_STATE if not initialized.
     */
    esp_err_t panel_uart_set_raw_mode(panel_uart_raw_cb_t cb, void *user);
    esp_err_t panel_uart_clear_raw_mode(void);

    /**
     * Reconfigure the UART baud rate at runtime. Used during OTA to switch
     * between the steady-state 115200 and the OTA transfer's 921600. Both
     * peers must change in lockstep — there's no in-band signal once one
     * side has switched.
     */
    esp_err_t panel_uart_set_baud(int baud);

#ifdef __cplusplus
}
#endif
