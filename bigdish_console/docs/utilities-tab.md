# Plan: the utilities tab

A fourth tab beside Map, Sky and Diagnostics, holding four things that do not belong in the
pointing panels: running a prepared command file, saving a position log, and pulling targets
in from CelesTrak, SIMBAD or a file.

Written before starting, so the decisions and the things checked are on record. Delete it once
the work is done and the README covers what was built.

## What was checked first, rather than assumed

- **Pointing file** (`dish_client/WR66_run_pointing_file.py`): CSV rows of
  `UTC ISO time, frame (azel|gal|radec), coord1, coord2, [vel1, vel2]`, ascending in time.
  Validation rejects el < −3°, coord1 outside 0–360, |coord2| > 90, and implausible rates.
  Execution sends `track` with `executeat` set to the row's time and a duration reaching the
  next row, sleeping until each is due.
- **Log file** (`dish_client/WR66_log_position.py`): header
  `UTC, az, el, az vel, el vel[, az volts, el volts, az amps, el amps]`, timestamps taken from
  the server's own `time` field, written as ISO UTC.
- **CelesTrak** serves OMM as JSON: `gp.php?CATNR=25544&FORMAT=JSON`, and searches by partial
  name with `NAME=`. It sends **no CORS header**, so it has to be proxied, as the TLE endpoint
  already is. `NAME=STARLINK-31` returned **1002 matches**, so results must be capped and the
  count reported.
- **SIMBAD** answers ADQL over TAP with `format=json`, and **does** send
  `Access-Control-Allow-Origin: *`. It could be called from the browser directly; proxying it
  anyway keeps every outside request in one place and the app same-origin.
- **satellite.js already exports `json2satrec`**, so OMM costs no new dependency.
- **`simple_tracking_scripts/oem_to_bigdish_commands.py`** already parses CCSDS OEM
  (EME2000, UTC, km), interpolates the states with a cubic spline, converts to az/el through
  astropy, and writes the pointing-file CSV above.

## 0. OMM instead of TLE

Do first: everything in part 3 depends on it, and TLEs are formally obsolete.

- `/tle` becomes `/omm`, fetching `FORMAT=JSON` and caching the JSON body.
- `targets.js` and `ephemeris.js` swap `twoline2satrec` for `json2satrec`; `spec.tle` becomes
  `spec.omm`; the cache key changes with it.
- Keep reading an existing cached TLE if one is found, so nobody's cache breaks on upgrade.

Mechanical, and the only part that touches code already in use.

## 1. Run a pointing file

- `src/lib/pointing_file.js` — parse and validate with the same rules as the Python, reporting
  the offending row number. A bad file is refused when loaded, not part way through.
- `src/lib/schedule.js` — a runner with states `idle | queued | running | cancelled`, handing
  each row to the server as `track(..., executeat)` shortly before it is due, exactly as the
  Python does. Using `executeat` rather than sleeping is what makes cancellation possible: only
  a row or two is ever committed to the server.
- Selection is a plain `<input type="file">`; the browser reads it locally and nothing is
  uploaded.

Integration is the awkward part, and most of the work:

- While **queued**, ordinary commands keep working, and the status panel says what is queued
  and when it starts.
- At the start time the schedule **preempts** whatever is running, including a strobe, and
  takes ownership of the offset (an offset should apply to file rows too, or explicitly not —
  decide before building).
- **Cancelling** mid-run stops the dish where it is, the way Stop tracking does.
- The diagnostics error trace should follow the file: `expectedAzElAt` needs to return the
  current row's position while the schedule runs.

## 2. Save a position log

Settled: log from the readings the console already polls, so nothing new is asked of the
server. The requested interval is rounded to the nearest multiple of the status poll period —
at 5 Hz, a requested 1 s becomes 1.0 s, a requested 0.3 s becomes 0.2 s — and the panel shows
what it actually settled on.

- A logger separate from the diagnostics history: that one is deliberately coarse (1 Hz) and
  an hour deep, which is wrong for this. This one accumulates from the poll at the chosen
  interval, unbounded, until saved. At 5 Hz an eight hour run is about 144000 rows, a few tens
  of megabytes in memory, which is acceptable.
- Save produces the exact `WR66_log_position.py` header and column formats, as a download.
- Show rows collected and the span so far, and warn if the connection drops mid-log, since a
  gap in a log that looks continuous is worse than a short log.

Streaming to disk through `serve.py` would lift the memory ceiling and put the file on the
machine at the radome rather than in a browser's downloads. Not now; note it here so the
reason it was skipped is on record.

## 3. Add a target: search or upload

One picker component and one temporary-target mechanism serve all of the following. Temporary
targets live in `store.extraTargets`, are concatenated by `buildTargets`, and are marked in the
dropdown as belonging to this session — they do not survive a reload, deliberately.

**From CelesTrak**, by name, catalog number or international designator, through the `/omm`
proxy. Show name, catalog number and epoch; cap the list and say how many matched.

**From SIMBAD**, by name or catalogue identifier, through a `/simbad` proxy running an ADQL
query joining `ident` to `basic`. Show main identifier, object type, ra/dec and magnitude where
there is one. Several matches is the normal case, hence the shared picker. Selected objects
become temporary `fixed` radec targets.

**From a file**, which is what makes this cover the ephemerides the other scripts here handle:

- **OMM** (JSON, XML or KVN) and **TLE/3LE** — straight into `json2satrec` or
  `twoline2satrec`, the same path as a satellite pulled from CelesTrak.
- **CCSDS OEM** — parse the state vectors, interpolate as `oem_to_bigdish_commands.py` does,
  and rotate GCRS to horizontal with astronomy-engine, which already does that rotation for
  every fixed target. This makes an uploaded OEM a *target* rather than a command file: it
  appears in the dropdown, gets a sky path on both charts, works with offsets, and is driven by
  the existing strobe worker. The alternative — converting it to a pointing file and running it
  through part 1 — is worse, since the result cannot be re-pointed or offset once written.
  Note EME2000 and GCRS differ by a frame bias of about 20 mas, which is nothing against a
  2.7° beam.
- The strobe worker takes the spec by `postMessage`, so an OEM spec must be plain arrays.

## Order of work

0. OMM migration — prerequisite, mechanical.
1. Searches, both of them — they share the picker, the proxy pattern and the temporary-target
   mechanism, so building them together is much less than twice one.
2. File upload for ephemerides — reuses everything from 1, adds the OEM reader.
3. Log saving — self-contained.
4. Pointing file queue — largest, and touches the most existing code, so last.

## Still to decide

- Does a pointing offset apply to rows from a command file, or is the file taken as absolute?
- What should happen to a queued file if the connection drops before it starts?
- Should a temporary target be re-fetchable — that is, does the console remember it came from
  CelesTrak and refresh the elements on a long track?
