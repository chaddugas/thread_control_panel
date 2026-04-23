#pragma once

// Hardware-fixed values shared by every thread_panel in the fleet.
// Per-product values (PANEL_ID, product topic strings) live in each panel's
// own panel_config.h.

// UART link to the Pi (XIAO ESP32-C6: D6 = GPIO16 (TX), D7 = GPIO17 (RX))
#define PANEL_UART_PORT     1       // UART_NUM_1
#define PANEL_UART_BAUD     115200
#define PANEL_UART_TX_PIN   16
#define PANEL_UART_RX_PIN   17

// Override OpenThread's discovered DNS (defaults to Google public DNS) with
// AdGuard at HA's static ULA so the broker hostname's split-horizon AAAA
// rewrite resolves over Thread.
#define PANEL_DNS_SERVER    "fd00:9db1:1410:d98c::10"

// TF-Mini Plus LiDAR (XIAO ESP32-C6: D3 = GPIO21, D4 = GPIO22).
// Uses UART0 routed via GPIO matrix — UART0 is otherwise free since the
// console is on USB-Serial-JTAG.
#define PANEL_LIDAR_UART_PORT  0       // UART_NUM_0
#define PANEL_LIDAR_UART_BAUD  115200
#define PANEL_LIDAR_RX_PIN     21      // C6 D3 — TF-Mini TX lands here
#define PANEL_LIDAR_TX_PIN     22      // C6 D4 — wired but unused (TF-Mini streams)
