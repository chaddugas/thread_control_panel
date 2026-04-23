idf_component_register(
    SRCS
        "app_main.c"
        "panel_app.c"
    INCLUDE_DIRS "."
    PRIV_REQUIRES
        panel_platform
        mqtt
)
