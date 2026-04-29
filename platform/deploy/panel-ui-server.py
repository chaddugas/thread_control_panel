#!/usr/bin/env python3
"""Static file server for the kiosk's `dist/` bundle.

Same role as `python3 -m http.server` but with cache headers tuned for our
deploy model:

  - `index.html` (and any other .html) → `Cache-Control: no-cache`. Forces
    the browser to revalidate every load. Essential because Vite's bundle
    references hash-named assets via index.html — if the browser caches
    index.html, it keeps loading the old asset references regardless of
    what's on disk, and `cut-release` deploys appear to do nothing on the
    kiosk until you manually clear `~/.cache/wpe-webkit/`.

  - everything else (the hash-named JS/CSS/font files Vite generates)
    → `Cache-Control: public, max-age=31536000, immutable`. These files
    are content-addressed; their filename changes when their content
    changes. Long, immutable caching is correct and saves WPE from
    re-downloading the bundle on every kiosk reload.

Usage:
    panel-ui-server.py [PORT [BIND]]

Defaults to port 8080 on 127.0.0.1, matching what panel-ui.service expects.
"""

from __future__ import annotations

import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer


class KioskHandler(SimpleHTTPRequestHandler):
    def end_headers(self) -> None:
        path = self.path.split("?", 1)[0]
        if path == "/" or path.endswith(".html"):
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
        else:
            self.send_header(
                "Cache-Control", "public, max-age=31536000, immutable"
            )
        super().end_headers()


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    bind = sys.argv[2] if len(sys.argv) > 2 else "127.0.0.1"
    server = ThreadingHTTPServer((bind, port), KioskHandler)
    print(f"panel-ui static server listening on http://{bind}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
