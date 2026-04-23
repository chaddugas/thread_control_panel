# platform/deploy/

Deployment artifacts shared across panels:

- `cage.service` — systemd unit that launches `cage -- chromium --kiosk http://localhost:5000`
- `bridge.service` — systemd unit that runs `platform/bridge/` on boot
- `install-pi.sh` — one-shot Pi bootstrap (apt installs, group memberships, service enables)

Per-panel UI bundles are built locally and rsync'd to the Pi separately.
