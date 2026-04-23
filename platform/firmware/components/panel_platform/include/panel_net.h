#pragma once

#ifdef __cplusplus
extern "C"
{
#endif

    /**
     * Bring up the MQTT client once Thread has attached.
     *
     * Registers an OpenThread state-change callback that starts the MQTT
     * client when the device reaches a child/router/leader role. Safe to
     * call after esp_openthread_start().
     */
    void panel_net_start(void);

    /**
     * Publish on the MQTT broker from any task. Returns the message id on
     * success, -1 if the client is not currently connected.
     *
     * `len` may be 0 to auto-compute strlen(data). Thread-safe.
     */
    int panel_net_publish(const char *topic, const char *data, int len,
                          int qos, int retain);

#ifdef __cplusplus
}
#endif
