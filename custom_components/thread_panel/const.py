"""Constants for the thread_panel integration."""

DOMAIN = "thread_panel"

CONF_MANIFEST_YAML = "manifest_yaml"
CONF_PANEL_ID = "panel_id"

TOPIC_AVAILABILITY = "thread_panel/{panel_id}/ha_availability"
TOPIC_ROSTER = "thread_panel/{panel_id}/state/_roster"
TOPIC_ENTITY_STATE = "thread_panel/{panel_id}/state/entity/{entity_id}"
TOPIC_ENTITY_STATE_WILDCARD = "thread_panel/{panel_id}/state/entity/#"
TOPIC_CALL_SERVICE = "thread_panel/{panel_id}/cmd/call_service"

# Panel-itself topics — the C6's own availability (LWT-backed) and the
# per-panel sensor readings it publishes periodically.
TOPIC_PANEL_AVAILABILITY = "thread_panel/{panel_id}/availability"
TOPIC_PANEL_PROXIMITY = "thread_panel/{panel_id}/state/proximity"
TOPIC_PANEL_AMBIENT_BRIGHTNESS = "thread_panel/{panel_id}/state/ambient_brightness"

# Panel-itself controls — bidirectional state + command channels for the
# Pi-owned controls (display power, wifi radio, reboot).
TOPIC_PANEL_SET = "thread_panel/{panel_id}/set/{name}"
TOPIC_PANEL_STATE = "thread_panel/{panel_id}/state/{name}"
TOPIC_PANEL_CMD = "thread_panel/{panel_id}/cmd/{name}"

PAYLOAD_ONLINE = "online"
PAYLOAD_OFFLINE = "offline"

STORAGE_VERSION = 1
STORAGE_KEY_FMT = "thread_panel.{panel_id}.published_topics"
