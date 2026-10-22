#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""

Generate times/coordinates for satellite intercepts near target RA/DEC observation location


Use IAU-CPS satchecker query, fall back to a local coarse calculation using celestrak if that fails

for Starlink sats that pass near target, get starlink provided ephemeris and compute precise coordinates and timing.
(in theory stachecker handles those but I haven't done enough to fully trust it yet)

INPUTS:
    ra:
        right ascension of observation. J2000 (decimal degrees, or sexagesimal hours e.g. 10:30:00)
    dec:
        declination of observation. J2000 (decimal degrees, or sexagesimal e.g. +20:00:00)
    radius:
        search radius around source in decimal degrees
    start:
        start time of observation as UTC Time in ISO Format (e.g. 2025-06-24T00:25:43Z)
    end:
        optional, need end or duration, end time of observation as UTC Time in ISO Format (e.g. 2025-06-24T00:25:43Z)
    duration:
        optional, need end or duration, length of observing window in seconds
    constellations:
        constellation or other sat identifier terms to include in output
    antenna:
        antenna to compute from (key into `antennas`)
    out_dir:
        folder to save outputs to. defaults to current working directory
    catalog:
        optional, path to a saved celestrak CSV to propagate instead of downloading one.
        celestrak only serves *current* elements and only lets you fetch every couple of
        hours, so a past observation needs the catalogue you saved at the time. The local
        fallback is only as good as the elements it is given -- propagating a TLE weeks
        past its epoch is meaningless and it warns when you do.
    local:
        optional, skip satchecker and go straight to the local calculation
    coarse_step / fine_step:
        optional, time resolution in seconds of the all-sky search (default 1.0) and of
        the per-candidate refinement (default 0.1)

RETURNS:
    comma separated list of:
        UTC Time, Satellite Name, NORAD ID, closest approach coordinates in ra/dec J2000
        saved to .csv file and printed to screen

    Saves all starlink ephemeris from starlink API as individual files.
"""

import argparse
import csv
import logging
import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
import urllib.request

from datetime import datetime, timezone
import astropy.units as u
import numpy as np
from scipy.interpolate import CubicHermiteSpline
import requests
from astropy.time import Time
from astropy.coordinates import (
    GCRS,
    ITRS,
    ICRS,
    AltAz,
    EarthLocation,
    SkyCoord,
    CartesianRepresentation,
)


from sgp4 import omm
from sgp4.api import Satrec
from skyfield.api import load, wgs84, EarthSatellite

from satellite_import_tools import Satellite_Trajectory_Calculator



log = logging.getLogger(__name__)

SATCHECKER_URL = "https://satchecker.cps.iau.org"
CELESTRAK_URL = "https://celestrak.org/NORAD/elements/gp.php?GROUP=active&FORMAT=csv" #query for latest TLEs of all active sats from celestrak
STARLINK_EPHEMERIDES_PATH ="https://api.starlink.com/public-files/ephemerides/"
STARLINK_EPHEMERIS_MANIFEST = "https://api.starlink.com/public-files/ephemerides/MANIFEST.txt"


# A starlink state vector line starts with one of these; the covariance lines under it are
# seven numbers as well, but none of them can be mistaken for one.
EPOCH_RE = re.compile(r"^\d{13}(\.\d+)?$")

# starlink Header lines are "key:value", sometimes several to a line. A key is a lower-case
# word against a colon, which is what keeps the colons in "17:57:20" out of it.
HEADER_RE = re.compile(r"(?:^|\s)([a-z_]+):(.*?)(?=\s[a-z_]+:|$)")

# Fastest a satellite crosses the sky, deg/s. A circular orbit at 300 km does ~1.25 deg/s
# overhead; 1.5 is a comfortable bound for anything we'd care about. Used to widen the
# coarse search cone so a sampled grid can't step straight over a small FOV.
MAX_SKY_RATE_DEG_S = 1.5

# A TLE propagated this far from its epoch is not worth reporting. SGP4 doesn't complain,
# it just quietly produces nonsense -- a year-stale starlink element puts the satellite
# 6.5e12 km away with a perfectly plausible-looking az/el.
STALE_TLE_WARN_DAYS = 7.0

# Anything beyond this range (km) came out of a broken propagation, not an orbit.
MAX_PLAUSIBLE_RANGE_KM = 1.0e6


antennas = {
    "westford":
        {
        "slew_time": 90.0,
        "min_elevation": 5.0,  # idk what this was just remeber it isn't really quite down to the horizon normally
        "max_elevation": 87.0,
        "feed_el_offset": -7.50,
        "feed_az_offset": 0.0,
        "coords_wgs84":
            {
            "lat": 42.61295,
            "lon": -71.49379,
            "el": 104,  # 86.76897, not sure where 86 is from but this seems like a bit better estimate for my purposes. need to investigate further at some point
            },
        },
    "bigdish":
        {
        "slew_time": 30,
        "min_elevation": 0.0,
        "max_elevation": 87.0,
        "feed_el_offset": 0.0,
        "feed_az_offset": 0.0,
        "coords_wgs84":
            {
            "lat": 42.360236,
            "lon": -71.089478,
            "el": 97.0,
            },
        },
    "haystack_37m":         {
        "min_elevation": 0.0,
        "max_elevation": 90.0, #I have no idea what this actually is
        "feed_el_offset": 0.0,
        "feed_az_offset": 0.0,
        "coords_wgs84":
            {
            "lat": 42.62329053,
            "lon": -71.48814111,
            "el": 120.6,
            },
        },
    }


# ---------------------------------------------------------------------------
# Transit container
# ---------------------------------------------------------------------------

@dataclass
class Transit:
    name: str
    norad_id: int
    jd_start: float
    jd_end: float
    min_sep_deg: float  # closest approach to FOV centre
    positions: list = field(default_factory=list)  # dicts w/ julian_date, ra, dec, angle, altitude, azimuth, ...
    source: str = "satchecker"

    @property
    def closest(self):
        """Position dict at closest approach."""
        return min(self.positions, key=lambda p: p["angle"])


def transits_from_positions(sats, gap_s=5.0, source="satchecker"):
    """Turn per-satellite position lists ({key: {name, norad_id, positions:[...]}})
    into discrete transits. A satellite can enter the FOV more than once in a long
    window, so split on time gaps. Your local code can return this same shape."""
    out = []
    gap_jd = gap_s / 86400.0
    for sat in sats.values():
        pos = sorted(sat.get("positions", []), key=lambda p: p["julian_date"])
        if not pos:
            continue
        chunk = [pos[0]]
        for p in pos[1:]:
            if p["julian_date"] - chunk[-1]["julian_date"] > gap_jd:
                out.append(_make_transit(sat, chunk, source))
                chunk = []
            chunk.append(p)
        out.append(_make_transit(sat, chunk, source))
    out.sort(key=lambda t: t.jd_start)
    return out


def _make_transit(sat, chunk, source):
    return Transit(
        name=sat["name"],
        norad_id=int(sat["norad_id"]),
        jd_start=chunk[0]["julian_date"],
        jd_end=chunk[-1]["julian_date"],
        min_sep_deg=min(p["angle"] for p in chunk),
        positions=chunk,
        source=source,
    )


# ---------------------------------------------------------------------------
# SatChecker client
# ---------------------------------------------------------------------------

class SatCheckerUnavailable(Exception):
    """Server unreachable, timed out, 5xx/429, or returned garbage -> fall back."""


class SatCheckerRequestError(Exception):
    """4xx: our request is wrong. Don't silently fall back on this."""


class NoCatalog(Exception):
    """Nothing to propagate: celestrak wouldn't answer and no saved copy was found."""


def _sc_get(session, url, params=None, timeout=(3.0, 15.0)):
    r = session.get(url, params=params, timeout=timeout,
                    headers={"accept": "application/json"})
    if 400 <= r.status_code < 500 and r.status_code != 429:
        raise SatCheckerRequestError(f"{r.status_code}: {r.text[:500]}")
    r.raise_for_status()
    body = r.json()
    # SatChecker wraps responses in a one-element list
    if isinstance(body, list):
        if not body:
            raise SatCheckerUnavailable("empty response")
        body = body[0]
    return body


def query_satchecker(coord, t_start, duration_s, radius_deg, location,
                     constellation=None, connect_timeout=3.0, read_timeout=120.0,
                     total_timeout=120.0, poll_interval=1.0, session=None):
    s = session or requests.Session()
    icrs = coord.icrs
    params = {
        "latitude": location.lat.deg,
        "longitude": location.lon.deg,
        "elevation": location.height.to_value(u.m),
        "start_time_jd": f"{t_start.utc.jd:.8f}",
        "duration": int(np.ceil(duration_s)),  # seconds
        "ra": icrs.ra.deg,
        "dec": icrs.dec.deg,
        "fov_radius": radius_deg,
        "group_by": "satellite",
        "async": "True",
    }
    if constellation:
        params["constellation"] = constellation

    timeout = (connect_timeout, read_timeout)
    deadline = time.monotonic() + total_timeout
    try:
        body = _sc_get(s, f"{SATCHECKER_URL}/fov/satellite-passes/", params, timeout)

        # Async (default): poll task-status until done or we run out of patience
        if "data" not in body and "task_id" in body:
            task_id = body["task_id"]
            while body.get("status") != "SUCCESS":
                if time.monotonic() + poll_interval > deadline:
                    raise SatCheckerUnavailable(f"task {task_id} not done after {total_timeout}s")
                time.sleep(poll_interval)
                body = _sc_get(s, f"{SATCHECKER_URL}/fov/task-status/{task_id}", None, timeout)
                if body.get("status") in ("FAILURE", "REVOKED"):
                    raise SatCheckerUnavailable(f"task {task_id}: {body.get('message')}")

        sats = body["data"]["satellites"]
    except (SatCheckerRequestError, SatCheckerUnavailable):
        raise
    except (requests.RequestException, ValueError, KeyError, TypeError) as e:
        # connection refused/timeout, 5xx, bad JSON, unexpected schema
        raise SatCheckerUnavailable(f"{type(e).__name__}: {e}") from e

    return transits_from_positions(sats, source="satchecker")

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

# ---------------------------------------------------------------------------
# Starlink File Handler borrowed from my other code
# ---------------------------------------------------------------------------

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
# Starlink Interpolator
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

def interpolation_error_km(t_unix: np.ndarray, states: np.ndarray) -> float:
    """
    How far the interpolator is from the file it was built on, in km.

    Built from every other state, then interpolated to original file resolution 
    and compared for error
    """
    if len(t_unix) < 5:
        return float("nan")

    coarse = CubicHermiteSpline(t_unix[::2], states[::2, 0:3], states[::2, 3:6], axis=0)
    left_out = slice(1, len(t_unix) - 1, 2)
    error = coarse(t_unix[left_out]) - states[left_out, 0:3]
    return float(np.max(np.linalg.norm(error, axis=1)))


# ---------------------------------------------------------------------------
# J2000 (GCRS) Cartesian → topocentric Az / El
# ---------------------------------------------------------------------------

def eme2000_track(pos_km: np.ndarray, t: Time, location: EarthLocation):
    """
    Geocentric EME2000 (≈ GCRS; the frame bias between them is 23 mas) Cartesian
    positions -> what the antenna at `location` sees.

    Az/El: GCRS -> ITRS is pure rotation (precession/nutation, earth rotation,
    polar motion), then subtract the site to get a *topocentric* ITRS vector.
    An ITRS frame carrying `location` goes straight to AltAz by geometry alone
    (astropy >= 5.2), so there's no CIRS detour and none of the
    aberration/parallax handling meant for sources at infinity. Same answer
    as projecting onto local east/north/up by hand, but astropy keeps the
    geodetic normal and polar motion consistent for us. Refraction is off
    (pressure=0 default).

    RA/Dec: the "J2000-equivalent" direction, i.e. the ICRS catalogue position
    a star would need to have to appear exactly where the satellite does. Built
    by taking the apparent az/el *direction* (no distance -> treated as infinitely
    far) back through AltAz -> ICRS, which puts back the annual + diurnal
    aberration the target itself gets. That makes `target.icrs.separation(...)`
    an honest apparent-sky separation. (The plain geometric topocentric direction
    in GCRS axes differs from this by up to ~20.5" of annual aberration.)

    Light-time (~2 ms, ~15 m at 7.5 km/s) is ignored.

    Parameters
    ----------
    pos_km   : (N, 3) positions in km, EME2000/GCRS, geocentric
    t        : Time, shape (N,)
    location : EarthLocation of the antenna

    Returns
    -------
    altaz : AltAz SkyCoord-like frame, shape (N,), with .distance = slant range
    icrs  : SkyCoord (ICRS), shape (N,), J2000-equivalent direction, no distance
    """
    geo = GCRS(CartesianRepresentation(pos_km.T * u.km), obstime=t)
    itrs_geo = geo.transform_to(ITRS(obstime=t))

    # topocentric ITRS: same axes, origin moved to the antenna
    topo_vec = itrs_geo.cartesian - location.get_itrs(t).cartesian
    itrs_topo = ITRS(topo_vec, obstime=t, location=location)

    aa_frame = AltAz(obstime=t, location=location)
    altaz = itrs_topo.transform_to(aa_frame)

    icrs = altaz_to_icrs(altaz.az, altaz.alt, t, location)
    return altaz, icrs


def altaz_to_icrs(az, alt, t, location):
    """
    Apparent az/el -> the "J2000-equivalent" ICRS direction, i.e. the catalogue
    position a star would need to have to appear exactly where the satellite does.

    Dropping the distance makes astropy treat it as a source at infinity, which puts
    back the annual + diurnal aberration a real target gets, so separations against a
    catalogue position are honest. Both the operator-ephemeris path and the local
    propagation fallback go through here, so "RA/Dec" means the same thing in both.

    az, alt may be Angle/Quantity or plain degrees.
    """
    if not isinstance(az, u.Quantity):
        az = np.asarray(az) * u.deg
    if not isinstance(alt, u.Quantity):
        alt = np.asarray(alt) * u.deg
    return SkyCoord(az=az, alt=alt, frame=AltAz(obstime=t, location=location)).icrs


def angular_separation_deg(az1_deg, el1_deg, az2_deg, el2_deg):
    """Angular separation (deg) between two az/el directions."""
    az1 = np.radians(az1_deg)
    el1 = np.radians(el1_deg)
    az2 = np.radians(az2_deg)
    el2 = np.radians(el2_deg)
    cos_sep = (
        np.sin(el1) * np.sin(el2)
        + np.cos(el1) * np.cos(el2) * np.cos(az1 - az2)
    )
    return np.degrees(np.arccos(np.clip(cos_sep, -1.0, 1.0)))


def contiguous_spans(mask, join=0):
    """(first, last) index pairs for each run of True in `mask`.

    Runs separated by `join` or fewer False samples are merged, which is how the fine
    pass avoids resampling the same seconds twice when two near approaches sit close
    enough together that their padding overlaps.
    """
    idx = np.flatnonzero(mask)
    if idx.size == 0:
        return []
    breaks = np.flatnonzero(np.diff(idx) > join + 1)
    starts = np.concatenate(([idx[0]], idx[breaks + 1]))
    ends = np.concatenate((idx[breaks], [idx[-1]]))
    return list(zip(starts.tolist(), ends.tolist()))


def find_nearby_satellites(SatCalc, all_sats, coarse_ts, beam_az, beam_el,
                           antenna_coords, search_radius_deg):
    """
    Coarse-pass filter: which satellites come within ``search_radius_deg`` of the beam.

    One satellite at a time, reducing each track to a separation and throwing the track
    away -- the whole active catalogue is ~13k satellites and holding every az/el/range
    array at once costs hundreds of MB for no gain (the propagation itself is only a few
    seconds).

    Unlike the version in sat_rfi/process_observation.py this takes the beam track as
    plain arrays rather than a pointing log, because here the beam is a fixed RA/Dec
    converted to az/el rather than something the telescope logged.

    Parameters
    ----------
    SatCalc : Satellite_Trajectory_Calculator
    all_sats : dict
        TLE dictionary from ``create_sat_data_dictionary_from_csv``.
    coarse_ts :
        skyfield time array to evaluate on.
    beam_az, beam_el : np.ndarray
        Beam az/el in degrees, same length as ``coarse_ts``.
    antenna_coords :
        wgs84 object from ``SatCalc.instantiate_antenna_coords``.
    search_radius_deg : float
        Cone half-angle. Pass the *inflated* radius; the caller trims back to the real
        FOV in the fine pass.

    Returns
    -------
    dict
        ``{name: (record, in_cone_mask)}`` for satellites that enter the cone.
        ``in_cone_mask`` indexes ``coarse_ts`` and tells the fine pass which stretches
        of the window are worth resampling.
    """
    nearby = {}
    n_failed = 0
    n_absurd = 0

    for name, record in all_sats.items():
        try:
            azels, _, ranges, _ = SatCalc.get_satellite_track(
                coarse_ts, record, antenna_coords)
        except Exception:
            n_failed += 1          # decayed element, bad epoch, sgp4 blew up
            continue

        sat_az = np.asarray(azels)[:, 0]
        sat_el = np.asarray(azels)[:, 1]

        # SGP4 does not always flag a propagation that has gone off the rails, so check
        # the answer rather than trusting an error code.
        if not np.all(np.isfinite(sat_az)) or not np.all(np.isfinite(sat_el)):
            n_absurd += 1
            continue
        if np.nanmax(np.asarray(ranges)) / 1e3 > MAX_PLAUSIBLE_RANGE_KM:
            n_absurd += 1
            continue

        above = sat_el > 0.0
        if not above.any():
            continue

        sep = np.full(sat_el.shape, np.inf)
        sep[above] = angular_separation_deg(
            beam_az[above], beam_el[above], sat_az[above], sat_el[above]
        )
        in_cone = sep <= search_radius_deg
        if in_cone.any():
            nearby[name] = (record, in_cone)

    if n_failed or n_absurd:
        log.debug("coarse pass: %d satellites failed to propagate, %d gave implausible "
                  "positions", n_failed, n_absurd)
    return nearby



# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------

class SatelliteInterceptGenerator(object):
    def __init__(self, opt):

        self.opt = opt

        self.out_dir = opt.out_dir if opt.out_dir is not None else os.getcwd()
        os.makedirs(self.out_dir, exist_ok=True)

        self.antenna = antennas[opt.antenna]
        c = self.antenna["coords_wgs84"]
        self.location = EarthLocation.from_geodetic(
            lon=c["lon"] * u.deg, lat=c["lat"] * u.deg, height=c["el"] * u.m
        )

        self.target = parse_radec(opt.obs_ra, opt.obs_dec)
        self.target_icrs = self.target.icrs
        self.radius = float(opt.radius)

        self.t_start = parse_utc(opt.start_time)
        if opt.end_time is not None:
            self.t_end = parse_utc(opt.end_time)
        else:
            self.t_end = self.t_start + opt.obs_len * u.s
        self.duration_s = (self.t_end - self.t_start).to_value(u.s)
        if self.duration_s <= 0:
            raise ValueError("observation end must be after start")

        # case-insensitive substring match against satellite names
        self.constellations = [s.lower() for s in (opt.constellations or [])]

    # -- coarse search ------------------------------------------------------

    def find_transits(self):
        if getattr(self.opt, "local", False):
            log.info("--local given; skipping SatChecker")
            return self.filter_constellations(self.local_fov_transits())

        # SatChecker only takes one constellation; pass it server-side when we
        # can, otherwise ask for everything and filter by name afterwards.
        sc_const = self.constellations[0] if len(self.constellations) == 1 else None
        try:
            transits = query_satchecker(
                self.target, self.t_start, self.duration_s, self.radius,
                self.location, constellation=sc_const,
            )
        except SatCheckerUnavailable as e:
            log.warning("SatChecker unavailable (%s); falling back to local propagation", e)
            transits = self.local_fov_transits()
        return self.filter_constellations(transits)

    # --

    def load_satellites(self):
        # load satellites from Celestrak if satchecker fails

        # An explicitly supplied catalogue wins: celestrak only serves *current*
        # elements, so a past observation can only be done from the file saved at
        # the time.
        if getattr(self.opt, "catalog", None):
            if not os.path.exists(self.opt.catalog):
                raise NoCatalog(f"no such catalog file: {self.opt.catalog}")
            log.info("using supplied catalog %s", self.opt.catalog)
            return self.opt.catalog

        request_time = datetime.fromtimestamp(time.time(), tz=timezone.utc)

        sats_file = Path(self.out_dir) / f"celestrak_satellites_ephemeris_{request_time.strftime('%Y%m%dT%H%M%S')}Z.csv"

        log.info("Accessing Celestrak database")

        try:
            with urllib.request.urlopen(CELESTRAK_URL, timeout=30) as resp:
                body = resp.read()
            # celestrak answers a too-soon repeat request with "GP data has not updated
            # since your last successful download..." -- usually a 403 (an OSError, caught
            # below), but cheap enough to check the body really is the catalogue.
            if not body.startswith(b"OBJECT_NAME,"):
                raise OSError(f"celestrak returned {body[:120].decode(errors='replace')!r}")
            sats_file.write_bytes(body)
            log.info("loaded satellites from celestrak")
        except OSError as e:
            # timestamped names sort chronologically -> newest is last
            saved = sorted(Path(self.out_dir).glob("celestrak_satellites_ephemeris_*.csv"))
            if not saved:
                raise NoCatalog(
                    f"celestrak would not serve the catalogue ({e}), there is no saved "
                    f"copy in {self.out_dir}, and no --catalog was given. Celestrak "
                    f"allows one download per group every two hours; pass --catalog with "
                    f"a CSV saved earlier (celestrak or space-track format both work)."
                ) from e
            sats_file = saved[-1]
            log.warning("failed to access celestrak (%s); using %s", e, sats_file)

        return str(sats_file)   # full path

    def local_fov_transits(self):
        """Local TLE propagation, for when SatChecker is unavailable.

        Builds the same {key: {"name", "norad_id", "positions": [{"julian_date", "ra",
        "dec", "angle", "altitude", "azimuth", ...}]}} shape SatChecker returns and hands
        it to transits_from_positions(), so everything downstream -- the Starlink
        refinement included -- can't tell the two apart except by `source`.

        Two passes: a cheap all-sky sweep in topocentric az/el over the whole catalogue
        (az/el because it needs no frame transforms), then a fine resampling in RA/Dec of
        only the handful of satellites that came close.
        """
        coarse_step = float(getattr(self.opt, "coarse_step", 1.0))
        fine_step = float(getattr(self.opt, "fine_step", 0.1))

        sats_file = self.load_satellites()
        SatCalc = Satellite_Trajectory_Calculator(self.out_dir)
        all_sats = SatCalc.create_sat_data_dictionary_from_csv(sats_file)
        log.info("loaded %d satellites from %s", len(all_sats), sats_file)

        # Matching names before propagating rather than afterwards in
        # filter_constellations() saves most of the work when you only want one
        # constellation.
        if self.constellations:
            all_sats = {n: r for n, r in all_sats.items()
                        if any(k in n.lower() for k in self.constellations)}
            log.info("%d satellites match %s", len(all_sats),
                     ",".join(self.constellations))
        if not all_sats:
            log.warning("no satellites to propagate")
            return []

        self.warn_if_stale(all_sats)

        c = self.antenna["coords_wgs84"]
        antenna_coords = SatCalc.instantiate_antenna_coords(c["lat"], c["lon"], c["el"])

        # Coarse grid over the observation, end inclusive.
        coarse_unix = np.arange(self.t_start.unix,
                                self.t_end.unix + coarse_step, coarse_step)
        coarse_unix = coarse_unix[coarse_unix <= self.t_end.unix + 1e-6]
        coarse_ts = SatCalc.ts.from_datetimes(
            [datetime.fromtimestamp(float(t), tz=timezone.utc) for t in coarse_unix])

        # Where the target sits in the sky, so the sweep can stay in az/el.
        beam = self.target_icrs.transform_to(AltAz(
            obstime=Time(coarse_unix, format="unix", scale="utc"),
            location=self.location))
        beam_az, beam_el = beam.az.deg, beam.alt.deg

        # A fast satellite can cross a small FOV entirely between two coarse samples, so
        # cast a wider net here and let the fine pass cut it back to the real radius.
        cone = self.radius + MAX_SKY_RATE_DEG_S * coarse_step
        log.info("coarse pass: %d satellites, %d steps of %g s, %.2f deg cone",
                 len(all_sats), len(coarse_unix), coarse_step, cone)

        nearby = find_nearby_satellites(SatCalc, all_sats, coarse_ts, beam_az, beam_el,
                                        antenna_coords, cone)
        log.info("coarse pass: %d candidate satellite(s) within %.2f deg", len(nearby), cone)

        sats = {}
        for name, (record, in_cone) in nearby.items():
            positions = self.refine_local_candidate(
                SatCalc, record, antenna_coords, coarse_unix, in_cone,
                coarse_step, fine_step)
            if not positions:
                log.debug("%s: inside the coarse cone but not the %.3f deg FOV",
                          name, self.radius)
                continue
            try:
                norad = int(record[0][1]["NORAD_CAT_ID"])
            except (KeyError, TypeError, ValueError):
                log.warning("%s: no NORAD id in the catalogue; skipping", name)
                continue
            sats[norad] = {"name": name, "norad_id": norad, "positions": positions}

        transits = transits_from_positions(
            sats, gap_s=max(1.0, 5 * fine_step), source="local")
        log.info("local propagation found %d transit(s)", len(transits))
        return transits

    def refine_local_candidate(self, SatCalc, record, antenna_coords, coarse_unix,
                               in_cone, coarse_step, fine_step, pad_s=2.0):
        """Resample one coarse candidate and keep the samples actually inside the FOV.

        Only the stretches where the coarse pass put the satellite inside the (inflated)
        cone get resampled, padded either side so the fine pass can't clip an entry or
        exit the coarse grid straddled.
        """
        # Spans whose padding would overlap are merged, so the fine grid has no repeats.
        join = int(np.ceil(2 * pad_s / coarse_step))
        grids = []
        for lo, hi in contiguous_spans(in_cone, join=join):
            t0 = max(coarse_unix[lo] - pad_s, self.t_start.unix)
            t1 = min(coarse_unix[hi] + pad_s, self.t_end.unix)
            n = int(np.floor((t1 - t0) / fine_step)) + 1
            grids.append(t0 + np.arange(n) * fine_step)
        if not grids:
            return []
        fine_unix = np.concatenate(grids)

        fine_ts = SatCalc.ts.from_datetimes(
            [datetime.fromtimestamp(float(t), tz=timezone.utc) for t in fine_unix])
        try:
            azels, _, ranges, _ = SatCalc.get_satellite_track(
                fine_ts, record, antenna_coords)
        except Exception as e:
            log.debug("fine pass failed (%s)", e)
            return []

        az = np.asarray(azels)[:, 0]
        el = np.asarray(azels)[:, 1]
        times = Time(fine_unix, format="unix", scale="utc")
        icrs = altaz_to_icrs(az, el, times, self.location)
        sep = self.target_icrs.separation(icrs).deg

        inside = np.flatnonzero((sep <= self.radius) & (el > 0.0))
        if inside.size == 0:
            return []

        jd = times.jd
        ra, dec = icrs.ra.deg, icrs.dec.deg
        rng_km = np.asarray(ranges) / 1e3
        return [{
            "julian_date": float(jd[i]),
            "ra": float(ra[i]),
            "dec": float(dec[i]),
            "angle": float(sep[i]),
            "azimuth": float(az[i]),
            "altitude": float(el[i]),
            "range_km": float(rng_km[i]),
        } for i in inside]

    def warn_if_stale(self, all_sats):
        """TLEs propagated far from their epoch are worthless, and nothing says so.

        SGP4 doesn't flag it -- a year-old starlink element happily reports a plausible
        az/el at a range of 6.5e12 km. find_nearby_satellites() throws those out, but the
        quieter case (elements a few weeks old, answers wrong by degrees) looks fine, so
        say how old the catalogue is relative to the observation.
        """
        epochs = []
        for record in all_sats.values():
            try:
                epochs.append(record[0][0].epoch.tt)
            except Exception:
                continue
        if not epochs:
            return
        age_days = float(np.median(np.asarray(epochs))) - self.t_start.tt.jd
        if abs(age_days) > STALE_TLE_WARN_DAYS:
            log.warning(
                "catalogue elements are a median %.1f days %s the observation -- SGP4 is "
                "not meaningful that far from epoch. Pass --catalog with elements from "
                "around %s.",
                abs(age_days), "after" if age_days > 0 else "before",
                self.t_start.isot)
        else:
            log.debug("catalogue elements are a median %.2f days from the observation",
                      age_days)

    def filter_constellations(self, transits):
        if not self.constellations:
            return transits
        return [t for t in transits
                if any(k in t.name.lower() for k in self.constellations)]

    # -- precise refinement -------------------------------------------------

    def refine_with_operator_ephemeris(self, transits, pad_s=30.0, step_s=0.01):
        """For satellites with a SpaceX-provided ephemeris, recompute the track
        through the FOV from it. Others (and any we can't cover) keep the coarse
        result.

        pad_s: the coarse (TLE-based) entry/exit times can be off by seconds, so
               search a padded window, clipped to the observation.
        """
        manifest = self.get_starlink_manifest()   # {norad_id: filename}
        refined = []

        for t in transits:
            fname = manifest.get(t.norad_id)
            if fname is None:
                log.info("%s (%d): no operator ephemeris, keeping %s result",
                         t.name, t.norad_id, t.source)
                refined.append(t)
                continue

            # filenames are versioned, so an existing copy is the same file
            path = os.path.join(self.out_dir, fname)
            if not os.path.exists(path):
                try:
                    urllib.request.urlretrieve(STARLINK_EPHEMERIDES_PATH + fname, path)
                except OSError as e:
                    log.warning("%s: couldn't fetch %s (%s); keeping coarse", t.name, fname, e)
                    refined.append(t)
                    continue

            meta, t_eph, states = parse_starlink(path)
            interp = build_interpolator(t_eph, states)
            log.debug("%s: %d states %s -> %s, interp err %.1f m", meta["object"], len(t_eph),
                      Time(t_eph[0], format="unix").isot, Time(t_eph[-1], format="unix").isot,
                      interpolation_error_km(t_eph, states) * 1e3)

            # Build the time grid as t0 + offsets rather than np.arange over JD:
            # a float64 JD only resolves ~40 us, and arange accumulates on top of that.
            t0 = max(Time(t.jd_start, format="jd", scale="utc") - pad_s * u.s, self.t_start)
            t1 = min(Time(t.jd_end, format="jd", scale="utc") + pad_s * u.s, self.t_end)
            n = int(np.floor((t1 - t0).to_value(u.s) / step_s)) + 1
            times = t0 + np.arange(n) * step_s * u.s

            # CubicHermiteSpline extrapolates silently, so check coverage ourselves.
            # The manifest only lists *current* files (~3 days ahead), so past
            # observations need ephemerides saved at the time.
            tu = times.unix   # same leap-second-free convention as parse_epoch()
            if tu[0] < t_eph[0] or tu[-1] > t_eph[-1]:
                log.warning("%s: ephemeris covers %s -> %s, not the window; keeping coarse",
                            t.name, Time(t_eph[0], format="unix").isot,
                            Time(t_eph[-1], format="unix").isot)
                refined.append(t)
                continue

            altaz, icrs = eme2000_track(interp(tu), times, self.location)
            sep = self.target_icrs.separation(icrs).deg
            inside = np.flatnonzero(sep <= self.radius)
            if inside.size == 0:
                log.info("%s: operator ephemeris says it misses the FOV (min sep %.3f deg); dropping",
                         t.name, sep.min())
                continue

            jd = times.jd
            ra, dec = icrs.ra.deg, icrs.dec.deg
            az, el, rng = altaz.az.deg, altaz.alt.deg, altaz.distance.to_value(u.km)
            positions = [{
                "julian_date": float(jd[i]),
                "ra": float(ra[i]),
                "dec": float(dec[i]),
                "angle": float(sep[i]),
                "azimuth": float(az[i]),
                "altitude": float(el[i]),
                "range_km": float(rng[i]),
            } for i in inside]

            refined.extend(transits_from_positions(
                {t.norad_id: {"name": t.name, "norad_id": t.norad_id, "positions": positions}},
                gap_s=max(1.0, 5 * step_s), source="starlink",
            ))

        refined.sort(key=lambda tr: tr.jd_start)
        return refined

    def get_starlink_manifest(self):
        """Fetch the Starlink ephemeris manifest -> {norad_id: filename}.
        Falls back to the newest manifest already saved in out_dir."""

        request_time = datetime.fromtimestamp(time.time(), tz=timezone.utc)
        manifest_path = os.path.join(
            self.out_dir, f"Starlink_manifest_{request_time.strftime('%Y%m%dT%H%M%S')}Z.txt")

        try:
            urllib.request.urlretrieve(STARLINK_EPHEMERIS_MANIFEST, manifest_path)
        except OSError as e:
            saved = sorted(Path(self.out_dir).glob("Starlink_manifest_*.txt"))
            if not saved:
                log.warning("couldn't fetch Starlink manifest (%s) and none saved", e)
                return {}
            manifest_path = str(saved[-1])
            log.warning("couldn't fetch Starlink manifest (%s); using %s", e, manifest_path)

        # MEME_<norad>_<name>_<...>.txt -- key on NORAD ID, which is what both
        # SatChecker and celestrak give us unambiguously
        sat_files = {}
        with open(manifest_path, "r") as fh:
            for line in fh:
                m = re.match(r"^MEME_(\d+)_", line.strip())
                if m:
                    sat_files[int(m.group(1))] = line.strip()
        return sat_files


    # -- output -------------------------------------------------------------

    # column header, width, right-align?
    _TABLE_COLS = {
        "utc_time":      ("UTC (closest approach)", 23, False),
        "name":          ("Name",                   20, False),
        "norad_id":      ("NORAD",                   6, True),
        "ra_j2000_deg":  ("RA J2000",               13, True),
        "dec_j2000_deg": ("Dec J2000",              13, True),
        "sep_deg":       ("Sep",                     7, True),
        "alt_deg":       ("El",                      7, True),
        "az_deg":        ("Az",                      7, True),
        "source":        ("Source",                 10, False),
    }

    def print_table(self, rows, fields, file=sys.stdout):
        """Fixed-width screen table. Angles in degrees. Long names are truncated."""
        def fmt(val, width, right):
            s = str(val)
            if len(s) > width:
                s = s[:width - 1] + "~"
            return s.rjust(width) if right else s.ljust(width)

        cols = [(f, *self._TABLE_COLS[f]) for f in fields]
        print("  ".join(fmt(h, w, r) for _, h, w, r in cols), file=file)
        print("  ".join("-" * w for _, _, w, _ in cols), file=file)
        for row in rows:
            print("  ".join(fmt(row[f], w, r) for f, _, w, r in cols), file=file)
        if not rows:
            print("(no transits)", file=file)

    def generate_target_list(self):
        transits = self.find_transits()
        transits = self.refine_with_operator_ephemeris(transits)

        rows = []
        for t in transits:
            p = t.closest
            if self.opt.hms:
                ra = self.ra_to_hms(p['ra'])
                dec = self.dec_to_dms(p['dec'])
            else:
                ra = f"{p['ra']:.5f}"
                dec = f"{p['dec']:.5f}"
            rows.append({
                "utc_time": Time(p["julian_date"], format="jd", scale="utc").isot,
                "name": t.name,
                "norad_id": t.norad_id,
                "ra_j2000_deg": ra,
                "dec_j2000_deg": dec,
                "sep_deg": f"{t.min_sep_deg:.4f}",
                "alt_deg": f"{p['altitude']:.3f}" if "altitude" in p else "",
                "az_deg": f"{p['azimuth']:.3f}" if "azimuth" in p else "",
                "source": t.source,
            })

        fname = os.path.join(
            self.out_dir,
            f"transits_{self.opt.antenna}_{self.t_start.strftime('%Y%m%dT%H%M%S')}.csv",
        )
        fields = ["utc_time", "name", "norad_id", "ra_j2000_deg", "dec_j2000_deg",
                  "sep_deg", "alt_deg", "az_deg", "source"]
        with open(fname, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(rows)

        self.print_table(rows, fields)
        log.info("%d transits written to %s", len(rows), fname)
        return transits

    def ra_to_hms(self, ra):

        hours = int(ra/15)
        mins = int((ra/15 - hours)*60)
        secs = ((ra/15 - hours)*60 - mins)*60

        return f"{hours}:{mins}:{secs:.4f}"

    def dec_to_dms(self, dec):

        degs = int(dec)
        mins = int((dec - degs)*60)
        secs = ((dec - degs)*60 - mins)*60

        return f"{degs}:{mins}:{secs:.4f}"


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def parse_utc(s):
    s = s.strip()
    if s.endswith(("Z", "z")):
        s = s[:-1]
    return Time(s, format="isot", scale="utc")


def parse_radec(ra, dec):
    """Decimal degrees, or sexagesimal (RA in hours) if it contains ':' or h/m/s."""
    if any(ch in ra for ch in ":hms"):
        return SkyCoord(ra, dec, unit=(u.hourangle, u.deg), frame="fk5", equinox="J2000")
    return SkyCoord(float(ra) * u.deg, float(dec) * u.deg, frame="fk5", equinox="J2000")


class Extend(argparse.Action):
    """Action to split comma-separated arguments and add to a list."""

    def __init__(self, option_strings, dest, type=None, **kwargs):
        if type is not None:
            itemtype = type
        else:

            def itemtype(s):
                return s

        def split_string_and_cast(s):
            return [itemtype(a.strip()) for a in s.strip().split(",")]

        super(Extend, self).__init__(
            option_strings, dest, type=split_string_and_cast, **kwargs
        )

    def __call__(self, parser, namespace, values, option_string=None):
        cur_list = getattr(namespace, self.dest, [])
        if cur_list is None:
            cur_list = []
        cur_list.extend(values)
        setattr(namespace, self.dest, cur_list)


def parse_command_line():
    scriptname = os.path.basename(sys.argv[0])

    formatter = argparse.RawDescriptionHelpFormatter(scriptname)
    width = formatter._width

    title = "Satellite Intercept Generator"
    copyright = "Copyright (c) 2026 Massachusetts Institute of Technology"
    shortdesc = "Generate times/coordinates for satellite intercepts near target RA/DEC observation location"
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
        "-ra",
        "--right_ascension",
        dest="obs_ra",
        type=str,
        required=True,
        help="""right ascension of observation. J2000 (deg, or hh:mm:ss)""",
    )
    parser.add_argument(
        "-dec",
        "--declination",
        dest="obs_dec",
        type=str,
        required=True,
        help="""declination of observation. J2000 (deg, or dd:mm:ss)""",
    )
    parser.add_argument(
        "-r",
        "--radius",
        dest="radius",
        type=float,
        required=True,
        help="""search radius around observation in decimal degrees""",
    )
    parser.add_argument(
        "-s",
        "--start",
        dest="start_time",
        type=str,
        required=True,
        help="""Start of observation window as UTC Time in ISO Format (e.g. 2025-06-24T00:25:43Z)""",
    )
    parser.add_argument(
        "-e",
        "--end",
        dest="end_time",
        type=str,
        default=None,
        help="""End of observation window as UTC Time in ISO Format (e.g. 2025-06-24T00:25:43Z)""",
    )
    parser.add_argument(
        "-l",
        "--obs_len",
        dest="obs_len",
        type=float,
        default=None,
        help="""length of observation window in seconds""",
    )
    parser.add_argument(
        "-c",
        "--constellations",
        dest="constellations",
        action=Extend,
        default=None,
        help="""satellite constellation or list of satellite constrellations to match from satellite names database (default=None will just pick any satellite but means uninteresting ones will likely be caught)""",
    )
    parser.add_argument(
        "-a",
        "--antenna",
        dest="antenna",
        type=str,
        default="bigdish",
        choices=sorted(antennas.keys()),
        help="""antenna to calculate from""",
    )
    parser.add_argument(
        "-o",
        "--out",
        dest="out_dir",
        type=str,
        default=None,
        help="""Where should I put output files? (default: cwd)""",
    )
    parser.add_argument(
        "-hms",
        "--oldunits",
        dest="hms",
        action="store_true",
        default=False,
        help="""return in h:m:s and d:m:s instead of decimal""",
    )
    parser.add_argument(
        "--catalog",
        dest="catalog",
        type=str,
        default=None,
        help="""saved celestrak CSV to propagate instead of downloading one. celestrak
                only serves current elements and only lets you fetch every couple of
                hours, so a past observation needs the catalogue saved at the time.""",
    )
    parser.add_argument(
        "--local",
        dest="local",
        action="store_true",
        default=False,
        help="""skip satchecker and go straight to the local calculation""",
    )
    parser.add_argument(
        "--coarse-step",
        dest="coarse_step",
        type=float,
        default=1.0,
        help="""time resolution in seconds of the local all-sky search (default 1.0)""",
    )
    parser.add_argument(
        "--fine-step",
        dest="fine_step",
        type=float,
        default=0.1,
        help="""time resolution in seconds of the local per-candidate refinement
                (default 0.1)""",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="""debug logging""",
    )

    options = parser.parse_args()

    if (options.end_time is None) == (options.obs_len is None):
        parser.error("give exactly one of --end or --obs_len")

    return options


if __name__ == "__main__":
    """
    Needed to add main function to use outside functions outside of module.
    """

    # Parse the Command Line for configuration
    options = parse_command_line()
    logging.basicConfig(
        level=logging.DEBUG if options.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )

    generator = SatelliteInterceptGenerator(options)
    try:
        generator.generate_target_list()
    except NoCatalog as e:
        # Celestrak only serves one download per group every couple of hours, so this
        # is a routine thing to hit rather than a crash worth a traceback.
        log.error("%s", e)
        sys.exit(1)