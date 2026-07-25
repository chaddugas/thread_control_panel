# Panel command-line tools

Every panel installs a small set of `panel-*` commands on its Raspberry Pi, on the `PATH` of any SSH session. They cover logs, version readouts, and re-running an install. None of them are needed in normal use — software updates arrive automatically through Home Assistant — but they make a panel easy to inspect and recover.

## Logs — `panel-logs`

A unified view over everything the panel logs — the bridge, the Thread firmware, the kiosk UI, software updates, and WiFi/networking — filtered by *scope*, *level*, and *time*, without memorizing `journalctl` flags.

```
panel-logs                                 # recent activity, info and up
panel-logs --scope wifi net                # WiFi state + raw network events
panel-logs --scope ota --level debug       # full detail of a software update
panel-logs --since last-boot               # everything since this boot
panel-logs --follow                        # live tail
panel-logs --json                          # one JSON object per line
```

Run `panel-logs --help` for the full list of scopes and more examples. A few worth knowing:

- `--scope` takes one or more names (combined with OR). Common ones: `bridge`, `uplink` (firmware), `ui`, `ota`, `wifi`, `net`, `ws`, `thread`.
- `--level debug` is the deep view of a **software update** — it surfaces every step's command output. Day-to-day logging stops at `info`.
- `--since` accepts ordinary expressions (`"3 hours ago"`, `"2026-06-18 12:00"`) plus shortcuts: `last-update`, `last-ota-fail`, `last-boot`.
- Times shown as `~HH:MM:SS` are back-computed: the panel's clock hadn't synced yet when those lines were written (it learns the time from Home Assistant), so `panel-logs` derives their true wall time from the journal's internal clocks.

## Versions

Three readouts of what's installed, each from a different source:

```
panel-version       # the panel version Home Assistant shows, e.g. 4.2.3
panel-helm-version  # the panel-computer side's build tag
panel-uplink-version  # the Thread chip's firmware tag (read from the chip itself)
```

`panel-version` and `panel-helm-version` read the installed release; `panel-uplink-version` reads the chip directly, which is the honest answer if a firmware flash was interrupted.

## Re-running an install — `panel-install`

Re-fetch and run a release's installer on an already-set-up panel — the same thing the first-time `curl … | bash` install does — without pasting the install command again.

```
panel-install                 # latest for this panel's update channel
panel-install v2026.06.01     # a specific version
panel-install --factory       # wipe pairing + UI and start completely fresh
```

Most panels never need this; reach for it to recover a panel, force a specific version, or apply a setting that only the full installer writes (some network and system tweaks land at install time, not over an update).
