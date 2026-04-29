#pragma once

#include "esp_err.h"

#ifdef __cplusplus
extern "C"
{
#endif

    /**
     * Configure UART for the TF-Mini Plus and spawn the parser task.
     * Idempotent.
     */
    esp_err_t panel_lidar_init(void);

    /**
     * Most recently parsed distance in cm, or -1 if no valid frame has
     * been received yet.
     */
    int panel_lidar_get_distance_cm(void);

    /**
     * Signal strength of the most recent frame (0..65535). The TF-Mini
     * datasheet treats values <100 or ==65535 as unreliable.
     */
    int panel_lidar_get_strength(void);

    /**
     * Pause / resume the lidar reader. Used by panel_ota_uart during a
     * UART OTA so the lidar's per-byte uart_read_bytes calls + UART0 RX
     * interrupts don't compete with the OTA stream on UART1 for CPU /
     * interrupt latency. Suspends the parser task and disables UART0 RX
     * interrupts on pause; reverses both on resume. Idempotent.
     *
     * After resume, the next few frames may be dropped on checksum (the
     * UART0 hardware FIFO can carry stale bytes from the pause window);
     * the parser self-resyncs on the next 0x59 0x59 header.
     */
    void panel_lidar_pause(void);
    void panel_lidar_resume(void);

#ifdef __cplusplus
}
#endif
