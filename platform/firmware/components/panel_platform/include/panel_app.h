#pragma once

#include "mqtt_client.h"

#ifdef __cplusplus
extern "C"
{
#endif

    /**
     * Initialize product-specific subsystems that need to be up before
     * networking (UART bridge to the Pi, etc.). Call from app_main before
     * panel_net_start().
     */
    void panel_app_init(void);

    /**
     * Called by panel_net when the MQTT client has connected to the broker.
     * Use it to subscribe to product-specific topics and publish any
     * startup state (discovery configs, initial availability, etc.).
     */
    void panel_app_on_connected(esp_mqtt_client_handle_t client);

    /**
     * Called by panel_net for every MQTT_EVENT_DATA. Topic and data pointers
     * are not null-terminated; use the provided lengths.
     */
    void panel_app_on_data(esp_mqtt_client_handle_t client,
                           const char *topic, int topic_len,
                           const char *data, int data_len);

#ifdef __cplusplus
}
#endif
