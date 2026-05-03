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

// Generic outbound command prefix. Bridge → C6 (over UART, as panel_cmd
// envelopes) → MQTT cmd/<name>. Currently used for `cmd/resync` to ask the
// integration to republish every entity_state on demand (e.g. after Pi
// boot, when retained messages were lost because the Pi UART wasn't ready
// yet when the C6 first subscribed).
#define PANEL_TOPIC_CMD_PREFIX             "thread_panel/" PANEL_ID "/cmd/"

// Panel-itself control channel. `set/#` carries HA-driven changes to
// panel-owned state (brightness, screen_on, wifi_*); forwarded to the Pi
// over UART for the bridge to act on. `state/<name>` carries the Pi's
// current value back; the C6 publishes those retained so HA sees current
// state after the Pi acts or on any reconnect.
#define PANEL_TOPIC_SET_PREFIX             "thread_panel/" PANEL_ID "/set/"
#define PANEL_TOPIC_SET_WILDCARD           "thread_panel/" PANEL_ID "/set/#"
#define PANEL_TOPIC_STATE_PREFIX           "thread_panel/" PANEL_ID "/state/"

// C6 self-reboot. The C6 subscribes directly and calls esp_restart() —
// no Pi involvement. Separate from reboot_pi, which goes UART → Pi →
// shutdown command.
#define PANEL_TOPIC_CMD_REBOOT_C6          "thread_panel/" PANEL_ID "/cmd/reboot_c6"

// Firmware version. Published retained on each MQTT connect so the HA
// `update.panel_firmware` entity (Phase 3) can read installed_version.
// PANEL_VERSION comes from panel_version.h, updated by cut-release.
#define PANEL_TOPIC_STATE_VERSION          "thread_panel/" PANEL_ID "/state/version"

// Pi-side commands. Forwarded to the Pi over UART as panel_cmd envelopes
// for the bridge to dispatch. Subscribed explicitly (rather than via a
// cmd/# wildcard) to avoid receiving our own cmd/call_service publishes
// back as echoes.
#define PANEL_TOPIC_CMD_REBOOT_PI          "thread_panel/" PANEL_ID "/cmd/reboot_pi"

// Wi-Fi management commands. Forwarded to the Pi over UART as panel_cmd
// envelopes for the bridge's wifi_manage module to dispatch. Subscribed
// explicitly (rather than via cmd/#) for the same reason as reboot_pi —
// avoid receiving our own cmd/call_service publishes back as echoes.
#define PANEL_TOPIC_CMD_WIFI_CONNECT       "thread_panel/" PANEL_ID "/cmd/wifi_connect"
#define PANEL_TOPIC_CMD_WIFI_SCAN          "thread_panel/" PANEL_ID "/cmd/wifi_scan"

// HA-driven full-system update. Forwarded to the Pi over UART as a
// panel_cmd envelope; bridge spawns panel-update.sh which runs the whole
// download → install → flash-C6 sequence. Payload is a JSON object with
// a `version` field (e.g. {"version":"v2.0.0-beta.4"}).
#define PANEL_TOPIC_CMD_UPDATE             "thread_panel/" PANEL_ID "/cmd/update"
