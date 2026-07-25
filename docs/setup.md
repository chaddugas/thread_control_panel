# Set up a panel

From parts on a desk to a paired panel on the wall: assemble the hardware, run one install command, and pair from Home Assistant. Building the interface it shows comes after — that's [Build your own UI](build-your-own-ui.md).

## What you need

- A **Raspberry Pi** (a Zero 2 W is enough) with an SD card and power supply.
- An **ESP32-C6 dev board** — the panel's Thread radio. It connects to the Pi over its native USB port.
- A **touchscreen**: HDMI or DSI, your pick. DSI panels need one extra install-time answer (below).
- A **Home Assistant** installation with a working **Thread network** (a border router the panel can join). Thread is the panel's only production link to HA.
- A **2.4 GHz WPA2 WiFi network** for install and pairing. The Pi's WiFi is used only to bootstrap — it turns off once the panel is on Thread — but the Pi Zero 2 W's radio is 2.4 GHz-only and does not support WPA3-SAE, so a WPA3-only network will fail with what looks like a wrong password.

## Assemble

1. Connect the C6 to the Pi with a USB cable on the C6's **native USB** port (the one wired to the chip, not a UART bridge). The Pi powers and flashes it over this cable — no buttons, no separate programmer.
2. Connect the touchscreen (HDMI or DSI ribbon) and its power/touch wiring per its own documentation.
3. Optional sensors (a UART LiDAR for presence, an analog ambient-light sensor) wire to the C6's pins; you'll declare them at pairing time.

## Prepare the Pi

Flash **Raspberry Pi OS Lite** with Raspberry Pi Imager, setting your WiFi credentials, hostname, and SSH access in the imager's settings. Boot the Pi and confirm you can ssh in.

For a **DSI panel**, you can pre-answer the display question before first boot: write your panel's overlay name (e.g. `vc4-kms-dsi-<model>`) to a file called `panel-display.txt` in the SD card's boot partition. HDMI needs nothing — it's auto-detected.

## Install

```bash
curl -sSL https://github.com/chaddugas/thread_control_panel/releases/latest/download/install-pi.sh | bash
```

The installer handles the whole panel side: it downloads the release, flashes the radio chip over the USB cable, installs the kiosk and bridge services, and reboots into the panel software. On a DSI panel with no pre-seeded answer it shows a picker of the display overlays Pi OS ships — choose your panel's model. You can also pass it directly: `install-pi.sh --display=<overlay>`.

Re-running the same command later is safe: it detects what's already current and skips it. `--factory` is the full wipe-and-reinstall.

After the reboot the screen shows the **pairing screen** with a countdown — the panel is announcing itself to your network and waiting for Home Assistant.

## Pair from Home Assistant

1. **Install the integration** (a one-time drop-in per HA): download `thread_panel.zip` from the [latest release](https://github.com/chaddugas/thread_control_panel/releases/latest), unzip it into your HA config's `custom_components/` (so `custom_components/thread_panel/` exists), and restart Home Assistant. That's the only manual install it ever needs — from then on the integration updates itself through its own update entity.
2. The panel appears under **Settings → Devices & Services** as a discovered **Thread Panel**. Open it.
3. **Pick the entities** the panel should see — its interface receives exactly these, nothing else.
4. **Fill the panel's hardware page**: an optional display name, the display rotation, and — only if you wired sensors — the pasted sensor config (next section).
5. **Confirm the 6-digit code**: HA shows one, the panel's screen shows one. If they match, confirm. HA then seals and pushes the panel's credentials and Thread dataset.

The panel joins your Thread mesh, connects to HA directly, and **turns its own WiFi off** — that's the steady state, and it's expected. Removing the panel's device from HA reverses everything: the panel wipes its credentials and returns to the pairing screen.

You can revisit the hardware page later from the device's **Configure** button — rotation and sensor edits apply live, no re-pairing.

## Sensor config

Sensorless panels skip this — leave the paste field empty. A panel with sensors declares them as TOML blocks; paste only the blocks you wired:

```toml
[firmware.sensors.lidar]        # UART presence/distance sensor
present = true
uart = 0
rx_pin = 21
tx_pin = 22
default_publish_hz = 1

[firmware.sensors.ambient]      # analog ambient-light sensor
present = true
adc_unit = 1
adc_channel = 0
default_publish_period_s = 5
default_mv_ceiling = 500
```

Pins and units are your wiring; the `default_*` fields are starting points you can tune later from HA. Anything you omit falls back to the firmware's defaults, and Home Assistant keeps the config — a re-paired or reinstalled panel gets it back automatically.

## After setup

- **Updates** arrive through update entities in HA: each panel has one, and the **Thread Panel self-update** entry (it appears on its own) keeps the integration itself current. When a release changes the panel↔HA connection contract, the integration's update stays out of sight until every panel is on it — update the panels as they offer, and the integration's update appears the moment the last one finishes. Panels first, integration last is the safe order, and it happens on its own. ([auto-update](auto-update.md) covers keeping your own UI current too.)
- **Instant update notices** (optional): the self-update entry's **Configure** dialog shows a webhook URL and secret. Add them as a webhook on this repo (Settings → Webhooks: content type `application/json`, release events only) and new releases appear in HA within seconds instead of on the hourly check. With Nabu Casa the URL works as-is; otherwise your HA must be reachable from the internet.
- **The interface** is yours to build and publish: [Build your own UI](build-your-own-ui.md).
- **On-panel tools** for a look under the hood live in the [CLI reference](cli.md).
