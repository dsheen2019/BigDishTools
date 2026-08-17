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

`public/config.json` holds the dish site location, default server host/port, map radius,
projection and tile style, dish beamwidth (for the beam wedge on the map), strobe cadences,
and the target list. Target types:

- `fixed` — ra/dec or galactic coordinates; tracked by the server itself.
- `station` — a ground station by lat/lon; becomes a map marker and an az/el goto at its
  great-circle bearing.
- `body` — a solar-system body by name (astronomy-engine); tracked by strobing
  `goto_posvel` az/el commands from a Web Worker, like
  `example_pointing_scripts/moon_tracker.py`.
- `satellite` — a NORAD catalog number; TLE from CelesTrak, propagated with satellite.js
  (SGP4), strobed the same way.

## Themes

The button at the right of the header switches between the dark console and a light one; the
choice is remembered, and until one is made it follows the system preference.

The map's chart paper does not change: the cream disc and everything inked on it — needles,
beam wedge, range rings, station marks, the sky track — read the same by day or night, so the
chart itself is one drawing in two consoles. Everything around it follows the theme, including
the degree ring, whose background is simply left unpainted so the panel shows through. The
star chart flips too, using VirtualSky's `negative` palette for black-on-white.

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
it will get. Because azimuth is shared, the dish's own needle lines up with the track
directly: when the needle points at the marker, the beam is on the target.

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
