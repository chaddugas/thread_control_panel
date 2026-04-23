#pragma once

// Product identity for the feeding_control panel.
// Used to namespace MQTT topics and Home Assistant discovery objects.
#define PANEL_ID "feeding_control"

// The C6's own availability. Published "online" on MQTT connect, and
// set as the LWT so the broker publishes "offline" automatically on
// ungraceful disconnect. HA entity availability is derived from this.
#define PANEL_TOPIC_AVAILABILITY  "thread_panel/" PANEL_ID "/availability"

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

// Outbound command channel — call_service messages sent by the UI arrive
// here over UART and get published to this topic for the integration to
// dispatch as HA service calls.
#define PANEL_TOPIC_CMD_CALL_SERVICE       "thread_panel/" PANEL_ID "/cmd/call_service"
