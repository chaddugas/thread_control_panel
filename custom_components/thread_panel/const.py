"""Constants for the thread_panel integration."""

DOMAIN = "thread_panel"

CONF_MANIFEST_YAML = "manifest_yaml"
CONF_PANEL_ID = "panel_id"
CONF_INCLUDE_PRERELEASES = "include_prereleases"
DEFAULT_INCLUDE_PRERELEASES = False

# GitHub repo the update entity polls for releases. cut-release substitutes
# __REPO__ at release-build time using `git remote get-url origin`. For
# in-tree dev (running this integration straight from the repo without
# going through cut-release), the placeholder string just makes the API
# call fail cleanly — latest_version stays None until a real release is
# pulled.
GITHUB_REPO = "__REPO__"

TOPIC_AVAILABILITY = "thread_panel/{panel_id}/ha_availability"
TOPIC_ROSTER = "thread_panel/{panel_id}/state/_roster"
TOPIC_ENTITY_STATE = "thread_panel/{panel_id}/state/entity/{entity_id}"
TOPIC_ENTITY_STATE_WILDCARD = "thread_panel/{panel_id}/state/entity/#"
TOPIC_CALL_SERVICE = "thread_panel/{panel_id}/cmd/call_service"

# Resync command — bridge fires this whenever its UART link to the C6 first
# comes up (cold boot, Pi restart, link drop). Integration responds by
# republishing the roster + every declared entity_state, so the kiosk
# catches up after the boot-time race where the Pi UART wasn't ready when
# the C6 first subscribed and retained messages were lost.
TOPIC_CMD_RESYNC = "thread_panel/{panel_id}/cmd/resync"

# Panel-itself topics — the C6's own availability (LWT-backed) and the
# per-panel sensor readings it publishes periodically.
TOPIC_PANEL_AVAILABILITY = "thread_panel/{panel_id}/availability"
TOPIC_PANEL_PROXIMITY = "thread_panel/{panel_id}/state/proximity"
TOPIC_PANEL_AMBIENT_BRIGHTNESS = "thread_panel/{panel_id}/state/ambient_brightness"

# Update flow — version retained by C6 on each MQTT connect, status not
# retained (high-churn). Command published by HA on user-driven install.
TOPIC_PANEL_VERSION = "thread_panel/{panel_id}/state/version"
TOPIC_PANEL_UPDATE_STATUS = "thread_panel/{panel_id}/state/update_status"
TOPIC_PANEL_CMD_UPDATE = "thread_panel/{panel_id}/cmd/update"

# Panel-itself controls — bidirectional state + command channels for the
# Pi-owned controls (display power, wifi radio, reboot).
TOPIC_PANEL_SET = "thread_panel/{panel_id}/set/{name}"
TOPIC_PANEL_STATE = "thread_panel/{panel_id}/state/{name}"
TOPIC_PANEL_CMD = "thread_panel/{panel_id}/cmd/{name}"

# Per-panel cross-entity registry under hass.data[DOMAIN]. The select +
# text entities for wifi management register their entity_ids here so
# the connect button can read their current state at press time.
DATA_ENTITIES = "entities"

PAYLOAD_ONLINE = "online"
PAYLOAD_OFFLINE = "offline"

STORAGE_VERSION = 1
STORAGE_KEY_FMT = "thread_panel.{panel_id}.published_topics"
