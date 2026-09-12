# Big Dish Console

A local, browser-displayed control UI for the Big Dish, in the spirit of the old
`w1xm/rci_interface` panel: a regional map with the dish azimuth drawn over it, a
VirtualSky star chart, manual pointing in az/el, ra/dec, or galactic coordinates, and a
target list (calibrator sources, sun/moon/planets, ground stations, satellites).

It talks to the dish control server from the `w1xm/BigDishControlServer` repository, which
also holds the protocol specification (`protocol.md`) and the server itself. A copy of this
app lives there too, under `web_client/bigdish-console`; it began life beside that
repository's earlier Vue client, `big-dish-web-client-vue`, and borrows its protocol
handling as a starting point.

The protocol client itself is not part of this app: it lives with its Python counterpart in
`../dish_client/bigdish_client.js`, and is imported here as `@client/bigdish_client.js`
(see the alias in `vite.config.js`).

Everything runs on the operator's machine and binds to 127.0.0.1 only. The only network
peers are the dish control server and (for satellite targets) a same-origin `/tle`
endpoint that fetches and caches TLEs from CelesTrak.

## Setup

Requires Node 18+ for building. There is a self-contained Node 20 under
`~/.local/opt/node-v20.19.0-linux-x64` (installed 2026-08; delete that directory to
remove it). Put it on PATH before npm commands:

```sh
export PATH=~/.local/opt/node-v20.19.0-linux-x64/bin:$PATH
npm install
```

Generate the map (needs internet once; re-run after changing the radius, projection, or
tile style in `public/config.json`):

```sh
python3 tools/generate_map.py
```

It downloads OSM tiles and resamples them into an azimuthal-equidistant chart centered on
the dish, so pixel radius is exactly ground range and pixel angle is exactly true bearing:
the console's range rings are honest and its azimuth needles are straight rays. Setting
`map.projection` to `webmercator` keeps the raw tiles instead, at the cost of curved
azimuth rays and a few miles of range error at the rim (at this latitude the 250 mi ring
lands anywhere from 247 to 253 mi out, depending on direction).

## Running

Development (auto-reload):

```sh
npm run dev
```

`serve.py` marks `index.html` as never cacheable and the hashed bundles beside it as cacheable
forever, which is the arrangement the build's content-hashed filenames exist for. Without it a
browser can hold an old `index.html` across a `git pull` and then ask for bundles that the
pull deleted, which looks like a broken install: a page of 404s, a flood of broken pipes in
the log, and the app quietly running whatever it had before.

Production-style (no Node needed at runtime):

```sh
npm run build
python3 serve.py            # http://127.0.0.1:8620/
```

`dist/` is committed, unusually for build output, so that the console can be served on a
machine that has no Node toolchain at all — `serve.py` uses nothing outside the Python
standard library, so a clone plus `python3 serve.py` is enough. It costs little in the
repository: all but four of the files in `dist/` are byte-identical copies of `public/`, which
git stores once. The catch is that it can go stale, so **rebuild and commit `dist/` whenever
you change anything under `src/`**, or the machine serving it will quietly run the old code.

## Configuration

`config.toml` holds the dish site location, default server host/port, map radius, projection
and tile style, dish beamwidth (for the beam wedge on the map), strobe cadences, and the
target list. It is TOML so that it can carry comments explaining each of those, and it is
commented; the browser is handed JSON, converted by whichever server is running.

It sits beside `serve.py` rather than in `public/`, so the build does not copy it and there is
only ever one of it: editing it takes effect on a browser reload, with nothing rebuilt and
nothing restarted. `python3 serve.py --config other.toml` serves a different one — useful for
a second site or a cut-down target list — and `BIGDISH_CONSOLE_CONFIG=other.toml npm run dev`
does the same in development. A `.json` file is still read as JSON, if you would rather keep
one.

Reading TOML needs Python 3.11 or newer for `tomllib` — Debian 12 and Raspberry Pi OS
bookworm both ship it. On an older Python, `pip install tomli` is enough, and `serve.py` says
so if it comes to it.

Target types:

- `fixed` — ra/dec or galactic coordinates; tracked by the server itself.
- `station` — a ground station by lat/lon; becomes a map marker and an az/el goto at its
  great-circle bearing. The name is drawn beside its dot, or in one of a ring of positions
  around it when that spot is taken, so that two stations close together do not print over
  each other. Every station is named: where nothing is clear the least covered position is
  used, which in a crowd fans the names out instead of piling them on one side.
- `body` — a solar-system body by name (astronomy-engine); tracked by strobing
  `goto_posvel` az/el commands from a Web Worker, like
  `example_pointing_scripts/moon_tracker.py`.
- `satellite` — a NORAD catalog number; orbital elements from CelesTrak as OMM, propagated
  with satellite.js (SGP4), strobed the same way. OMM supersedes the two-line format, which
  cannot carry catalog numbers past five digits; a TLE is still accepted if that is what you
  have.

## Connecting and control

Connecting and taking control are two steps, and the second one lives in the header rather
than in the startup dialog. The dialog gets you as far as an authenticated, view-only
session; the session menu at the right of the header — `user@host:port` — is where control
is asked for, given back, and logged out of.

The order is forced by the protocol and is the better order anyway: the server will not tell
a connection who else is on until it has authenticated, so there is no way to know whether
taking control means taking it off somebody until you are already connected. Asking first
and deciding second means the kick is made with the other operator's name and how long since
they last moved the dish in front of you, rather than as a checkbox ticked before there was
anything to know. **Connect and take control** in the dialog runs both steps for the common
case where nobody else is on, and falls back to the same dialog if somebody is.

Everything the console does for its own sake — the map and star chart, the diagnostics
history, the position log, a queued pointing file's countdown — needs no more than an
authenticated connection, so stepping back to view only costs none of it. Logging out
deliberately does not put the dialog back up: an hour of diagnostics is still worth reading,
and the header offers the way back in.

Two things are worth knowing about how this works against the current server.

**Releasing control drops the connection for about a second.** The protocol has no message
for giving control back — a connection leaves the controlling state only by being kicked or
by going away — so releasing means closing the socket and immediately reconnecting as a
viewer, which the server reads as an ordinary disconnect. The console does this for you and
says what it is doing, but the second off the air is real: it shows up as a gap in the
position log, which counts and reports such gaps, and as a notch in the diagnostics traces.
It also means the password is held in memory for the session, to authenticate again. A
`release` message would make it a single round trip and remove both costs; see `todo.txt` in
the repository root.

**A kick is worked out rather than announced.** The server sends nothing when it takes
control away, and the user list it does offer is keyed by account rather than by connection,
so with one shared login per station — the ordinary arrangement — two windows are
indistinguishable in it by name. The console picks its own entry out of the list by
timestamp instead: the server stamps the sender's last-active time before building the reply,
so the newest entry in an answer is always the connection that asked for it. Reading the
state off that entry catches a kick by anyone, on any account, within one poll, and it is
what makes losing control during a *track* visible at all — a track is run by the server, so
a console that has quietly lost control sends nothing that could come back refused, and would
otherwise go on claiming control for as long as the track lasted.

This is an inference, not a label: two connections that sent a command in the same microsecond
would tie, and the loser would misread one poll before the next corrected it. `todo.txt`
describes the one-field server change that would make it a fact instead. Independently of it,
the answer to any refused command or control request is taken as the authority on which state
this console is really in, so a drifted header corrects itself the moment anything is asked.

While control is held, releasing or logging out while the dish is following something asks
first, and offers to stop the dish on the way out. Giving up control does not stop it
otherwise: the server runs the command it already has until that command ends, whether or not
anyone is left in control — which is the same thing that happens today when a browser tab is
closed, and is what makes handing a running observation to the next operator possible.

A queued or running pointing file does not survive it, though. The file is this console's to
deliver, row by row, and a console that has given up control cannot deliver it, so releasing
or logging out cancels it. Cancelling it that way deliberately does not hold the dish, unlike
the Cancel button in the utilities tab: whether the dish keeps moving is the question you were
just asked, and cancelling the file should not answer it for you.

## Themes

The button at the right of the header switches between the dark console and a light one; the
choice is remembered, and until one is made it follows the system preference.

The map's chart paper does not change: the cream disc and everything inked on it — needles,
beam wedge, range rings, station marks, the sky track — read the same by day or night, so the
chart itself is one drawing in two consoles. Everything around it follows the theme, including
the degree ring, whose background is simply left unpainted so the panel shows through. The
star chart flips too, using VirtualSky's `negative` palette for black-on-white.

## Finding targets

The Utilities tab looks up things the config does not list. A satellite by name, catalog
number or international designator from CelesTrak, or an astronomical source by name or
designation from SIMBAD; either can be added to the Targets dropdown, where it behaves like
anything else — sky path, offsets, tracking. Added targets belong to the session and are gone
on reload; to keep one, put it in `config.toml`.

An ephemeris can also be loaded from a file: OMM (json), a TLE, a CCSDS OEM, or the text
ephemeris SpaceX publish for each Starlink. The first two are elements and get propagated like
any satellite. The other two are tables of state vectors somebody else has already computed —
often a better prediction than SGP4 can give, since the operator knows their own manoeuvres —
so such a file becomes a target of its own kind, interpolated between the states with a cubic
that uses the velocities the file carries. A straight line between them would not do: at the
sixty second spacing these files use, a satellite in low orbit departs from the chord by about
four kilometres, which at a few hundred kilometres range is nearly half a degree. Files are
read in the browser; nothing is uploaded.

Sources are resolved by the same CDS name resolver `astropy`'s `SkyCoord.from_name` uses,
which is what makes "crab", "m87" and "sgr a*" work; the results below the first are other
objects whose identifiers also match. Searching happens when asked rather than as you type,
`serve.py` sends at most two requests per search, and it caches them for two minutes and never
sends two closer together than a second — CelesTrak and CDS answer out of goodwill.

It also runs a prepared pointing file — the csv `WR66_run_pointing_file.py` takes, and
`oem_to_bigdish_commands.py` writes. The whole file is checked when loaded, by the same rules
as the Python and reporting the offending line, because a row that is wrong in a way nobody
notices until the dish drives into a limit is the thing to avoid. What it found is shown before
anything is committed: rows, frames, when it starts and for how long, the step between rows,
and the lowest elevation it commands.

Rows are handed to the server as `track` commands carrying `executeat` rather than by waiting
for each moment and firing. The server holds each until its time and applies it to the second,
and since only the next few seconds are ever committed, cancelling means simply not sending
the rest. A queued file leaves the dish alone until it starts, so ordinary commands still work;
at its start time it stands down anything else running and **sets the pointing offset to zero**,
so the file runs from a known state, and can be nudged by hand afterwards. Losing the
connection while queued costs nothing unless it is still down when the file is due; losing it
mid-run stops the file. The state and a cancel button sit in the sidebar, visible from any tab.

The tab also logs the dish's position to a csv in the format `WR66_log_position.py` writes —
same columns, same precision, same line endings — so anything that reads one of those reads
this. It records the readings the status poll already collects rather than opening a second
stream of requests, which has one consequence worth knowing: an interval finer than the poll
period cannot be honoured, and one that is not a multiple of it is rounded to the nearest that
is. The panel says what it settled on. Stretches where readings stopped arriving are counted
and reported, since a gap in a log that looks continuous is worse than a short log.

## Sky tracks

Selecting a target draws its path across the sky — rise to set, or a full 24 hours for
something circumpolar — on both the map and the star chart. It works for anything that moves:
satellites, the sun, moon and planets, and fixed calibrator sources. Ground stations are
bolted to the earth and have no path, so they clear it.

On the **map** the path is drawn as a polar sky plot laid over the chart: azimuth is shared
with the map underneath, and radius is zenith angle, so the middle is overhead and the rim is
the horizon — which is conveniently also where the map's outer range ring already is. Dashed
guide circles mark elevation 30° and 60°, the path carries clock ticks and rise/set marks, and
the target's position now is a filled marker, with a caret on the degree ring at its azimuth
and a line at the top right reading its az/el and set time, or when it next rises and how high
it will get.

The dish's own needles are drawn in that same plot, so they can be compared with the track
directly. A needle carries azimuth as its direction and elevation as its length, reaching the
radius the sky plot puts that elevation at — full to the rim on the horizon, shrinking to
nothing overhead — which means the needle's **tip** is where the beam is pointing, not merely
its bearing. When the tip sits on the target's marker, the dish is on the target, in both
axes at once. The dashed elevation circles are therefore drawn whether or not a target is
focused, since they are the scale that gives a needle's length its meaning; near the zenith
the needle grows too short to carry an arrowhead, and the marker at the centre carries the
reading instead.

The green beam wedge opens from the dish out to the patch of sky the beam actually covers, so
what it widens to is a footprint rather than a fixed spread of azimuth carried to the rim.
`dish.beamwidth_deg` is a cone across the sky, and a cone is a circle on the sky; in this
projection that circle becomes an ellipse. Radius is zenith angle, so the mark keeps its true
angular size *radially* wherever it sits. Across the radius it does not: the same beam covers
`2ρ/cos(el)` of azimuth — 2ρ down at the horizon, the whole compass at the zenith — while the
arc it is drawn on shrinks to nothing over that same journey. What survives of the two is a
tangential stretch of `z/sin z`, exactly 1 overhead and π/2 at the horizon. So the mark is
round in the middle of the chart and is drawn out along the rim into an arc as the dish comes
down. Point near enough to the zenith and the centre of the chart falls inside the mark, at
which point the wedge is the mark.

The footprint is drawn over the wedge as well as at the end of it, which is why it reads as a
denser patch. The wedge's sides are tangents to the mark and touch it at its widest — about
its middle — so a wedge drawn alone absorbs the near half of the footprint, and what is left
looking like the beam is the far cap, half the width the beam really is. Drawn twice, the
whole of it can be measured against the elevation circles.

On the **star chart** the same samples are drawn in VirtualSky's projection, using its own
`azel2xy`, repainted with every redraw. Note that the two views mirror each other, and both
are right: the map looks down (north up, east right, compass convention) while the star chart
looks up (north up, east left, planetarium convention).

A ground track — the satellite's position over the earth — was tried first and dropped. It is
only meaningful for satellites, and even then rarely visible: the best ISS pass from Boston in
a day crosses the 250 mi disc for about 95 seconds, and the sub-solar and sub-lunar points can
never come within 1300 and 998 miles of the dish. The angular plot is the useful one.

`map.sky_track` in `config.json` sets `max_hours` (the cap for circumpolar sources and for how
far ahead to look for the next pass) and `max_points` (the sampling ceiling; the path is
otherwise sampled every half degree of travel, so a satellite pass gets seconds-apart samples
and the moon gets minutes-apart ones).

## Diagnostics

The Diagnostics tab plots the last hour of telemetry: position and pointing error on the
left, motor voltage and current on the right. It is fed from the status poll that already
runs, so it costs nothing extra to collect, and it starts when the console connects — there
is no server-side log to backfill from, and this is not the program to build one in.

The error is the difference between the position the server reports and where the dish should
have been *at the timestamp of that reading*, which the server provides. For a track that
means recomputing the target's az/el for each sample, since it moves; for a goto it is the
commanded position; and before anything has been commanded there is no error, so the plot is
empty rather than showing zero.

It is recorded only while this console holds control, and the commanded position with it —
on the position plot, and as the dashed needle and elevation mark on the map. What both are measured against is where *this* console last told the
dish to point, so with another operator driving — or nobody — they describe a command the dish
was never given, and the difference from it is not a pointing error but the distance between
two unrelated positions. Those stretches are recorded as nothing at all, and nothing is drawn
across them: the trace breaks where the readings stop and picks up where they resume, rather
than running a straight line over the interval to suggest a measurement that was never taken.

`diagnostics.error_limit_deg` in `config.toml` fixes the error axis, deliberately tight —
a converged track sits a few hundredths of a degree off, which an axis wide enough to hold a
slew would flatten to nothing. Samples beyond the bound are simply not drawn, so the trace
breaks and a slew reads as off the scale rather than as a bar along the edge of it — a value
clamped to the bound is a reading the dish never took, in the very place the eye goes to
judge whether the error is small. `dish.az_range` and
`dish.el_range` fix the position axis over the rotor's travel; voltage and current scale
themselves.

The plots also carry the commanded position, dotted, behind the measured one; on a healthy
track the two lie on top of each other, which is why they are told apart by line style rather
than by shade.

A reading is kept once a second (`diagnostics.sample_seconds`) and the plots redraw every five
(`redraw_seconds`). An hour across six hundred pixels is six seconds to the pixel, so storing
or drawing faster shows nothing more. Within that, each pixel column shows the range of the
samples falling in it rather than their average, so a brief excursion still appears as a
spike. The chart tabs also stop drawing entirely while hidden, the star chart's live clock
included.

## Pointing offsets

The Offset panel adds an angular nudge to every pointing command until it is cleared,
entered in whichever frame is convenient — handy for stepping across a source to find beam
center, or parking the beam a known distance off-source. It goes into the commanded
coordinates, not into the server's `set_offset`, which protocol.md reserves for
feed/boresight corrections that should persist across observations.

Four frames are available. In az/el, ra/dec and galactic it is plain coordinate arithmetic,
so 1° of Δaz is 1° of azimuth — less than 1° of beam travel away from the horizon; the panel
shows what the beam actually moves. The fourth frame, **along / across track**, is in true
on-sky angle measured against the direction the target is moving: Δ∥ leads or trails it
along its own path, Δ⊥ steps across that path, and both are exact rotations, so 0.5° is
0.5° of beam travel wherever the dish is looking. That is the frame for cutting across a
source to find beam center, or for parking ahead of a target so it drifts through the beam.
The axes are a right-handed triad in the order (beam direction radially outward, direction of
travel = +Δ∥, their cross product = +Δ⊥). Looking out at the target that puts +Δ⊥ 90°
clockwise from the direction of travel, so for something rising in the east — climbing up and
to the right — +Δ⊥ steps down and to the right, southward. A target that is not moving at
all, a geostationary satellite, has no track direction, so the frame falls back to increasing
azimuth.

The frame decides how a command can be carried out:

- **Sky target, sky offset** (ra/dec or galactic) — still a fixed point on the sky, so the
  server keeps tracking it natively. The command is sent in the offset's frame, converting
  the target if needed.
- **Sky target, az/el or track offset** — no longer fixed on the sky: the offset direction
  rotates as the source moves (a 1° az offset walks 0.07°/h at the Crab, 0.19°/h near the
  zenith), so the console computes az/el continuously and strobes it, as it does for the moon.
- **Az/el target, or a body or satellite, with any offset** — folded into the az/el solution,
  once for a goto and on every strobe tick for a track.

While the console is driving a track itself it knows where the source is as well as where
the beam is, so the panel reports the actual offset in az/el rather than an estimate.

Applying or clearing an offset re-points whatever is tracking, so the beam moves
immediately; otherwise it lands on the next command. Stow and service ignore it.

**Stop tracking** in the header takes down whatever is following a target — the console's
strobe or the server's own track — and holds the current position. The protocol has no
cancel message, so this is a goto at the present az/el, which preempts the running command
(protocol.md line 9) and stops the dish where it is.

## Vendored pieces

- `public/vendor/virtualsky/` — VirtualSky + its data files (LCO / Stuart Lowe, MIT),
  so the star chart works offline.
- `public/vendor/fonts/` — IBM Plex Mono and Barlow Condensed (OFL).
