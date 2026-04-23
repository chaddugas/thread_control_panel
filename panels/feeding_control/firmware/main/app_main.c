/*
 * SPDX-FileCopyrightText: 2021-2026 Espressif Systems (Shanghai) CO LTD
 *
 * SPDX-License-Identifier: CC0-1.0
 *
 * Derived from the ESP-IDF OpenThread CLI example.
 */

#include "panel_platform.h"
#include "panel_app.h"
#include "panel_net.h"

void app_main(void)
{
    panel_platform_init();   // NVS, event loop, netif, OpenThread
    panel_app_init();        // product setup (UART bridge to Pi)
    panel_net_start();       // MQTT once Thread attaches + OMR address arrives
}
