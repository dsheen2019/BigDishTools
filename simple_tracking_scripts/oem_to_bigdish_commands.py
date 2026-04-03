#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
oem_to_bigdish_commands.py

Convert a CCSDS OEM ephemeris file (EME2000 frame, UTC time system, km / km/s)
to a vector tracking command file for the W1XM bigdish antenna at MIT.

Output format (one line per command epoch):
    UTC_ISO, azel, azimuth_deg, elevation_deg, az_rate_deg/s, el_rate_deg/s

The time tag on each line is the moment the antenna should *already be* at that
position/rate — identical convention to the TLE-based script this replaces.

Usage:
    python oem_to_bigdish_commands.py <oem_file>
        -s 2026-04-03T12:00:00
        -e 2026-04-03T14:00:00
        [-i 1.0]
        [-o output.csv]
        [--min-el 5.0]

Dependencies:
    astropy, scipy, numpy
"""

import argparse
import os
import sys
import numpy as np
from datetime import datetime, timedelta, timezone

from scipy.interpolate import make_interp_spline

from astropy.coordinates import (
    GCRS,
    AltAz,
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


# ---------------------------------------------------------------------------
# OEM parser
# ---------------------------------------------------------------------------

def parse_oem(filepath: str) -> tuple[dict, np.ndarray, np.ndarray]:
    """
    Parse a CCSDS OEM v2.0 file.

    Returns
    -------
    meta : dict
        Header key/value pairs (REF_FRAME, TIME_SYSTEM, etc.)
    t_unix : np.ndarray, shape (N,)
        State epoch times as Unix timestamps (float64 seconds).
    states : np.ndarray, shape (N, 6)
        Columns: x, y, z (km), vx, vy, vz (km/s) in EME2000 / GCRS.
    """
    meta = {}
    times = []
    states = []

    in_meta = False
    with open(filepath, "r") as fh:
        for raw in fh:
            line = raw.strip()

            # Skip blank lines and COMMENT lines
            if not line or line.startswith("COMMENT"):
                continue

            if line == "META_START":
                in_meta = True
                continue
            if line == "META_STOP":
                in_meta = False
                continue

            if in_meta:
                if "=" in line:
                    key, _, val = line.partition("=")
                    meta[key.strip()] = val.strip()
                continue

            # Header key=value lines outside META block
            if "=" in line and not line[0].isdigit() and line[0] != "-":
                key, _, val = line.partition("=")
                meta[key.strip()] = val.strip()
                continue

            # Data lines: starts with a date string YYYY-MM-DD...
            parts = line.split()
            if len(parts) == 7:
                try:
                    t = Time(parts[0], format="isot", scale="utc")
                    sv = [float(v) for v in parts[1:]]
                    times.append(t.unix)
                    states.append(sv)
                except Exception:
                    pass  # silently skip malformed lines

    if not times:
        raise ValueError(f"No state vectors found in {filepath}")

    ref_frame = meta.get("REF_FRAME", "UNKNOWN")
    time_sys  = meta.get("TIME_SYSTEM", "UNKNOWN")

    if ref_frame != "EME2000":
        print(f"  WARNING: REF_FRAME is '{ref_frame}', expected EME2000. "
              "Proceeding anyway — verify the frame is compatible with GCRS.")
    if time_sys != "UTC":
        raise ValueError(
            f"TIME_SYSTEM is '{time_sys}'. Only UTC is supported. "
            "Convert the OEM to UTC before running this script."
        )

    return meta, np.array(times, dtype=np.float64), np.array(states, dtype=np.float64)


# ---------------------------------------------------------------------------
# Interpolator
# ---------------------------------------------------------------------------

def build_interpolator(t_unix: np.ndarray, states: np.ndarray):
    """
    Build a cubic B-spline interpolator over the OEM state vectors.

    EME2000 / GCRS position and velocity vary smoothly along a lunar
    trajectory, so a cubic spline (k=3) with natural boundary conditions
    gives sub-metre interpolation accuracy at typical OEM spacings.

    Returns a callable f(t) -> np.ndarray of shape (6,) or (N, 6).
    """
    # scipy make_interp_spline requires strictly increasing x
    if np.any(np.diff(t_unix) <= 0):
        raise ValueError("OEM epochs are not strictly increasing — check the file.")

    spl = make_interp_spline(t_unix, states, k=3)
    return spl


# ---------------------------------------------------------------------------
# Single epoch: EME2000 (GCRS) Cartesian → topocentric Az / El
# ---------------------------------------------------------------------------

def gcrs_to_altaz(x_km: float, y_km: float, z_km: float,
                  t_unix: float) -> tuple[float, float]:
    """
    Convert a geocentric EME2000 (≈ GCRS) Cartesian position to topocentric
    azimuth and elevation as seen from the bigdish site.

    Parameters
    ----------
    x_km, y_km, z_km : float   — position in km in EME2000/GCRS
    t_unix : float             — epoch as Unix timestamp (UTC)

    Returns
    -------
    az_deg, el_deg : float
    """
    t = Time(t_unix, format="unix", scale="utc")
    pos = CartesianRepresentation(x_km * u.km, y_km * u.km, z_km * u.km)
    gcrs = GCRS(pos, obstime=t)
    altaz = gcrs.transform_to(AltAz(obstime=t, location=OBSERVER))
    return float(altaz.az.deg), float(altaz.alt.deg)


# ---------------------------------------------------------------------------
# Track generator
# ---------------------------------------------------------------------------

def generate_track(
    interp,
    t_start_unix: float,
    t_end_unix: float,
    interval_s: float,
    oem_t_min: float,
    oem_t_max: float,
    min_el: float,
) -> list:
    """
    Step through the requested time range at *interval_s* cadence, evaluate
    the interpolated GCRS state, and transform to Az/El at each epoch.

    Az/El rates are computed by finite difference to the *next* epoch,
    matching exactly the convention in the TLE-based script:

        az_rate = (az[t+dt] - az[t]) / dt

    with a ±360° wrap correction for azimuth.

    Returns a list of rows:
        [datetime_utc, az_deg, el_deg, az_rate_deg/s, el_rate_deg/s]

    All rows are returned regardless of elevation limits; limit filtering
    is applied in main() after the full track is computed.
    """

    # Build the command epoch grid
    epochs_unix = np.arange(t_start_unix, t_end_unix + 1e-6, interval_s)

    # Clamp to OEM coverage with a warning
    oem_lo = oem_t_min
    oem_hi = oem_t_max
    if epochs_unix[0] < oem_lo or epochs_unix[-1] > oem_hi:
        print(
            "  WARNING: requested time window extends outside OEM coverage.\n"
            f"    OEM covers  {Time(oem_lo, format='unix', scale='utc').isot} "
            f"→ {Time(oem_hi, format='unix', scale='utc').isot}\n"
            f"    Requested   {Time(epochs_unix[0], format='unix', scale='utc').isot} "
            f"→ {Time(epochs_unix[-1], format='unix', scale='utc').isot}\n"
            "  Clamping to OEM coverage."
        )
        epochs_unix = epochs_unix[
            (epochs_unix >= oem_lo) & (epochs_unix <= oem_hi)
        ]

    if len(epochs_unix) == 0:
        raise ValueError("No command epochs remain after clamping to OEM coverage.")

    # Evaluate states at all epochs *and* one step ahead for rate computation
    # We add one extra epoch at the end for the finite-difference step
    extra = np.append(epochs_unix, epochs_unix[-1] + interval_s)
    extra = np.clip(extra, oem_lo, oem_hi)

    sv_all = interp(extra)          # shape (N+1, 6)

    track = []
    n = len(epochs_unix)

    for i in range(n):
        t_unix_i  = epochs_unix[i]
        t_unix_i1 = extra[i + 1]   # next step (possibly clamped at end)

        x, y, z = sv_all[i, 0], sv_all[i, 1], sv_all[i, 2]
        az,  el  = gcrs_to_altaz(x, y, z, t_unix_i)

        x1, y1, z1 = sv_all[i + 1, 0], sv_all[i + 1, 1], sv_all[i + 1, 2]
        az1, el1 = gcrs_to_altaz(x1, y1, z1, t_unix_i1)

        dt = t_unix_i1 - t_unix_i  # should equal interval_s except at end

        # Az rate with ±180° wrap correction (matches TLE script logic)
        az_rate = (az1 - az) / dt
        if az_rate < -180.0:
            az_rate = (az1 - az + 360.0) / dt
        elif az_rate > 180.0:
            az_rate = (az1 - az - 360.0) / dt

        el_rate = (el1 - el) / dt

        dt_obj = datetime.fromtimestamp(t_unix_i, tz=timezone.utc)
        track.append([dt_obj, az, el, az_rate, el_rate])

    # Zero out rates on the final command (matches TLE script convention)
    track[-1][3] = 0.0
    track[-1][4] = 0.0

    return track


# ---------------------------------------------------------------------------
# Command file writer
# ---------------------------------------------------------------------------

def write_command_file(track: list, out_path: str, slew_lead_s: int = 30) -> None:
    """
    Write the bigdish command CSV.

    The first line is a stationary pre-position command issued
    *slew_lead_s* seconds before the first track point so the antenna
    has time to slew and settle — identical to the TLE script behaviour.
    """
    with open(out_path, "w") as fh:
        # Pre-position line
        pre_time = track[0][0] - timedelta(seconds=slew_lead_s)
        fh.write(
            f"{pre_time.strftime('%Y-%m-%dT%H:%M:%SZ')}, azel, "
            f"{track[0][1]:0.3f}, {track[0][2]:0.3f}, 0.000, 0.000\r\n"
        )
        # Main track
        for row in track:
            dt, az, el, az_r, el_r = row
            fh.write(
                f"{dt.strftime('%Y-%m-%dT%H:%M:%SZ')}, azel, "
                f"{az:0.3f}, {el:0.3f}, {az_r:0.3f}, {el_r:0.3f}\r\n"
            )

    print(f"  Wrote {len(track) + 1} lines (including pre-position) → {out_path}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args():
    scriptname = os.path.basename(sys.argv[0])

    formatter = argparse.RawDescriptionHelpFormatter(scriptname)
    width = formatter._width

    title     = "Bigdish OEM tracking command generator"
    copyright = "Copyright (c) 2025 Massachusetts Institute of Technology"
    shortdesc = "Convert a CCSDS OEM (EME2000/UTC) to a bigdish azel command file"

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
        "oem_path",
        metavar="oem_path",
        help="Path to CCSDS OEM file (.asc / .oem / .txt)",
    )
    parser.add_argument(
        "-s", "--start",
        dest="start_time",
        required=True,
        type=str,
        help="Start of tracking window, UTC ISO format (e.g. 2026-04-03T12:00:00)",
    )
    parser.add_argument(
        "-e", "--end",
        dest="end_time",
        required=True,
        type=str,
        help="End of tracking window, UTC ISO format (e.g. 2026-04-03T14:00:00)",
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
        help="Output command file path (default: <oem_basename>_bigdish.csv)",
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

    return parser.parse_args()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    args = parse_args()

    # Default output filename
    if args.out_file is None:
        base = os.path.splitext(os.path.basename(args.oem_path))[0]
        args.out_file = f"{base}_bigdish.csv"

    # Parse start / end times → Unix
    try:
        t_start = Time(args.start_time, format="isot", scale="utc")
        t_end   = Time(args.end_time,   format="isot", scale="utc")
    except Exception as exc:
        print(f"ERROR: could not parse start/end times: {exc}")
        sys.exit(1)

    if t_end <= t_start:
        print("ERROR: end time must be after start time.")
        sys.exit(1)

    print(f"\nOEM file   : {args.oem_path}")
    print(f"Window     : {t_start.isot}  →  {t_end.isot} UTC")
    print(f"Interval   : {args.interval} s")
    print(f"El limits  : {args.min_el}° – {args.max_el}°")
    print(f"Output     : {args.out_file}\n")

    # 1. Parse OEM
    print("Parsing OEM file …")
    meta, t_oem, states = parse_oem(args.oem_path)
    print(f"  {len(t_oem)} state vectors  |  "
          f"{Time(t_oem[0], format='unix', scale='utc').isot} → "
          f"{Time(t_oem[-1], format='unix', scale='utc').isot}")

    # 2. Build interpolator
    print("Building spline interpolator …")
    interp = build_interpolator(t_oem, states)

    # 3. Generate full track
    print("Computing Az/El track …")
    track = generate_track(
        interp,
        t_start.unix,
        t_end.unix,
        args.interval,
        t_oem[0],
        t_oem[-1],
        args.min_el,
    )
    print(f"  {len(track)} command epochs computed")

    # 4. Filter to dish elevation limits
    #    Rows outside [min_el, max_el] are dropped entirely so the command
    #    file never asks the antenna to move to an illegal position.
    #    If the track re-enters the valid window after an excursion (e.g.
    #    the object sets and rises again) each valid segment is written
    #    with its own pre-position command in write_command_file.
    filtered = [row for row in track if args.min_el <= row[2] <= args.max_el]

    n_total    = len(track)
    n_filtered = len(filtered)
    n_dropped  = n_total - n_filtered

    if n_filtered == 0:
        print(f"  WARNING: no epochs fall within elevation limits "
              f"({args.min_el}° – {args.max_el}°). No output file written.")
        sys.exit(0)

    peak_el = max(row[2] for row in filtered)
    print(f"  {n_filtered}/{n_total} epochs within limits  "
          f"(dropped {n_dropped})  |  peak elevation: {peak_el:.2f}°")

    # Zero out rates on the new last command after filtering
    filtered[-1][3] = 0.0
    filtered[-1][4] = 0.0

    # 5. Write command file
    print("Writing command file …")
    write_command_file(filtered, args.out_file, slew_lead_s=BIGDISH["slew_time"])

    print("\nDone.\n")


if __name__ == "__main__":
    main()
