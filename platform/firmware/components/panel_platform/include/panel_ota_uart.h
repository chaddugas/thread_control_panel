#pragma once

#include <stddef.h>
#include "esp_err.h"

#ifdef __cplusplus
extern "C"
{
#endif

    /**
     * Initialize the UART OTA receiver. Idempotent. Doesn't start anything —
     * just sets internal state. Call once at boot from panel_app_init().
     */
    void panel_ota_uart_init(void);

    /**
     * Handle an `{"type":"ota_begin", ...}` JSON envelope received from the
     * Pi over UART. Call from panel_app's UART line dispatcher when it sees
     * a line whose type is "ota_begin".
     *
     * The envelope must contain:
     *   - "size":   firmware byte count (matches the .bin file size)
     *   - "sha256": expected sha256 of the firmware (lowercase hex, 64 chars)
     *   - "version": informational only (logged, not validated)
     *
     * On a parse/setup error, sends an `ota_result` error envelope back over
     * UART and returns. On success, takes over the UART (raw mode + 921600
     * baud), spawns a worker task that drains incoming bytes onto the OTA
     * partition, and returns immediately. The worker eventually sends an
     * `ota_result` envelope (success or error) — and on success calls
     * esp_restart() to boot the new firmware.
     *
     * Returns true if the OTA was accepted (worker spawned). Returns false
     * if rejected (already in progress, parse error, etc.) — in that case
     * an `ota_result` error envelope has already been sent.
     */
    bool panel_ota_uart_handle_begin(const char *json, size_t len);

    /**
     * True while an OTA is in flight (between begin and result). panel_app
     * uses this to suppress sensor publishes / forwards while the UART is
     * carrying binary firmware bytes.
     */
    bool panel_ota_uart_is_active(void);

#ifdef __cplusplus
}
#endif
