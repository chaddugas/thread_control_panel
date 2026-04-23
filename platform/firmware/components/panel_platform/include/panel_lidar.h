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

#ifdef __cplusplus
}
#endif
