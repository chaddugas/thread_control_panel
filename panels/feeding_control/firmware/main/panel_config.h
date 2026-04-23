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

// Readiness signal published by the thread_panel HA integration. Retained,
// LWT-backed. We gate our state publishes on this being "online" so we
// don't fill the Thread mesh with messages no one is listening to.
#define PANEL_TOPIC_HA_AVAILABILITY  "thread_panel/" PANEL_ID "/ha_availability"

// Forwarded HA entities. The integration publishes one retained topic per
// declared entity_id plus a retained roster topic. We subscribe to both,
// wrap each message with a typed envelope, and forward to the Pi over UART
// so the bridge can broadcast to the UI.
#define PANEL_TOPIC_STATE_ENTITY_PREFIX    "thread_panel/" PANEL_ID "/state/entity/"
#define PANEL_TOPIC_STATE_ENTITY_WILDCARD  "thread_panel/" PANEL_ID "/state/entity/#"
#define PANEL_TOPIC_STATE_ROSTER           "thread_panel/" PANEL_ID "/state/_roster"
