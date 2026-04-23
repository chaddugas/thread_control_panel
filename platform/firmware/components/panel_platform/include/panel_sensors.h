#pragma once

#include "esp_err.h"

#ifdef __cplusplus
extern "C"
{
#endif

    /**
     * Initialize all platform sensors. Idempotent. Currently sets up the
     * TEMT6000 ambient-light reader on ADC1 CH0 (GPIO0 / D0).
     */
    esp_err_t panel_sensors_init(void);

    /**
     * Read the TEMT6000 ambient-light sensor.
     *
     * @return raw ADC count (0..4095 at default 12-bit), or -1 on error.
     */
    int panel_ambient_read_raw(void);

    /**
     * Read the TEMT6000 ambient-light sensor in millivolts.
     *
     * Requires ADC calibration. Returns -1 if calibration is unavailable
     * (eFuse not burned) or the read fails.
     */
    int panel_ambient_read_mv(void);

#ifdef __cplusplus
}
#endif
