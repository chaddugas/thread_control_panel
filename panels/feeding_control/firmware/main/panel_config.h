#pragma once

// Product identity for the feeding_control panel.
// Used to namespace MQTT topics and Home Assistant discovery objects.
#define PANEL_ID "feeding_control"

// POC topics — placeholders that preserve the original ot_mqtt_test
// behavior. Will be replaced by the thread_panel/feeding_control/* schema
// from docs/build_plan.md once HA discovery + bridging are wired up.
#define PANEL_TOPIC_ECHO     "panel/test/echo"
#define PANEL_TOPIC_HELLO    "panel/test/hello"
#define PANEL_HELLO_PAYLOAD  "Hello from XIAO C6"

// Debug topic for UART → MQTT echo. Also POC.
#define PANEL_TOPIC_FROM_PI  "panel/test/from_pi"
