#!/usr/bin/env python3
'''
Local-only server for the built console.

Serves the vite build output (dist/) on 127.0.0.1 and provides the same /tle endpoint the
vite dev server proxies: it fetches a TLE from CelesTrak by catalog number and caches it
on disk, so repeated sessions are polite to CelesTrak and satellite tracking still works
briefly offline.

The config is served from a file of its own rather than from the build output, so there is
one copy of it and it can be edited, or swapped for another with --config, without rebuilding
anything. It is TOML, so it can carry comments; the browser is still handed JSON, converted
here. A .json file is read as JSON, for anyone who prefers one.

Usage:
    npm run build          # once, after changing the app
    python3 serve.py [--port 8620] [--config config.toml]
'''

import argparse
import http.server
import json
import sys
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
DIST_DIR = APP_DIR / "dist"
DEFAULT_CONFIG = APP_DIR / "config.toml"

# tomllib is standard from Python 3.11. Debian 12 and Raspberry Pi OS bookworm ship 3.11, but
# 3.10 is still about, so fall back to tomli and say something useful if neither is there.
try:
    import tomllib
except ModuleNotFoundError:
    try:
        import tomli as tomllib
    except ModuleNotFoundError:
        tomllib = None


def read_config(path):
    """The configuration as a dict, from TOML or, if it is named .json, from JSON."""
    if path.suffix == ".json":
        return json.loads(path.read_bytes())
    if tomllib is None:
        raise SystemExit(
            f"Reading {path.name} needs TOML support: run this with python3.11 or newer, "
            "or `pip install tomli`, or point --config at a .json file.")
    return tomllib.loads(path.read_text(encoding="utf-8"))
CACHE_DIR = APP_DIR / ".tle_cache"
TLE_MAX_AGE_S = 6 * 3600
CELESTRAK_URL = "https://celestrak.org/NORAD/elements/gp.php?CATNR={catnr}&FORMAT=TLE"


class ConsoleHandler(http.server.SimpleHTTPRequestHandler):
    config_path = DEFAULT_CONFIG

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(DIST_DIR), **kwargs)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/tle":
            self.serve_tle(urllib.parse.parse_qs(parsed.query))
        elif parsed.path == "/config.json":
            self.serve_config()
        else:
            super().do_GET()

    def serve_config(self):
        """
        Serve the configuration from its own file, not from dist/.

        It lives outside public/ so that the build does not copy it, which used to leave two
        copies: the one that was edited and the one that was actually served. Read on every
        request, so editing stations or the server address takes effect on a browser reload
        with nothing rebuilt and nothing restarted.
        """
        try:
            # parsed here, and handed to the browser as JSON, so a mistake in the file is
            # reported against the file rather than surfacing as a broken page
            body = json.dumps(read_config(self.config_path)).encode()
        except FileNotFoundError:
            self.send_error(404, f"No configuration file at {self.config_path}")
            return
        except Exception as e:
            self.send_error(500, f"{self.config_path} could not be read: {e}")
            return

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def serve_tle(self, query):
        catnr = (query.get("catnr") or [""])[0]
        if not re.fullmatch(r"\d{1,9}", catnr):
            self.send_error(400, "catnr must be a NORAD catalog number")
            return

        CACHE_DIR.mkdir(exist_ok=True)
        cache_file = CACHE_DIR / f"{catnr}.tle"
        tle = None
        if cache_file.exists() and time.time() - cache_file.stat().st_mtime < TLE_MAX_AGE_S:
            tle = cache_file.read_text()
        else:
            try:
                request = urllib.request.Request(
                    CELESTRAK_URL.format(catnr=catnr),
                    headers={"User-Agent": "BigDishConsole/0.1"})
                with urllib.request.urlopen(request, timeout=20) as response:
                    tle = response.read().decode("utf-8")
                cache_file.write_text(tle)
            except OSError:
                # CelesTrak unreachable: fall back to a stale cache if there is one.
                if cache_file.exists():
                    tle = cache_file.read_text()
                else:
                    self.send_error(502, "CelesTrak unreachable and no cached TLE")
                    return

        body = tle.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8620)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG,
                        help="configuration file to serve (default: %(default)s)")
    args = parser.parse_args()

    if not (DIST_DIR / "index.html").exists():
        raise SystemExit("dist/ not found -- run `npm run build` first (see README.md).")
    if not args.config.is_file():
        raise SystemExit(f"No configuration file at {args.config.absolute()}.")
    try:
        read_config(args.config)  # fail now, not on the first page load
    except Exception as e:
        # an operator's typo in their own config file, so say what is wrong with it rather
        # than printing a stack trace of the parser
        raise SystemExit(f"{args.config.absolute()} could not be read: {e}")

    ConsoleHandler.config_path = args.config.resolve()
    server = http.server.ThreadingHTTPServer(("127.0.0.1", args.port), ConsoleHandler)
    print(f"Big Dish console at http://127.0.0.1:{args.port}/ (local machine only)")
    print(f"Configuration from {ConsoleHandler.config_path}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
