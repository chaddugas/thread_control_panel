"""Constants for the thread_panel integration."""

DOMAIN = "thread_panel"

CONF_MANIFEST_YAML = "manifest_yaml"
CONF_PANEL_ID = "panel_id"

TOPIC_AVAILABILITY = "thread_panel/{panel_id}/ha_availability"
TOPIC_ROSTER = "thread_panel/{panel_id}/state/_roster"
TOPIC_ENTITY_STATE = "thread_panel/{panel_id}/state/entity/{entity_id}"
TOPIC_ENTITY_STATE_WILDCARD = "thread_panel/{panel_id}/state/entity/#"
TOPIC_CALL_SERVICE = "thread_panel/{panel_id}/cmd/call_service"

PAYLOAD_ONLINE = "online"
PAYLOAD_OFFLINE = "offline"

STORAGE_VERSION = 1
STORAGE_KEY_FMT = "thread_panel.{panel_id}.published_topics"
