#!/usr/bin/env python3
'''
Local-only server for the built console.

Serves the vite build output (dist/) on 127.0.0.1 and provides the same /omm endpoint the
vite dev server proxies: it fetches orbital elements from CelesTrak by catalog number and
caches them on disk, so repeated sessions are polite to CelesTrak and satellite tracking still
works briefly offline.

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
import urllib.error
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
ELEMENTS_MAX_AGE_S = 6 * 3600
# OMM, which is what CelesTrak serves now and what supersedes the two-line format. The JSON
# form is what satellite.js reads directly.
CELESTRAK_URL = "https://celestrak.org/NORAD/elements/gp.php?CATNR={catnr}&FORMAT=JSON"
CELESTRAK_SEARCH_URL = "https://celestrak.org/NORAD/elements/gp.php?{field}={value}&FORMAT=JSON"
SIMBAD_URL = "https://simbad.cds.unistra.fr/simbad/sim-tap/sync"
# The name resolver astropy's SkyCoord.from_name uses. It is forgiving about spacing and case
# in a way that querying the tables directly is not -- "crab", "m87", "sgr a*" all resolve --
# so it answers what the operator meant, and the table query below only supplies alternatives.
SESAME_URL = "https://cds.unistra.fr/cgi-bin/nph-sesame/-oI/SNV"

# Searches are answered from a short lived cache, and no two upstream searches are sent closer
# together than this. Somebody leaning on the return key should not be able to make a nuisance
# of us to CelesTrak or CDS, and both are answering out of the goodness of their hearts.
SEARCH_CACHE_S = 120
SEARCH_MIN_INTERVAL_S = 1.0
SEARCH_LIMIT = 50
_search_cache = {}
_last_upstream_search = [0.0]


def wildcard_between_letters_and_digits(text):
    """
    M87 -> M%87%, NGC4486 -> NGC%4486%

    SIMBAD stores identifiers with padded spacing -- "M  87", "NGC  4486" -- so a prefix match
    on what somebody types finds nothing. A wildcard wherever letters meet digits covers any
    amount of padding. It matches more than it should, "M  187" among them, which is what the
    list of candidates is for.
    """
    return re.sub(r"(?<=[A-Za-z])(?=\d)|(?<=\d)(?=[A-Za-z])", "%", text) + "%"


def simbad_query(text):
    """
    One ADQL query for alternatives to what the resolver found.

    Every clause here has to be anchored at the start of an identifier. A pattern beginning
    with a wildcard, a case insensitive regexp, or an OR of two differently shaped clauses each
    turns this into a scan of the whole identifier table, which does not come back: measured at
    over three minutes before being abandoned, against well under a second for the anchored
    forms. So the query takes one shape or the other, chosen by what was typed, and never both.

    A catalogue designation is matched by regexp, which absorbs the padding SIMBAD stores --
    "M  87" for M87. Anything else is matched as a common name, which SIMBAD files under a
    "NAME " prefix: "crab" matches nothing, "NAME Crab" is the entry.
    """
    escaped = text.replace("'", "''")
    columns = "b.main_id, b.ra, b.dec, b.otype_txt"
    table = "FROM ident AS i JOIN basic AS b ON i.oidref = b.oid"

    if re.search(r"[A-Za-z]\s*\d|\d\s*[A-Za-z]", text):
        pattern = re.sub(r"\s+", " *", escaped.upper())
        pattern = re.sub(r"(?<=[A-Z])(?=\d)|(?<=\d)(?=[A-Z])", " *", pattern)
        where = f"regexp(i.id, '^{pattern}') = 1"
    else:
        where = f"i.id LIKE 'NAME {escaped.title()}%'"

    return f"SELECT DISTINCT TOP {SEARCH_LIMIT} {columns} {table} WHERE {where}"


def parse_sesame(text):
    """The resolver's reply: %C.0 object type, %J degrees, %I.0 main identifier."""
    if "Nothing found" in text:
        return None
    found = {}
    for line in text.splitlines():
        if line.startswith("%J "):
            parts = line.split()
            found["ra"], found["dec"] = float(parts[1]), float(parts[2])
        elif line.startswith("%C.0"):
            found["otype"] = line[4:].strip()
        elif line.startswith("%I.0"):
            found["id"] = " ".join(line[4:].split())
    return found if "ra" in found else None


class ConsoleHandler(http.server.SimpleHTTPRequestHandler):
    config_path = DEFAULT_CONFIG

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(DIST_DIR), **kwargs)

    def end_headers(self):
        """
        Tell the browser what it may keep.

        The build gives every bundle a name containing a hash of its contents, so those can be
        cached forever: a change produces a different name. index.html names them, and must
        never be cached, or a browser holding an old copy asks for bundles that the last pull
        deleted -- which looks like a broken install and a flood of 404s, and leaves the app
        running whatever it had before.
        """
        path = urllib.parse.urlparse(self.path).path
        if path.startswith("/assets/"):
            self.send_header("Cache-Control", "public, max-age=31536000, immutable")
        else:
            # everything else revalidates: cheap, since unchanged files answer 304
            self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def handle_one_request(self):
        """
        A browser hanging up mid-response is ordinary -- switching tabs, reloading, following
        a link -- and is not worth a stack trace each time. Report it in one line.
        """
        try:
            super().handle_one_request()
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True
            self.log_message("client closed the connection")

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/tle":
            # the old name, kept working: an installed console that has not been rebuilt is
            # still asking for it
            self.serve_omm(urllib.parse.parse_qs(parsed.query))
        elif parsed.path == "/search":
            self.serve_search(urllib.parse.parse_qs(parsed.query))
        elif parsed.path == "/omm":
            self.serve_omm(urllib.parse.parse_qs(parsed.query))
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
        self.end_headers()
        self.wfile.write(body)

    def send_json_error(self, code, message):
        """
        An error the page can show as it stands.

        send_error answers with an HTML document, which is right for somebody who typed the
        URL and useless to a fetch: it would end up in the search box verbatim, doctype and
        all.
        """
        body = json.dumps({"error": message}).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def fetch_search(self, url, cache_key):
        """Fetch a search, from the cache when it is fresh, and never faster than the limit."""
        cached = _search_cache.get(cache_key)
        if cached and time.time() - cached[0] < SEARCH_CACHE_S:
            return cached[1]

        wait = SEARCH_MIN_INTERVAL_S - (time.time() - _last_upstream_search[0])
        if wait > 0:
            time.sleep(wait)
        _last_upstream_search[0] = time.time()

        request = urllib.request.Request(url, headers={"User-Agent": "BigDishConsole/0.1"})
        with urllib.request.urlopen(request, timeout=25) as response:
            body = response.read().decode("utf-8", errors="replace")
        _search_cache[cache_key] = (time.time(), body)
        return body

    def serve_search(self, query):
        """Search CelesTrak by name or international designator, or SIMBAD by identifier."""
        catalogue = (query.get("catalogue") or [""])[0]
        text = (query.get("q") or [""])[0].strip()
        if not 2 <= len(text) <= 64:
            self.send_json_error(400, "Search text must be between 2 and 64 characters.")
            return

        if catalogue == "satellite":
            field = "INTDES" if re.fullmatch(r"\d{4}-\d{3}[A-Z]{0,3}", text.upper()) else "NAME"
            url = CELESTRAK_SEARCH_URL.format(
                field=field, value=urllib.parse.quote(text))
        elif catalogue == "simbad":
            self.serve_simbad_search(text)
            return
        else:
            self.send_json_error(400, "Catalogue must be satellite or simbad.")
            return

        try:
            body = self.fetch_search(url, f"{catalogue}:{text}")
        except urllib.error.HTTPError as e:
            # CelesTrak answers an unmatched name with 404, which is an empty result, not a
            # fault; SIMBAD reports a bad query as a VOTable document, handled by the client
            if e.code == 404:
                body = "[]"
            else:
                self.send_json_error(502, f"The {catalogue} catalogue returned HTTP {e.code}.")
                return
        except OSError:
            self.send_json_error(502, f"Could not reach the {catalogue} catalogue.")
            return

        encoded = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def serve_simbad_search(self, text):
        """
        What the operator meant, then anything else it could have been.

        Two requests at most: the resolver, which is the one that gets "crab" right, and one
        table query for alternatives. The alternatives are optional -- if that query fails or
        times out, the resolved object is still worth returning on its own.
        """
        matches = []
        try:
            resolved = parse_sesame(self.fetch_search(
                SESAME_URL + "?" + urllib.parse.quote(text), f"sesame:{text}"))
            if resolved:
                resolved["source"] = "resolved"
                matches.append(resolved)
        except OSError:
            self.send_json_error(502, "Could not reach the name resolver.")
            return

        try:
            body = self.fetch_search(
                SIMBAD_URL + "?" + urllib.parse.urlencode({
                    "request": "doQuery", "lang": "adql", "format": "json",
                    "query": simbad_query(text)}),
                f"simbad:{text}")
            # SIMBAD reports a rejected or slow query as VOTable or HTML, whatever was asked
            # for, so the reply is checked rather than relayed
            table = json.loads(body)
            for row in table.get("data", []):
                identifier = " ".join(str(row[0]).split())
                if any(m.get("id") == identifier for m in matches):
                    continue
                matches.append({"id": identifier, "ra": row[1], "dec": row[2],
                                "otype": row[3], "source": "catalogue"})
        except (OSError, ValueError, KeyError, IndexError):
            pass  # alternatives are a bonus; what the resolver found still stands

        encoded = json.dumps(matches).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def serve_omm(self, query):
        """
        Orbital elements for one satellite, as OMM JSON.

        Proxied rather than fetched by the page because CelesTrak sends no CORS header, and
        cached on disk so that repeated sessions are polite to them and a satellite stays
        trackable through a short outage.
        """
        catnr = (query.get("catnr") or [""])[0]
        if not re.fullmatch(r"\d{1,9}", catnr):
            self.send_error(400, "catnr must be a NORAD catalog number")
            return

        CACHE_DIR.mkdir(exist_ok=True)
        cache_file = CACHE_DIR / f"{catnr}.omm.json"
        elements = None
        fresh = cache_file.exists() and time.time() - cache_file.stat().st_mtime < ELEMENTS_MAX_AGE_S
        if fresh:
            elements = cache_file.read_text()
        else:
            try:
                request = urllib.request.Request(
                    CELESTRAK_URL.format(catnr=catnr),
                    headers={"User-Agent": "BigDishConsole/0.1"})
                with urllib.request.urlopen(request, timeout=20) as response:
                    elements = response.read().decode("utf-8")
            except urllib.error.HTTPError as e:
                # 404 here means there is no such satellite, which is not a network problem
                # and should not be reported as one. HTTPError is an OSError, so this has to
                # come first or it would be swallowed by the branch below.
                if e.code == 404:
                    self.send_error(
                        404, f"CelesTrak has no orbital elements for catalog number {catnr}")
                    return
                if cache_file.exists():
                    elements = cache_file.read_text()
                else:
                    self.send_error(502, f"CelesTrak returned HTTP {e.code} and nothing is cached")
                    return
            except OSError:
                # unreachable: a stale cache beats nothing at all
                if cache_file.exists():
                    elements = cache_file.read_text()
                else:
                    self.send_error(502, "CelesTrak unreachable and no cached elements")
                    return
            else:
                # An unknown catalog number is answered with "No GP data found", as prose and
                # with a 200, so the reply has to be inspected rather than trusted. Say the
                # satellite is unknown, which is what it means, rather than blaming the network
                # as a fallthrough to the branch above would.
                try:
                    parsed = json.loads(elements)
                except json.JSONDecodeError:
                    parsed = None
                if not isinstance(parsed, list) or not parsed:
                    self.send_error(
                        404, f"CelesTrak has no orbital elements for catalog number {catnr}")
                    return
                cache_file.write_text(elements)

        body = elements.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
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
