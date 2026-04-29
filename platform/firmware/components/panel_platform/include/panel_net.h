#pragma once

#ifdef __cplusplus
extern "C"
{
#endif

    /**
     * Tell the platform which MQTT topic to use for the C6's availability.
     * If set before panel_net_start(), the MQTT client is configured with
     * an LWT that publishes "offline" on ungraceful disconnect, and
     * "online" is published on every successful connect.
     *
     * The topic string must live for the lifetime of the MQTT client —
     * typically a string literal from the product's panel_config.h.
     *
     * Leaving this unset disables availability entirely (no LWT, no
     * online publish) — useful for headless diagnostic builds.
     */
    void panel_net_set_availability_topic(const char *topic);

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

    /**
     * Pause / resume the MQTT client. Used by panel_ota_uart while a UART
     * OTA is in progress so esp-mqtt's TLS-handshake reconnect attempts
     * don't compete with the OTA stream for Thread bandwidth + CPU. After
     * pause, the client is fully stopped (no reconnect attempts); resume
     * re-establishes from scratch. Idempotent.
     */
    void panel_net_pause(void);
    void panel_net_resume(void);

#ifdef __cplusplus
}
#endif
