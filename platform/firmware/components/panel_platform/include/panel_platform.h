#pragma once

#ifdef __cplusplus
extern "C"
{
#endif

    /**
     * Bring up the platform: NVS, default event loop, netif, eventfd,
     * OpenThread CLI (if enabled), OpenThread stack, optional state
     * indicator and CLI extensions, network auto-start.
     *
     * Call once from app_main before any product-specific init.
     */
    void panel_platform_init(void);

#ifdef __cplusplus
}
#endif
