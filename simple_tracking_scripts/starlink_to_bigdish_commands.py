#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
starlink_to_bigdish_commands.py

Convert a Starlink text ephemeris -- the per-satellite files SpaceX publish at
api.starlink.com/public-files/ephemerides/ -- to a vector tracking command file
for the W1XM bigdish antenna at MIT.

Output format (one line per command epoch), identical to the OEM and TLE
scripts beside this one:

    UTC_ISO, azel, azimuth_deg, elevation_deg, az_rate_deg/s, el_rate_deg/s

The time tag on each line is the moment the antenna should *already be* at that
position and rate, and each rate is the average over the step to the next line.

The file itself:

    created:2026-08-22 17:57:20 UTC
    ephemeris_start:2026-08-22 17:39:42 UTC ephemeris_stop:... step_size:60
    ephemeris_source:blend
    UVW
    2026234173942.000 -6193.9604965151 2772.1851604203 ... -2.9921356700 ...
    <three lines carrying the twenty-one terms of the covariance>
    <next state vector>

so it is a CCSDS OEM in a different wrapper: four header lines, then records of
a state vector and a covariance that is of no use for pointing. Epochs are
YYYYDDDHHMMSS.sss in UTC, counting the day of the year; positions are km and
velocities km/s. The "UVW" line names the frame of the covariance, not of the
states.

The states are J2000 (the "MEME" in the filename), and are handed to astropy as
GCRS, which differs by a frame bias of about 20 mas. That the frame is J2000
rather than mean equator and equinox *of date* was checked rather than assumed,
since of-date would be a quarter of a degree away: fitting the node of a 72 hour
file back to the epoch of the same satellite's CelesTrak elements reproduces
them to 0.0002 deg when the states are rotated from J2000 to the equator of
date, and misses by half a degree when they are read as of-date already.

Because these are low orbits, the file is usually 72 hours of prediction holding
a handful of usable passes. --list-passes says when they are, and --pass N
tracks one of them without transcribing times by hand; -s/-e work as they do in
the OEM script if you would rather say the window yourself.

Usage:
    python starlink_to_bigdish_commands.py <ephemeris_file> --list-passes
    python starlink_to_bigdish_commands.py <ephemeris_file> --pass 3 [-i 1.0]
    python starlink_to_bigdish_commands.py <ephemeris_file>
        -s 2026-08-22T21:05:00
        -e 2026-08-22T21:15:00
        [-i 1.0]
        [-o output.csv]
        [--min-el 5.0]

Dependencies:
    astropy, scipy, numpy
"""

import argparse
import os
import re
import sys
import numpy as np
from datetime import datetime, timedelta, timezone

from scipy.interpolate import CubicHermiteSpline

from astropy.coordinates import (
    GCRS,
    ITRS,
    EarthLocation,
    CartesianRepresentation,
)
from astropy.time import Time
import astropy.units as u


# ---------------------------------------------------------------------------
# Bigdish site parameters  (W1XM / MIT campus)
# ---------------------------------------------------------------------------
BIGDISH = {
    "lat":        42.360236,   # deg N
    "lon":        -71.089478,  # deg E
    "height":     97.0,        # metres above WGS84 ellipsoid
    "slew_time":  30,          # seconds — antenna pre-position lead time
    "min_el":     0.0,         # deg — hard floor (overridden by --min-el)
    "max_el":     87.0,        # deg — hard ceiling
}

OBSERVER = EarthLocation(
    lat=BIGDISH["lat"] * u.deg,
    lon=BIGDISH["lon"] * u.deg,
    height=BIGDISH["height"] * u.m,
)

# The site in earth-fixed coordinates, and the east / north / up it stands in, both
# of which are the same at every epoch and so are worked out once.
OBSERVER_ITRS_KM = np.array([c.to_value(u.km) for c in OBSERVER.geocentric])

_LAT = np.radians(BIGDISH["lat"])
_LON = np.radians(BIGDISH["lon"])
EAST  = np.array([-np.sin(_LON), np.cos(_LON), 0.0])
NORTH = np.array([-np.sin(_LAT) * np.cos(_LON), -np.sin(_LAT) * np.sin(_LON), np.cos(_LAT)])
UP    = np.array([np.cos(_LAT) * np.cos(_LON), np.cos(_LAT) * np.sin(_LON), np.sin(_LAT)])

# The console's pointing-file reader and WR66_run_pointing_file.py both refuse a
# row asking for more than this, so a file that would be refused is worth saying
# so at the time it is written rather than at the time somebody tries to run it.
MAX_RATE = 20.0   # deg/s

# A state vector line starts with one of these; the covariance lines under it are
# seven numbers as well, but none of them can be mistaken for one.
EPOCH_RE = re.compile(r"^\d{13}(\.\d+)?$")

# Header lines are "key:value", sometimes several to a line. A key is a lower-case
# word against a colon, which is what keeps the colons in "17:57:20" out of it.
HEADER_RE = re.compile(r"(?:^|\s)([a-z_]+):(.*?)(?=\s[a-z_]+:|$)")


# ---------------------------------------------------------------------------
# Starlink ephemeris parser
# ---------------------------------------------------------------------------

def parse_epoch(token: str) -> float:
    """
    YYYYDDDHHMMSS.sss in UTC, counting the day of the year rather than the month
    and the day, returned as a Unix timestamp.
    """
    year = int(token[0:4])
    day_of_year = int(token[4:7])
    hour = int(token[7:9])
    minute = int(token[9:11])
    second = float(token[11:])

    if not 1 <= day_of_year <= 366 or hour > 23 or minute > 59 or second >= 61.0:
        raise ValueError(f"'{token}' is not a real instant")

    start_of_year = datetime(year, 1, 1, tzinfo=timezone.utc).timestamp()
    return (start_of_year + (day_of_year - 1) * 86400.0
            + hour * 3600.0 + minute * 60.0 + second)


def parse_starlink(filepath: str) -> tuple[dict, np.ndarray, np.ndarray]:
    """
    Parse a Starlink text ephemeris.

    Returns
    -------
    meta : dict
        The header key/value pairs (created, ephemeris_start, step_size, ...),
        plus "object" taken from the filename, which is the only place the
        satellite is named.
    t_unix : np.ndarray, shape (N,)
        State epoch times as Unix timestamps (float64 seconds).
    states : np.ndarray, shape (N, 6)
        Columns: x, y, z (km), vx, vy, vz (km/s) in J2000 / GCRS.
    """
    meta = {}
    times = []
    states = []
    skipped = 0
    head = []

    with open(filepath, "r") as fh:
        for raw in fh:
            if len(head) < 40:
                head.append(raw)
            line = raw.strip()
            if not line:
                continue

            parts = line.split()

            # Data lines: an epoch and six numbers. Everything else in the file
            # is either a header or a covariance term.
            if len(parts) == 7 and EPOCH_RE.match(parts[0]):
                try:
                    t = parse_epoch(parts[0])
                    sv = [float(v) for v in parts[1:]]
                except ValueError:
                    skipped += 1
                    continue
                times.append(t)
                states.append(sv)
                continue

            # Header lines: "key:value" pairs, several to a line, values holding
            # spaces and colons of their own ("created:2026-08-22 17:57:20 UTC").
            # Only a lower-case word opens a key, so the colons inside a clock
            # time are safely part of the value.
            for key, value in HEADER_RE.findall(line):
                meta[key] = value.strip()

    meta_text = "".join(head)
    if not times:
        # The likeliest reason for a file with no state vectors in it is that it is
        # an ephemeris of some other kind, so say which script wants it.
        hint = ""
        if "CCSDS_OEM_VERS" in meta_text or "META_START" in meta_text:
            hint = " This looks like a CCSDS OEM — oem_to_bigdish_commands.py reads those."
        elif re.search(r"^1 \d{5}", meta_text, re.M):
            hint = " This looks like a TLE — tle_to_bigdish_commands.py reads those."
        raise ValueError(
            f"No state vectors found in {filepath}. Expected lines of "
            f"'YYYYDDDHHMMSS.sss x y z vx vy vz'.{hint}"
        )
    if skipped:
        print(f"  WARNING: skipped {skipped} malformed state vector line(s).")

    t_unix = np.array(times, dtype=np.float64)
    if np.any(np.diff(t_unix) <= 0):
        raise ValueError(
            "Ephemeris epochs are not strictly increasing — check the file."
        )

    # Nothing inside the file says which satellite it is; the filename does, as
    # MEME_<catalog number>_<object>_<rest>.txt.
    name_match = re.match(r"^MEME_\d+_([^_]+)_", os.path.basename(filepath), re.I)
    meta["object"] = name_match.group(1) if name_match else os.path.basename(filepath)

    return meta, t_unix, np.array(states, dtype=np.float64)


# ---------------------------------------------------------------------------
# Interpolator
# ---------------------------------------------------------------------------

def build_interpolator(t_unix: np.ndarray, states: np.ndarray):
    """
    Build a cubic Hermite interpolator over the state vectors.

    Hermite rather than the plain cubic spline the OEM script uses, because
    these files carry velocities alongside the positions and a low orbit needs
    them: at the 60 s spacing SpaceX publish, a satellite departs from the chord
    between two states by about four kilometres, which at a few hundred
    kilometres range is half a degree. Fitting the curve to the velocities as
    well as the positions brings that to metres — see the accuracy check in
    main(), which leaves out every other state and interpolates it back.

    Returns a callable f(t) -> np.ndarray of shape (N, 3), positions in km.
    """
    return CubicHermiteSpline(t_unix, states[:, 0:3], states[:, 3:6], axis=0)


# ---------------------------------------------------------------------------
# J2000 (GCRS) Cartesian → topocentric Az / El
# ---------------------------------------------------------------------------

def gcrs_to_altaz(pos_km: np.ndarray, t_unix: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """
    Convert geocentric J2000 (≈ GCRS) Cartesian positions to topocentric azimuth
    and elevation as seen from the bigdish site.

    The route is J2000 → ITRS, which is the earth-rotation chain and nothing
    else, then the difference from the site and a projection onto the local
    east / north / up. Deliberately *not* astropy's AltAz frame: that goes by way
    of CIRS and applies the aberration and parallax handling meant for a source
    at infinity, which for something a few hundred kilometres up is simply wrong.
    Checked against this geometric route on a real pass, astropy's AltAz differs
    by up to 0.027° -- 40 m of pointing error at 800 km range, growing as the
    range shrinks. The geometric answer agrees with the console's own sampler
    (astronomy-engine, an independent implementation) to 0.0002°.

    What is legitimately left out is small: light travel time moves a satellite
    at 800 km by 20 m (0.001°), and aberration from the observer's own rotation
    is 0.3 arcseconds. Both are far inside the 2.7° beam.

    Vectorised over epochs: one transform for the whole track rather than one
    per command, which for a ten minute pass at 1 s is the difference between
    seconds and minutes.

    Parameters
    ----------
    pos_km : np.ndarray, shape (N, 3)  — positions in km in J2000/GCRS
    t_unix : np.ndarray, shape (N,)    — epochs as Unix timestamps (UTC)

    Returns
    -------
    az_deg, el_deg : np.ndarray, shape (N,)
    """
    t = Time(t_unix, format="unix", scale="utc")
    pos = CartesianRepresentation(
        pos_km[:, 0] * u.km, pos_km[:, 1] * u.km, pos_km[:, 2] * u.km
    )
    itrs = GCRS(pos, obstime=t).transform_to(ITRS(obstime=t))
    topo = itrs.cartesian.xyz.to_value(u.km).T - OBSERVER_ITRS_KM

    east, north, up = topo @ EAST, topo @ NORTH, topo @ UP
    az = np.degrees(np.arctan2(east, north)) % 360.0
    el = np.degrees(np.arctan2(up, np.hypot(east, north)))
    return az, el


# ---------------------------------------------------------------------------
# Passes
# ---------------------------------------------------------------------------

def find_passes(interp, t_min: float, t_max: float, min_el: float,
                sample_s: float = 10.0) -> list:
    """
    Every stretch of the file's coverage where the satellite is above *min_el*.

    Sampled at ten seconds, which is fine enough that no pass is missed: a low
    orbit rises from the horizon to a few degrees in tens of seconds, and the
    shortest pass worth pointing at lasts minutes. Edges are the samples either
    side of the crossing, so a pass is reported very slightly short.

    Returns a list of dicts: start, end (Unix), peak elevation, and the azimuths
    at which it rises and sets.
    """
    epochs = np.arange(t_min, t_max, sample_s)
    az, el = gcrs_to_altaz(interp(epochs), epochs)

    above = el >= min_el
    passes = []
    start_index = None

    for i, is_up in enumerate(above):
        if is_up and start_index is None:
            start_index = i
        elif not is_up and start_index is not None:
            passes.append((start_index, i - 1))
            start_index = None
    if start_index is not None:
        passes.append((start_index, len(above) - 1))

    return [
        {
            "start": float(epochs[a]),
            "end": float(epochs[b]),
            "peak_el": float(np.max(el[a:b + 1])),
            "rise_az": float(az[a]),
            "set_az": float(az[b]),
        }
        for a, b in passes
        if b > a          # a single sample above the horizon is not a pass
    ]


def print_passes(passes: list, min_el: float) -> None:
    if not passes:
        print(f"  No passes above {min_el}° in the coverage of this file.")
        return

    print(f"\n  Passes above {min_el}° (use -p N to track one):\n")
    print("    N  start (UTC)           end (UTC)             mins   peak el   rise az → set az")
    print("    " + "-" * 88)
    for n, p in enumerate(passes, start=1):
        start = Time(p["start"], format="unix", scale="utc").datetime
        end = Time(p["end"], format="unix", scale="utc").datetime
        print(f"    {n:<2} {start:%Y-%m-%dT%H:%M:%SZ}  {end:%Y-%m-%dT%H:%M:%SZ}  "
              f"{(p['end'] - p['start']) / 60:5.1f}   {p['peak_el']:6.2f}°   "
              f"{p['rise_az']:6.1f}° → {p['set_az']:6.1f}°")
    print()


# ---------------------------------------------------------------------------
# Track generator
# ---------------------------------------------------------------------------

def generate_track(interp, t_start_unix: float, t_end_unix: float,
                   interval_s: float, t_min: float, t_max: float) -> list:
    """
    Step through the requested time range at *interval_s* cadence, evaluate the
    interpolated position, and transform to Az/El at each epoch.

    Az/El rates are computed by finite difference to the *next* epoch, matching
    the convention of the OEM and TLE scripts:

        az_rate = (az[t+dt] - az[t]) / dt

    with a ±360° wrap correction for azimuth, which a low orbit passing near
    the zenith will use.

    Returns a list of rows:
        [datetime_utc, az_deg, el_deg, az_rate_deg/s, el_rate_deg/s]

    All rows are returned regardless of elevation limits; limit filtering is
    applied in main() after the full track is computed.
    """
    epochs = np.arange(t_start_unix, t_end_unix + 1e-6, interval_s)

    if epochs[0] < t_min or epochs[-1] > t_max:
        print(
            "  WARNING: requested time window extends outside the ephemeris.\n"
            f"    File covers {Time(t_min, format='unix', scale='utc').isot} "
            f"→ {Time(t_max, format='unix', scale='utc').isot}\n"
            f"    Requested   {Time(epochs[0], format='unix', scale='utc').isot} "
            f"→ {Time(epochs[-1], format='unix', scale='utc').isot}\n"
            "  Clamping to the ephemeris coverage."
        )
        epochs = epochs[(epochs >= t_min) & (epochs <= t_max)]

    if len(epochs) == 0:
        raise ValueError("No command epochs remain after clamping to the ephemeris coverage.")

    # One extra epoch past the end, for the finite difference of the last row
    extra = np.clip(np.append(epochs, epochs[-1] + interval_s), t_min, t_max)

    az, el = gcrs_to_altaz(interp(extra), extra)

    dt = np.diff(extra)                      # interval_s throughout, bar a clamped last step
    dt[dt == 0] = interval_s                 # a last step clamped to nothing: rate is zeroed below

    az_rate = np.diff(az)
    az_rate = np.where(az_rate < -180.0, az_rate + 360.0,
                       np.where(az_rate > 180.0, az_rate - 360.0, az_rate)) / dt
    el_rate = np.diff(el) / dt

    track = [
        [datetime.fromtimestamp(t, tz=timezone.utc), az[i], el[i], az_rate[i], el_rate[i]]
        for i, t in enumerate(epochs)
    ]

    # The dish is asked to stop, not to carry on, at the end of the track
    track[-1][3] = 0.0
    track[-1][4] = 0.0

    return track


# ---------------------------------------------------------------------------
# Command file writer
# ---------------------------------------------------------------------------

def split_segments(track: list, interval_s: float) -> list:
    """
    Break a track wherever elevation filtering has taken rows out of the middle
    of it -- the dish reaching its ceiling on a high pass, most often.

    Each segment is commanded on its own, since the row after a gap is somewhere
    the dish has not been driving towards and needs pre-positioning for.
    """
    segments = [[track[0]]]
    for previous, row in zip(track, track[1:]):
        gap = (row[0] - previous[0]).total_seconds()
        if gap > interval_s * 1.5:
            segments.append([])
        segments[-1].append(row)
    return segments


def report_gap(last_row: list, next_row: list, pre_time: datetime) -> None:
    """
    Say how far the dish has to move across a gap and how long it has to do it.

    A pass through the keyhole leaves by one side of the zenith and comes back
    on the other, so the azimuth on the far side can be most of a turn away with
    seconds to get there. The file still says go, and the dish still lags; how
    badly is worth knowing before the pass rather than after it, since the
    answer may be to track it further from the zenith with --max-el.
    """
    swing = abs(next_row[1] - last_row[1]) % 360.0
    swing = min(swing, 360.0 - swing)
    seconds = (next_row[0] - pre_time).total_seconds()
    print(f"  Gap at {last_row[0]:%H:%M:%S}Z: {swing:.1f}° of azimuth to cover in "
          f"{seconds:.0f} s ({swing / seconds:.1f}°/s) before the track resumes.")


def write_command_file(track: list, out_path: str, interval_s: float,
                       slew_lead_s: int = 30) -> None:
    """
    Write the bigdish command CSV.

    Each segment opens with a stationary pre-position command issued
    *slew_lead_s* seconds ahead of its first track point, so the antenna has
    time to slew and settle. A lead that would land inside the previous segment
    is pulled in to just after it, and dropped altogether if there is no room.
    """
    segments = split_segments(track, interval_s)
    lines = 0

    with open(out_path, "w") as fh:
        previous = None
        for segment in segments:
            pre_time = segment[0][0] - timedelta(seconds=slew_lead_s)
            if previous is not None and pre_time <= previous[0]:
                pre_time = previous[0] + timedelta(seconds=interval_s)
                report_gap(previous, segment[0], pre_time)

            if pre_time < segment[0][0]:
                fh.write(
                    f"{pre_time.strftime('%Y-%m-%dT%H:%M:%SZ')}, azel, "
                    f"{segment[0][1]:0.3f}, {segment[0][2]:0.3f}, 0.000, 0.000\r\n"
                )
                lines += 1

            for dt_obj, az, el, az_r, el_r in segment:
                fh.write(
                    f"{dt_obj.strftime('%Y-%m-%dT%H:%M:%SZ')}, azel, "
                    f"{az:0.3f}, {el:0.3f}, {az_r:0.3f}, {el_r:0.3f}\r\n"
                )
                lines += 1
            previous = segment[-1]

    if len(segments) > 1:
        print(f"  {len(segments)} segments, each pre-positioned: the track leaves the "
              "elevation limits and comes back.")
    print(f"  Wrote {lines} lines (including pre-position) → {out_path}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args():
    scriptname = os.path.basename(sys.argv[0])

    formatter = argparse.RawDescriptionHelpFormatter(scriptname)
    width = formatter._width

    title     = "Bigdish Starlink tracking command generator"
    copyright = "Copyright (c) 2026 Massachusetts Institute of Technology"
    shortdesc = "Convert a Starlink text ephemeris to a bigdish azel command file"

    desc = "\n".join(
        (
            "*" * width,
            "*{0:^{1}}*".format(title, width - 2),
            "*{0:^{1}}*".format(copyright, width - 2),
            "*{0:^{1}}*".format("", width - 2),
            "*{0:^{1}}*".format(shortdesc, width - 2),
            "*" * width,
        )
    )

    parser = argparse.ArgumentParser(
        description=desc,
        prefix_chars="-",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "ephemeris_path",
        metavar="ephemeris_path",
        help="Path to a Starlink text ephemeris (MEME_*.txt)",
    )
    parser.add_argument(
        "-s", "--start",
        dest="start_time",
        type=str,
        default=None,
        help="Start of tracking window, UTC ISO format (e.g. 2026-08-22T21:05:00)",
    )
    parser.add_argument(
        "-e", "--end",
        dest="end_time",
        type=str,
        default=None,
        help="End of tracking window, UTC ISO format (e.g. 2026-08-22T21:15:00)",
    )
    parser.add_argument(
        "-l", "--list-passes",
        dest="list_passes",
        action="store_true",
        help="List the passes above --min-el in this file and exit",
    )
    parser.add_argument(
        "-p", "--pass",
        dest="pass_number",
        type=int,
        default=None,
        help="Track pass N from that list, instead of giving --start and --end",
    )
    parser.add_argument(
        "-i", "--interval",
        dest="interval",
        type=float,
        default=1.0,
        help="Command interval in seconds (default: 1.0)",
    )
    parser.add_argument(
        "-o", "--out",
        dest="out_file",
        type=str,
        default=None,
        help="Output command file path (default: <ephemeris_basename>_bigdish.csv)",
    )
    parser.add_argument(
        "--min-el",
        dest="min_el",
        type=float,
        default=BIGDISH["min_el"],
        help=f"Minimum elevation to include in output (default: {BIGDISH['min_el']} deg)",
    )
    parser.add_argument(
        "--max-el",
        dest="max_el",
        type=float,
        default=BIGDISH["max_el"],
        help=f"Maximum elevation to include in output (default: {BIGDISH['max_el']} deg)",
    )

    args = parser.parse_args()

    given = [args.list_passes, args.pass_number is not None,
             args.start_time is not None or args.end_time is not None]
    if sum(given) != 1:
        parser.error(
            "say exactly one of: --list-passes, --pass N, or --start with --end.")
    if (args.start_time is None) != (args.end_time is None):
        parser.error("--start and --end go together.")

    return args


# ---------------------------------------------------------------------------
# Interpolation accuracy check
# ---------------------------------------------------------------------------

def interpolation_error_km(t_unix: np.ndarray, states: np.ndarray) -> float:
    """
    How far the interpolator is from the file it was built on, in km.

    Built from every other state, then asked for the ones left out, so it
    measures interpolation at twice the spacing the command file actually uses
    and the real error is smaller still -- a cubic's error goes as the fourth
    power of the step, so by around a factor of sixteen. Reported rather than
    checked against a threshold: it is the number that says whether the command
    file is worth more than the chord between two states, and it belongs in
    front of whoever is about to point the dish with it.
    """
    if len(t_unix) < 5:
        return float("nan")

    coarse = CubicHermiteSpline(t_unix[::2], states[::2, 0:3], states[::2, 3:6], axis=0)
    left_out = slice(1, len(t_unix) - 1, 2)
    error = coarse(t_unix[left_out]) - states[left_out, 0:3]
    return float(np.max(np.linalg.norm(error, axis=1)))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    try:
        run(parse_args())
    except (ValueError, OSError) as exc:
        # A file that is not what it was taken for, or is not there at all: the
        # message says what was wrong, and a traceback would only bury it.
        print(f"ERROR: {exc}")
        sys.exit(1)


def run(args):
    """Everything main() does, with the failures it can report left to it."""
    if args.out_file is None:
        base = os.path.splitext(os.path.basename(args.ephemeris_path))[0]
        args.out_file = f"{base}_bigdish.csv"

    print(f"\nEphemeris  : {args.ephemeris_path}")

    # 1. Parse the file
    print("Parsing Starlink ephemeris …")
    meta, t_eph, states = parse_starlink(args.ephemeris_path)
    print(f"  {meta['object']}  |  {len(t_eph)} state vectors  |  "
          f"{Time(t_eph[0], format='unix', scale='utc').isot} → "
          f"{Time(t_eph[-1], format='unix', scale='utc').isot}")
    print(f"  source: {meta.get('ephemeris_source', 'unstated')}  |  "
          f"step: {meta.get('step_size', int(round(t_eph[1] - t_eph[0])))} s  |  "
          f"created: {meta.get('created', 'unstated')}")

    # 2. Build the interpolator
    print("Building cubic Hermite interpolator …")
    interp = build_interpolator(t_eph, states)
    print(f"  worst error at twice the file's step, an upper bound on the real one: "
          f"{interpolation_error_km(t_eph, states) * 1000:.1f} m")

    # 3. Work out the window: from the pass list, or as asked for
    if args.list_passes or args.pass_number is not None:
        print(f"Finding passes above {args.min_el}° …")
        passes = find_passes(interp, t_eph[0], t_eph[-1], args.min_el)

        if args.list_passes:
            print_passes(passes, args.min_el)
            sys.exit(0)

        if not 1 <= args.pass_number <= len(passes):
            print(f"ERROR: pass {args.pass_number} does not exist; this file has "
                  f"{len(passes)} pass(es) above {args.min_el}°. "
                  "Run with --list-passes to see them.")
            sys.exit(1)

        chosen = passes[args.pass_number - 1]
        t_start, t_end = chosen["start"], chosen["end"]
        print(f"  Pass {args.pass_number} of {len(passes)}: peak elevation "
              f"{chosen['peak_el']:.2f}°, {(t_end - t_start) / 60:.1f} minutes")
    else:
        try:
            t_start = Time(args.start_time, format="isot", scale="utc").unix
            t_end = Time(args.end_time, format="isot", scale="utc").unix
        except Exception as exc:
            print(f"ERROR: could not parse start/end times: {exc}")
            sys.exit(1)
        if t_end <= t_start:
            print("ERROR: end time must be after start time.")
            sys.exit(1)

    print(f"Window     : {Time(t_start, format='unix', scale='utc').isot}  →  "
          f"{Time(t_end, format='unix', scale='utc').isot} UTC")
    print(f"Interval   : {args.interval} s")
    print(f"El limits  : {args.min_el}° – {args.max_el}°")
    print(f"Output     : {args.out_file}\n")

    # 4. Generate the full track
    print("Computing Az/El track …")
    track = generate_track(interp, t_start, t_end, args.interval, t_eph[0], t_eph[-1])
    print(f"  {len(track)} command epochs computed")

    # 5. Filter to the dish's elevation limits. Rows outside them are dropped
    #    entirely, so the command file never asks the antenna for a position it
    #    cannot take; what is left is written as one or more segments.
    filtered = [row for row in track if args.min_el <= row[2] <= args.max_el]
    dropped = len(track) - len(filtered)

    if not filtered:
        print(f"  WARNING: no epochs fall within elevation limits "
              f"({args.min_el}° – {args.max_el}°). No output file written.")
        sys.exit(0)

    peak_el = max(row[2] for row in filtered)
    print(f"  {len(filtered)}/{len(track)} epochs within limits  "
          f"(dropped {dropped})  |  peak elevation: {peak_el:.2f}°")

    fastest = max(max(abs(row[3]), abs(row[4])) for row in filtered)
    print(f"  fastest commanded rate: {fastest:.3f}°/s")
    if fastest > MAX_RATE:
        print(f"  WARNING: that is beyond the {MAX_RATE}°/s the pointing-file readers "
              "accept, and such a file will be refused. Track this pass further from "
              "the zenith with --max-el, or leave it alone.")

    # Zero the rates on the last row of the file, as on the last row of each segment
    filtered[-1][3] = 0.0
    filtered[-1][4] = 0.0

    # 6. Write the command file
    print("Writing command file …")
    write_command_file(filtered, args.out_file, args.interval,
                       slew_lead_s=BIGDISH["slew_time"])

    print("\nDone.\n")


if __name__ == "__main__":
    main()
