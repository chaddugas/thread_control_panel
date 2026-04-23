# platform/diagnostics/

Pi-side smoke-test scripts. Not meant for production — these are throwaway tools for verifying hardware and links.

| File | Tests |
|---|---|
| `panel_test.py` | UART link to the C6 (reader thread + stdin sender) |
| `touch_test.py` | Waveshare display + touch via direct framebuffer + evdev |

Both have served their purpose; left in tree as references for the equivalent production code in `platform/bridge/` and `platform/ui-core/`.
