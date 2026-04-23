# platform/firmware/

ESP-IDF component containing every panel's shared C6 firmware:

- **`panel_platform`** — NVS / event loop / netif / OpenThread bring-up; OMR-gated MQTT lifecycle (`panel_net`); UART bridge to the Pi (`panel_uart`); embedded ISRG Root X1 cert.

Per-product firmware lives in `panels/<id>/firmware/main/` and depends on this component via `PRIV_REQUIRES panel_platform`. Each panel project's top-level `CMakeLists.txt` adds this directory to `EXTRA_COMPONENT_DIRS`.

Per-product `panel_app.c` implements the `panel_app_*` callbacks declared in `panel_platform/include/panel_app.h`.
