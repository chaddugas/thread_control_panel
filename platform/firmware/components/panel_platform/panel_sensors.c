#include "panel_sensors.h"

#include "esp_adc/adc_cali.h"
#include "esp_adc/adc_cali_scheme.h"
#include "esp_adc/adc_oneshot.h"
#include "esp_log.h"

static const char *TAG = "panel_sensors";

// TEMT6000 wiring (XIAO ESP32-C6):
//   VCC  -> 3V3 output pin
//   GND  -> shared GND with the C6 (and the Pi via the existing UART link)
//   SIG  -> D0 = GPIO0 = ADC1_CH0
//
// DB_12 attenuation gives ~0..3.1V usable range — sensor's full output (0..VCC,
// where VCC is ~3.3V) maps cleanly onto the ADC's effective range.
#define AMBIENT_ADC_UNIT     ADC_UNIT_1
#define AMBIENT_ADC_CHANNEL  ADC_CHANNEL_0
#define AMBIENT_ADC_ATTEN    ADC_ATTEN_DB_12

static adc_oneshot_unit_handle_t s_adc_handle = NULL;
static adc_cali_handle_t s_cali_handle = NULL;
static bool s_initialized = false;

esp_err_t panel_sensors_init(void)
{
    if (s_initialized)
    {
        return ESP_OK;
    }

    adc_oneshot_unit_init_cfg_t init_cfg = {
        .unit_id = AMBIENT_ADC_UNIT,
    };
    esp_err_t err = adc_oneshot_new_unit(&init_cfg, &s_adc_handle);
    if (err != ESP_OK)
    {
        ESP_LOGE(TAG, "adc_oneshot_new_unit failed: %s", esp_err_to_name(err));
        return err;
    }

    adc_oneshot_chan_cfg_t chan_cfg = {
        .atten = AMBIENT_ADC_ATTEN,
        .bitwidth = ADC_BITWIDTH_DEFAULT,
    };
    err = adc_oneshot_config_channel(s_adc_handle, AMBIENT_ADC_CHANNEL, &chan_cfg);
    if (err != ESP_OK)
    {
        ESP_LOGE(TAG, "adc_oneshot_config_channel failed: %s", esp_err_to_name(err));
        return err;
    }

    // Calibration is optional — raw reads still work without it. C6's ADC
    // calibration scheme is curve-fitting (vs. line-fitting on older parts).
    adc_cali_curve_fitting_config_t cali_cfg = {
        .unit_id  = AMBIENT_ADC_UNIT,
        .atten    = AMBIENT_ADC_ATTEN,
        .bitwidth = ADC_BITWIDTH_DEFAULT,
    };
    err = adc_cali_create_scheme_curve_fitting(&cali_cfg, &s_cali_handle);
    if (err != ESP_OK)
    {
        ESP_LOGW(TAG, "ADC calibration unavailable (%s); raw reads only",
                 esp_err_to_name(err));
        s_cali_handle = NULL;
    }

    s_initialized = true;
    ESP_LOGI(TAG, "Ambient sensor up on ADC1 CH0 (D0/GPIO0), atten=DB_12");
    return ESP_OK;
}

int panel_ambient_read_raw(void)
{
    if (!s_initialized)
    {
        return -1;
    }
    int raw = 0;
    if (adc_oneshot_read(s_adc_handle, AMBIENT_ADC_CHANNEL, &raw) != ESP_OK)
    {
        return -1;
    }
    return raw;
}

int panel_ambient_read_mv(void)
{
    int raw = panel_ambient_read_raw();
    if (raw < 0 || s_cali_handle == NULL)
    {
        return -1;
    }
    int mv = 0;
    if (adc_cali_raw_to_voltage(s_cali_handle, raw, &mv) != ESP_OK)
    {
        return -1;
    }
    return mv;
}
