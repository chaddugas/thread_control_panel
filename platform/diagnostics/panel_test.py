#!/usr/bin/env python3
"""
Panel UART smoke test — runs on the Pi, talks to the C6 over /dev/serial0.

Reader thread prints every line received from the C6.
Main thread reads stdin and forwards each line (newline-terminated) to the C6.

Quick proofs:
  - HA publish on panel/test/echo "hello loopback"
      → here:  [HH:MM:SS.mmm] [RX] hello loopback
  - Type {"hello":"pi"} <Enter> here
      → mosquitto_sub on panel/test/from_pi sees {"hello":"pi"}

Stop with Ctrl+C or Ctrl+D.
"""

import sys
import threading
from datetime import datetime

import serial

PORT = "/dev/serial0"
BAUD = 115200


def reader(port: serial.Serial) -> None:
    while True:
        try:
            line = port.readline()
        except serial.SerialException as exc:
            print(f"[ERR] serial read: {exc}", file=sys.stderr)
            return
        if not line:
            continue
        text = line.decode("utf-8", errors="replace").rstrip("\r\n")
        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        print(f"[{ts}] [RX] {text}")


def main() -> int:
    try:
        port = serial.Serial(PORT, BAUD, timeout=0.1)
    except serial.SerialException as exc:
        print(f"Failed to open {PORT}: {exc}", file=sys.stderr)
        return 1

    print(f"Opened {PORT} @ {BAUD}. Type a line + Enter to send. Ctrl+C to quit.")

    threading.Thread(target=reader, args=(port,), daemon=True).start()

    try:
        for line in sys.stdin:
            payload = line.rstrip("\r\n") + "\n"
            port.write(payload.encode("utf-8"))
            port.flush()
    except KeyboardInterrupt:
        pass
    finally:
        port.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
