#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
oem_doppler_plot.py

Given a CCSDS OEM ephemeris file (EME2000 frame, UTC, km / km/s) and a
transmit frequency, plot:

    1. Topocentric range and elevation vs time
    2. Topocentric range rate (km/s) vs time
    3. One-way Doppler shift (kHz) vs time
       — the shift seen at the ground station if the spacecraft transmits
         at exactly f0.  Negate sign convention for uplink.

Range rate is computed properly in the observer (topocentric) frame:

    rho_vec = r_sc - r_obs          (topocentric position, km)
    v_rel   = v_sc - v_obs          (topocentric velocity, km/s)
    rho_dot = dot(rho_hat, v_rel)   (range rate, km/s)

The observer velocity v_obs accounts for Earth rotation (~0.34 km/s at
MIT latitude), which contributes several kHz at S/X-band and must not
be ignored.

Usage
-----
    python oem_doppler_plot.py <oem_file> -f <freq_hz>
        [-s 2026-04-03T12:00:00]   (default: full OEM span)
        [-e 2026-04-03T14:00:00]
        [-i 60]                    (sample interval seconds, default 60)
        [-o plot.png]              (omit to display interactively)

Dependencies
------------
    astropy, scipy, numpy, matplotlib
    Install: pip install astropy scipy numpy matplotlib
"""

import argparse
import os
import sys
import numpy as np
from datetime import timezone

import matplotlib
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.gridspec import GridSpec

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
# Constants
# ---------------------------------------------------------------------------

C_KM_S = 299792.458      # speed of light, km/s

# Bigdish / W1XM site
BIGDISH = {
    "lat":    42.360236,  # deg N
    "lon":   -71.089478,  # deg E
    "height": 97.0,       # metres above WGS84 ellipsoid
}

OBSERVER_LOC = EarthLocation(
    lat=BIGDISH["lat"]    * u.deg,
    lon=BIGDISH["lon"]    * u.deg,
    height=BIGDISH["height"] * u.m,
)


# ---------------------------------------------------------------------------
# OEM parser  (shared logic with oem_to_bigdish_commands.py)
# ---------------------------------------------------------------------------

def parse_oem(filepath: str) -> tuple[dict, np.ndarray, np.ndarray]:
    """
    Parse a CCSDS OEM v2.0 file.

    Returns
    -------
    meta    : dict            — header key/value pairs
    t_unix  : ndarray (N,)   — epoch times as Unix float64 seconds (UTC)
    states  : ndarray (N, 6) — x,y,z [km], vx,vy,vz [km/s] in EME2000/GCRS
    """
    meta, times, states = {}, [], []
    in_meta = False

    with open(filepath) as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("COMMENT"):
                continue
            if line == "META_START":
                in_meta = True;  continue
            if line == "META_STOP":
                in_meta = False; continue
            if in_meta:
                if "=" in line:
                    k, _, v = line.partition("=")
                    meta[k.strip()] = v.strip()
                continue
            if "=" in line and not line[0].isdigit() and line[0] != "-":
                k, _, v = line.partition("=")
                meta[k.strip()] = v.strip()
                continue
            parts = line.split()
            if len(parts) == 7:
                try:
                    t = Time(parts[0], format="isot", scale="utc")
                    times.append(t.unix)
                    states.append([float(v) for v in parts[1:]])
                except Exception:
                    pass

    if not times:
        raise ValueError(f"No state vectors found in {filepath}")
    if meta.get("TIME_SYSTEM", "") != "UTC":
        raise ValueError(
            f"TIME_SYSTEM is '{meta.get('TIME_SYSTEM')}'. Only UTC is supported."
        )

    return meta, np.array(times, dtype=np.float64), np.array(states, dtype=np.float64)


def build_interpolator(t_unix: np.ndarray, states: np.ndarray):
    """Cubic B-spline interpolator over OEM state vectors."""
    if np.any(np.diff(t_unix) <= 0):
        raise ValueError("OEM epochs are not strictly increasing.")
    return make_interp_spline(t_unix, states, k=3)


# ---------------------------------------------------------------------------
# Observer GCRS state (position + velocity)
# ---------------------------------------------------------------------------

def observer_gcrs_state(t_unix_arr: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """
    Return the GCRS Cartesian position (km) and velocity (km/s) of the
    bigdish observer for each epoch in t_unix_arr.

    Velocity is estimated by a 1-second finite difference in GCRS, which
    correctly captures the ~0.34 km/s Earth-rotation contribution at MIT
    latitude without requiring explicit ITRS velocity inputs.
    """
    n = len(t_unix_arr)
    pos_km   = np.empty((n, 3))
    vel_km_s = np.empty((n, 3))

    for i, tu in enumerate(t_unix_arr):
        t  = Time(tu,        format="unix", scale="utc")
        t2 = Time(tu + 1.0,  format="unix", scale="utc")

        # Position at t
        gcrs  = OBSERVER_LOC.get_itrs(obstime=t).transform_to(GCRS(obstime=t))
        c     = gcrs.cartesian
        p0    = np.array([c.x.to(u.km).value,
                          c.y.to(u.km).value,
                          c.z.to(u.km).value])

        # Position at t+1s  →  velocity by finite difference
        gcrs2 = OBSERVER_LOC.get_itrs(obstime=t2).transform_to(GCRS(obstime=t2))
        c2    = gcrs2.cartesian
        p1    = np.array([c2.x.to(u.km).value,
                          c2.y.to(u.km).value,
                          c2.z.to(u.km).value])

        pos_km[i]   = p0
        vel_km_s[i] = p1 - p0          # 1-second difference → km/s

    return pos_km, vel_km_s


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------

def compute_doppler(
    interp,
    t_unix_arr: np.ndarray,
    freq_hz: float,
) -> dict:
    """
    Compute topocentric range, range rate, elevation, and Doppler shift.

    Doppler sign convention  (downlink / spacecraft transmits at f0):
        delta_f = f_rx - f0 = -f0 * rho_dot / c
        Positive = approaching (blue-shift), negative = receding (red-shift).

    Returns dict with arrays keyed by:
        t_unix, range_km, range_rate_km_s, elevation_deg, doppler_hz
    """
    print("  Computing observer GCRS states …")
    obs_pos, obs_vel = observer_gcrs_state(t_unix_arr)

    sv      = interp(t_unix_arr)     # (N, 6)
    sc_pos  = sv[:, :3]              # km  in GCRS / EME2000
    sc_vel  = sv[:, 3:]              # km/s

    # Topocentric vectors
    rho_vec = sc_pos - obs_pos       # (N, 3) km
    v_rel   = sc_vel  - obs_vel      # (N, 3) km/s

    range_km     = np.linalg.norm(rho_vec, axis=1)
    rho_hat      = rho_vec / range_km[:, np.newaxis]
    range_rate   = np.einsum("ij,ij->i", rho_hat, v_rel)   # km/s

    # Elevation via astropy AltAz transform
    print("  Computing elevations …")
    elevations = np.empty(len(t_unix_arr))
    for i, tu in enumerate(t_unix_arr):
        t   = Time(tu, format="unix", scale="utc")
        pos = CartesianRepresentation(
            sc_pos[i, 0]*u.km, sc_pos[i, 1]*u.km, sc_pos[i, 2]*u.km
        )
        gcrs  = GCRS(pos, obstime=t)
        altaz = gcrs.transform_to(AltAz(obstime=t, location=OBSERVER_LOC))
        elevations[i] = float(altaz.alt.deg)

    # One-way Doppler:  delta_f = -f0 * rho_dot / c
    doppler_hz = -freq_hz * range_rate / C_KM_S

    return {
        "t_unix":          t_unix_arr,
        "range_km":        range_km,
        "range_rate_km_s": range_rate,
        "elevation_deg":   elevations,
        "doppler_hz":      doppler_hz,
    }


# ---------------------------------------------------------------------------
# Plotting
# ---------------------------------------------------------------------------

def make_plots(data: dict, freq_hz: float, oem_name: str, out_path: str | None,
               min_el: float = 0.0):

    t_dt = [
        Time(tu, format="unix", scale="utc").to_datetime(timezone=timezone.utc)
        for tu in data["t_unix"]
    ]

    freq_label  = _freq_label(freq_hz)
    doppler_khz = data["doppler_hz"] / 1e3
    zc          = _zero_crossings(data["range_rate_km_s"])

    fig = plt.figure(figsize=(12, 10))
    fig.suptitle(
        f"Topocentric Range Rate & Doppler — {oem_name}\n"
        f"Observer: W1XM bigdish, MIT  |  f₀ = {freq_label}  (one-way downlink)",
        fontsize=13, fontweight="bold", y=0.98,
    )

    gs = GridSpec(3, 1, figure=fig, hspace=0.48)

    # ── Panel 1: Range and elevation ────────────────────────────────────────
    ax1 = fig.add_subplot(gs[0])
    c_range = "#1f77b4"
    c_el    = "#d62728"

    ax1.plot(t_dt, data["range_km"] / 1e3, color=c_range, lw=1.5, label="Range")
    ax1.set_xlim([min(t_dt), max(t_dt)])
    ax1.set_ylabel("Range  (×10³ km)", color=c_range)
    ax1.tick_params(axis="y", labelcolor=c_range)
    ax1.set_title("Range and Elevation")
    shaded = _shade_below_horizon(ax1, t_dt, data["elevation_deg"], min_el)
    _annotate_rise_set(ax1, t_dt, data["elevation_deg"], min_el)

    ax1r = ax1.twinx()
    ax1r.plot(t_dt, data["elevation_deg"], color=c_el, lw=1.2,
              linestyle="--", alpha=0.8, label="Elevation")
    ax1r.set_ylabel("Elevation  (deg)", color=c_el)
    ax1r.tick_params(axis="y", labelcolor=c_el)
    ax1r.axhline(min_el, color=c_el, lw=0.6, linestyle=":")

    lines  = ax1.get_lines() + ax1r.get_lines()
    labels = [l.get_label() for l in lines]
    if shaded:
        from matplotlib.patches import Patch
        lines  = lines  + [Patch(facecolor="lightgrey", alpha=0.6, label=f"Below {min_el}°")]
        labels = labels + [f"Below {min_el}°"]
    #ax1.legend(lines, labels, loc="upper right", fontsize=8)
    _fmt_xaxis(ax1)

    # ── Panel 2: Range rate ─────────────────────────────────────────────────
    ax2 = fig.add_subplot(gs[1])
    ax2.plot(t_dt, data["range_rate_km_s"], color="#2ca02c", lw=1.5)
    ax2.set_xlim([min(t_dt), max(t_dt)])
    ax2.axhline(0, color="black", lw=0.8, linestyle="--", alpha=0.5)
    ax2.set_ylabel("Range rate  (km/s)")
    ax2.set_title("Topocentric Range Rate  (+ = receding, − = approaching)")
    _shade_below_horizon(ax2, t_dt, data["elevation_deg"], min_el)
    _annotate_rise_set(ax2, t_dt, data["elevation_deg"], min_el)
    _annotate_zero_crossings(ax2, t_dt, zc)
    _fmt_xaxis(ax2)

    # Peak annotation
    peak_rr = np.nanmax(np.abs(data["range_rate_km_s"]))
    ax2.text(0.01, 0.97, f"Peak |ṙ| = {peak_rr:.4f} km/s",
             transform=ax2.transAxes, fontsize=8, va="top",
             bbox=dict(boxstyle="round,pad=0.3", facecolor="honeydew",
                       edgecolor="#2ca02c", alpha=0.8))

    # ── Panel 3: Doppler shift ───────────────────────────────────────────────
    ax3 = fig.add_subplot(gs[2])
    ax3.plot(t_dt, doppler_khz, color="#9467bd", lw=1.5)
    ax3.set_xlim([min(t_dt), max(t_dt)])
    ax3.axhline(0, color="black", lw=0.8, linestyle="--", alpha=0.5)
    ax3.set_ylabel("One-way Doppler  (kHz)")
    ax3.set_title(
        f"One-way Doppler Shift at Ground Receiver  (f₀ = {freq_label})"
    )
    _shade_below_horizon(ax3, t_dt, data["elevation_deg"], min_el)
    _annotate_rise_set(ax3, t_dt, data["elevation_deg"], min_el)
    _annotate_zero_crossings(ax3, t_dt, zc)
    _fmt_xaxis(ax3)
    ax3.set_xlabel("Time (UTC)")

    peak_pos = np.nanmax(doppler_khz)
    peak_neg = np.nanmin(doppler_khz)
    stats = (
        f"Peak Doppler:  +{peak_pos:.2f} / {peak_neg:.2f} kHz\n"
        f"  (+ = approaching / blue-shift)"
    )
    ax3.text(0.01, 0.97, stats, transform=ax3.transAxes,
             fontsize=8, va="top",
             bbox=dict(boxstyle="round,pad=0.3", facecolor="lavender",
                       edgecolor="mediumpurple", alpha=0.8))

    if out_path:
        fig.savefig(out_path, dpi=150, bbox_inches="tight")
        print(f"  Plot saved → {out_path}")
    else:
        plt.show()

    plt.close(fig)


# ---------------------------------------------------------------------------
# Plot helpers
# ---------------------------------------------------------------------------

def _fmt_xaxis(ax):
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d\n%H:%M"))
    ax.xaxis.set_major_locator(mdates.AutoDateLocator())
    ax.tick_params(axis="x", labelsize=7)
    ax.grid(True, alpha=0.3)


def _shade_below_horizon(ax, t_dt, elevations, min_el: float = 0.0):
    """
    Shade contiguous spans where elevation < min_el with a grey overlay,
    and return True if any shading was applied (so the caller can add a
    legend entry).
    """
    below = np.array(elevations) < min_el
    if not np.any(below):
        return False

    # Find contiguous below-horizon spans by detecting transitions
    # Pad with False on both ends so edge spans are detected cleanly
    padded = np.concatenate(([False], below, [False]))
    starts = np.where(~padded[:-1] &  padded[1:])[0]   # indices where below begins
    ends   = np.where( padded[:-1] & ~padded[1:])[0]   # indices where below ends

    ylim = ax.get_ylim()
    for s, e in zip(starts, ends):
        # s and e are indices into the padded array; unshift by 1 to get
        # indices into t_dt, then clamp to valid range
        i0 = max(s - 1, 0)
        i1 = min(e,     len(t_dt) - 1)
        ax.axvspan(t_dt[i0], t_dt[i1],
                   color="lightgrey", alpha=0.45, lw=0,
                   label="_nolegend_")
    ax.set_ylim(ylim)
    return True


def _annotate_rise_set(ax, t_dt, elevations, min_el: float = 0.0):
    """
    Draw labelled vertical dashed lines at rise and set transitions
    (elevation crosses min_el).  Labels are placed at the top of the axes.
    """
    el   = np.array(elevations)
    visible = el >= min_el
    padded  = np.concatenate(([False], visible, [False]))

    rises = np.where(~padded[:-1] &  padded[1:])[0]
    sets  = np.where( padded[:-1] & ~padded[1:])[0]

    ymax = ax.get_ylim()[1]

    for idx in rises:
        i = min(idx, len(t_dt) - 1)
        ax.axvline(t_dt[i], color="#d62728", lw=1.0, linestyle="--", alpha=0.7)
        ax.text(t_dt[i], ymax, " rise", fontsize=7, color="#d62728",
                va="top", ha="left", rotation=90, clip_on=True)

    for idx in sets:
        i = min(max(idx - 1, 0), len(t_dt) - 1)
        ax.axvline(t_dt[i], color="#1f77b4", lw=1.0, linestyle="--", alpha=0.7)
        ax.text(t_dt[i], ymax, " set ", fontsize=7, color="#1f77b4",
                va="top", ha="right", rotation=90, clip_on=True)


def _zero_crossings(arr: np.ndarray) -> list[int]:
    """Indices just before sign changes (range-rate turnarounds)."""
    signs = np.sign(arr)
    return [i for i in range(len(signs) - 1)
            if signs[i] != 0 and signs[i+1] != 0 and signs[i] != signs[i+1]]


def _annotate_zero_crossings(ax, t_dt, zc: list[int]):
    for idx in zc:
        ax.axvline(t_dt[idx], color="grey", lw=0.8, linestyle=":")
        ax.text(t_dt[idx], ax.get_ylim()[0], "  ṙ=0",
                fontsize=7, color="grey", va="bottom", rotation=90)


def _freq_label(freq_hz: float) -> str:
    if freq_hz >= 1e9:
        return f"{freq_hz/1e9:.6g} GHz"
    if freq_hz >= 1e6:
        return f"{freq_hz/1e6:.6g} MHz"
    return f"{freq_hz/1e3:.6g} kHz"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args():
    scriptname = os.path.basename(sys.argv[0])
    formatter  = argparse.RawDescriptionHelpFormatter(scriptname)
    width      = formatter._width

    desc = "\n".join((
        "*" * width,
        "*{0:^{1}}*".format("OEM Doppler / Range-Rate Plot Generator",          width-2),
        "*{0:^{1}}*".format("Copyright (c) 2025 Massachusetts Institute of Technology", width-2),
        "*{0:^{1}}*".format("",                                                  width-2),
        "*{0:^{1}}*".format(
            "Plot topocentric range rate and Doppler from a CCSDS OEM file",     width-2),
        "*" * width,
    ))

    parser = argparse.ArgumentParser(
        description=desc,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("oem_path", metavar="oem_path",
                        help="Path to CCSDS OEM file (.asc / .oem / .txt)")
    parser.add_argument("-f", "--freq", dest="freq_hz", required=True,
                        type=float,
                        help="Transmit frequency in Hz  (e.g. 2250e6 for S-band, "
                             "8425e6 for X-band)")
    parser.add_argument("-s", "--start", dest="start_time", type=str,
                        default=None,
                        help="Start of plot window, UTC ISO (default: OEM start)")
    parser.add_argument("-e", "--end", dest="end_time", type=str,
                        default=None,
                        help="End of plot window, UTC ISO (default: OEM end)")
    parser.add_argument("-i", "--interval", dest="interval", type=float,
                        default=60.0,
                        help="Sample interval in seconds (default: 60)")
    parser.add_argument("-o", "--out", dest="out_file", type=str,
                        default=None,
                        help="Output image path (.png / .pdf). "
                             "Omit to display interactively.")
    parser.add_argument("--min-el", dest="min_el", type=float, default=0.0,
                        help="Minimum elevation for 'visible' shading in degrees "
                             "(default: 0 = geometric horizon)")
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    args = parse_args()

    if args.out_file is None:
        base = os.path.splitext(os.path.basename(args.oem_path))[0]
        args.out_file = f"{base}_doppler.png"

    print(f"\nOEM file   : {args.oem_path}")
    print(f"Frequency  : {_freq_label(args.freq_hz)}")
    print(f"Interval   : {args.interval} s")
    print(f"Output     : {args.out_file}\n")

    # 1. Parse & interpolate
    print("Parsing OEM file …")
    meta, t_oem, states = parse_oem(args.oem_path)
    print(f"  {len(t_oem)} state vectors  |  "
          f"{Time(t_oem[0], format='unix', scale='utc').isot} → "
          f"{Time(t_oem[-1], format='unix', scale='utc').isot}")

    interp = build_interpolator(t_oem, states)

    # 2. Build sample epoch grid
    t_start_unix = (
        Time(args.start_time, format="isot", scale="utc").unix
        if args.start_time else t_oem[0]
    )
    t_end_unix = (
        Time(args.end_time, format="isot", scale="utc").unix
        if args.end_time else t_oem[-1]
    )
    t_start_unix = max(t_start_unix, t_oem[0])
    t_end_unix   = min(t_end_unix,   t_oem[-1])

    t_arr = np.arange(t_start_unix, t_end_unix + 1e-6, args.interval)
    print(f"  {len(t_arr)} sample epochs over "
          f"{(t_end_unix - t_start_unix)/3600:.2f} hours\n")

    # 3. Compute
    print("Computing range rate and Doppler …")
    data = compute_doppler(interp, t_arr, args.freq_hz)

    peak_rr  = np.nanmax(np.abs(data["range_rate_km_s"]))
    peak_dop = np.nanmax(np.abs(data["doppler_hz"])) / 1e3
    print(f"  Peak |range rate| : {peak_rr:.4f} km/s")
    print(f"  Peak |Doppler|    : {peak_dop:.3f} kHz")

    # 4. Plot
    print("Generating plot …")
    oem_name = meta.get("OBJECT_NAME", os.path.basename(args.oem_path))
    make_plots(data, args.freq_hz, oem_name, args.out_file, min_el=args.min_el)

    print("\nDone.\n")


if __name__ == "__main__":
    main()
