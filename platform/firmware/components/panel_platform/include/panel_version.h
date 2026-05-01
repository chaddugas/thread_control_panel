#pragma once

// Firmware version. Updated by tools/cut-release.zsh as part of the
// version-bump phase, alongside platform/integration/thread_panel/manifest.json.
// Read by panel_app to publish the retained `state/version` MQTT topic that
// the HA `update.panel_firmware` entity (Phase 3) reads as installed_version.
//
// Format: vMAJOR.MINOR.PATCH or vMAJOR.MINOR.PATCH-TAG.N (semver). Stub
// "v0.0.0-dev" applies until cut-release writes a real release version.
#define PANEL_VERSION "v2.0.0-beta.27"
