#!/usr/bin/env python3
"""
Waveshare 6.25" touch test — direct framebuffer + evdev.
Writes RGB565 to /dev/fb0. Ctrl+C to exit.
"""
import os
import sys
import threading
import queue
import struct
import fcntl
import time
import evdev
from evdev import ecodes
from PIL import Image, ImageDraw, ImageFont

# --- Hide the console cursor so it doesn't blink through our framebuffer ---
CURSOR_BLINK_PATH = "/sys/class/graphics/fbcon/cursor_blink"
original_cursor_state = None
try:
    with open(CURSOR_BLINK_PATH, "r") as f:
        original_cursor_state = f.read().strip()
    with open(CURSOR_BLINK_PATH, "w") as f:
        f.write("0")
except (OSError, PermissionError) as e:
    print(f"Warning: could not disable cursor blink ({e})", flush=True)


def restore_cursor():
    if original_cursor_state is not None:
        try:
            with open(CURSOR_BLINK_PATH, "w") as f:
                f.write(original_cursor_state)
        except OSError:
            pass


# --- Find the Waveshare touch device ---
touch_dev = None
for path in evdev.list_devices():
    d = evdev.InputDevice(path)
    if "waveshare" in d.name.lower():
        touch_dev = d
        break

if not touch_dev:
    print("Waveshare touchscreen not found")
    restore_cursor()
    sys.exit(1)

print(f"Using {touch_dev.path} ({touch_dev.name})", flush=True)

abs_info = {code: info for code, info in touch_dev.capabilities()[ecodes.EV_ABS]}
X_MAX = abs_info[ecodes.ABS_MT_POSITION_X].max
Y_MAX = abs_info[ecodes.ABS_MT_POSITION_Y].max

# --- Query framebuffer geometry ---
FBIOGET_VSCREENINFO = 0x4600
with open("/dev/fb0", "rb") as fb:
    buf = bytearray(160)
    fcntl.ioctl(fb, FBIOGET_VSCREENINFO, buf)
    WIDTH, HEIGHT, _, _, _, _, BPP = struct.unpack("IIIIIII", bytes(buf[:28]))

print(f"Framebuffer: {WIDTH}x{HEIGHT}, {BPP}bpp", flush=True)

# --- Touch queue and reader thread ---
touch_queue = queue.Queue()


def read_touches():
    current_x, current_y = 0, 0
    for event in touch_dev.read_loop():
        if event.type == ecodes.EV_ABS:
            if event.code == ecodes.ABS_MT_POSITION_X:
                current_x = event.value
            elif event.code == ecodes.ABS_MT_POSITION_Y:
                current_y = event.value
        elif (
            event.type == ecodes.EV_KEY
            and event.code == ecodes.BTN_TOUCH
            and event.value == 1
        ):
            px = int(current_x / X_MAX * WIDTH)
            py = int(current_y / Y_MAX * HEIGHT)
            touch_queue.put((px, py))


threading.Thread(target=read_touches, daemon=True).start()

# --- State ---
colors = [
    (255, 80, 80),
    (80, 255, 80),
    (80, 160, 255),
    (255, 220, 80),
    (220, 80, 255),
    (80, 255, 220),
]
color_index = 0
touches = []

try:
    font = ImageFont.truetype(
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 40
    )
    small_font = ImageFont.truetype(
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 22
    )
except OSError:
    font = ImageFont.load_default()
    small_font = ImageFont.load_default()

# --- Framebuffer ---
fb = open("/dev/fb0", "wb")
CX, CY = WIDTH // 2, HEIGHT // 2


def render_and_flush():
    img = Image.new("RGB", (WIDTH, HEIGHT), (20, 20, 30))
    d = ImageDraw.Draw(img)

    d.line([(CX, 0), (CX, HEIGHT)], fill=(60, 60, 80), width=1)
    d.line([(0, CY), (WIDTH, CY)], fill=(60, 60, 80), width=1)

    for x, y, c in touches:
        d.ellipse([x - 40, y - 40, x + 40, y + 40], outline=c, width=4)
        d.ellipse([x - 4, y - 4, x + 4, y + 4], fill=c)
        d.text((x + 50, y - 14), f"({x},{y})", fill=c, font=small_font)

    d.text((20, 20), "Touch Test", fill=(200, 200, 220), font=font)
    d.text((20, 70), f"{WIDTH}x{HEIGHT}", fill=(140, 140, 160), font=small_font)
    d.text((20, 100), f"Taps: {color_index}", fill=(180, 180, 200), font=small_font)
    d.text(
        (20, HEIGHT - 30),
        "Ctrl+C in SSH to exit",
        fill=(120, 120, 140),
        font=small_font,
    )

    fb.seek(0)
    fb.write(img.convert("BGR;16").tobytes())
    fb.flush()


def clear_screen():
    """Fill framebuffer with black so we don't leave garbage on exit."""
    black = Image.new("RGB", (WIDTH, HEIGHT), (0, 0, 0))
    fb.seek(0)
    fb.write(black.convert("BGR;16").tobytes())
    fb.flush()


# --- Main loop ---
try:
    while True:
        while not touch_queue.empty():
            x, y = touch_queue.get_nowait()
            color = colors[color_index % len(colors)]
            touches.append((x, y, color))
            if len(touches) > 10:
                touches.pop(0)
            color_index += 1

        render_and_flush()
        time.sleep(1 / 30)
except KeyboardInterrupt:
    pass
finally:
    clear_screen()
    fb.close()
    restore_cursor()
    print("\nExiting.")
