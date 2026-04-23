#pragma once

#include <stddef.h>
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
     * Configure UART and spawn the RX task. Idempotent on repeated calls.
     * `on_line` may be NULL (RX bytes are consumed and dropped).
     */
    esp_err_t panel_uart_init(panel_uart_line_cb_t on_line);

    /**
     * Write `len` bytes of `line` followed by a single '\n'. Thread-safe
     * with respect to other panel_uart_send_line callers.
     */
    esp_err_t panel_uart_send_line(const char *line, size_t len);

#ifdef __cplusplus
}
#endif
