// Pointing offsets: an angular nudge the operator adds to a pointing or tracking command,
// entered in whichever of the three frames is convenient. Useful for stepping across a
// source to find the beam center, or for parking the beam a known distance off-source.
//
// The offset goes into the commanded coordinates, not into the server's set_offset --
// protocol.md reserves that for feed/boresight corrections, which should persist across
// commands and belong to the dish rather than to one observation.
//
// In the three coordinate frames it is plain coordinate arithmetic: an offset of 1 degree
// in az moves the commanded azimuth by 1 degree, which up near the zenith is much less than
// 1 degree of beam travel. skySeparation() reports what the beam actually moves, so the
// panel can show both.
//
// The fourth frame, "track", is in true on-sky angle instead, measured against the
// direction the target is moving: Δ∥ leads or trails it along its own path, and Δ⊥ steps
// across that path. Both are exact rotations of the pointing direction, so 0.5 degrees is
// 0.5 degrees of beam travel wherever the dish is looking -- the frame to use for cutting
// across a source to find beam center.
//
// Which frame the offset is in decides how a command can be carried out:
//
//   sky target + sky offset (ra/dec or galactic)
//       still a fixed point on the sky, so the server can keep tracking it natively.
//   sky target + az/el or track offset
//       no longer fixed on the sky: the offset direction rotates as the source moves, so
//       the console has to compute az/el continuously and strobe it (App.vue does this).
//   az/el target (or a body/satellite) + any offset
//       applied to the az/el solution, either once for a goto or on every strobe tick.

import { wrap360 } from "./projection.js";
import { azElToFixedFrame, fixedFrameAzEl, convertFixedFrame } from "./ephemeris.js";

export const OFFSET_FRAMES = {
    azel: { label: "Az / El", c1: "Δaz", c2: "Δel" },
    radec: { label: "RA / Dec", c1: "Δra", c2: "Δdec" },
    gal: { label: "Galactic l / b", c1: "Δl", c2: "Δb" },
    track: { label: "Along / across track", c1: "Δ∥ along", c2: "Δ⊥ across" },
};

// The two frames that describe a point fixed on the sky, and so can be handed to the
// server's own track command.
const SKY_FRAMES = ["radec", "gal"];

export function isZeroOffset(offset) {
    return !offset || (!offset.coord1 && !offset.coord2);
}

// Add an offset to a spherical coordinate pair, carrying over the pole if the latitude-like
// component runs past it.
function addSpherical(lon, lat, offset) {
    let newLat = lat + offset.coord2;
    let newLon = lon + offset.coord1;
    if (newLat > 90) {
        newLat = 180 - newLat;
        newLon += 180;
    } else if (newLat < -90) {
        newLat = -180 - newLat;
        newLon += 180;
    }
    return { coord1: wrap360(newLon), coord2: newLat };
}

// --- true on-sky offsets against the direction of travel ---------------------------------
//
// Vectors are (east, north, up) triples -- right-handed, so a cross product means what it
// says geometrically. (The tempting (north, east, up) order is left-handed and silently
// negates every cross product.) The frame axes are then a right-handed triad in the order
//
//   1. the beam direction, radially outward
//   2. the direction of travel        (+Δ∥)
//   3. their cross product, 1 x 2     (+Δ⊥)
//
// which puts +Δ⊥ 90 degrees clockwise from the direction of travel as the operator sees it,
// looking out at the target: for something rising in the east, travel is up and to the
// right, and +Δ⊥ steps down and to the right (southward). The tests pin this down.

const rad = (d) => (d * Math.PI) / 180;
const deg = (r) => (r * 180) / Math.PI;

function azElToVector(az, el) {
    const cosEl = Math.cos(rad(el));
    return [cosEl * Math.sin(rad(az)), cosEl * Math.cos(rad(az)), Math.sin(rad(el))];
}

function vectorToAzEl(v) {
    return {
        az: wrap360(deg(Math.atan2(v[0], v[1]))),
        el: deg(Math.asin(Math.max(-1, Math.min(1, v[2])))),
    };
}

const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const cross = (a, b) => [
    a[1] * b[2] - a[2] * b[1],
    a[2] * b[0] - a[0] * b[2],
    a[0] * b[1] - a[1] * b[0],
];

function normalize(v) {
    const length = Math.hypot(v[0], v[1], v[2]);
    return length === 0 ? null : [v[0] / length, v[1] / length, v[2] / length];
}

// Rodrigues rotation of v about a unit axis.
function rotateAbout(v, axis, angleRad) {
    const c = Math.cos(angleRad);
    const s = Math.sin(angleRad);
    const cr = cross(axis, v);
    const d = dot(axis, v) * (1 - c);
    return [
        v[0] * c + cr[0] * s + axis[0] * d,
        v[1] * c + cr[1] * s + axis[1] * d,
        v[2] * c + cr[2] * s + axis[2] * d,
    ];
}

// Unit tangent vector along the target's apparent motion at this instant. azElAt is the
// target's own az/el function when we have one; without it the sky's diurnal drift at this
// direction is used, which is what a fixed celestial source there would do. Falls back to
// the direction of increasing azimuth for a target that is not moving at all (a
// geostationary satellite, say), so the frame is always defined.
function trackDirection(az, el, site, date, azElAt) {
    const sampleAt = azElAt
        ?? ((when) => {
            const sky = azElToFixedFrame("radec", az, el, site, date);
            return fixedFrameAzEl("radec", sky.coord1, sky.coord2, site, when);
        });
    const here = azElToVector(az, el);
    // A second is plenty for anything that moves visibly; a minute is the fallback for
    // sidereal-rate motion, where one second is still 1e-6 radians -- far above the noise
    // floor, but not by much.
    for (const seconds of [1, 60]) {
        const later = sampleAt(new Date(date.getTime() + seconds * 1000));
        if (!later) break;
        const there = azElToVector(later.az, later.el);
        // component of the later direction perpendicular to the current one
        const projection = dot(there, here);
        const perpendicular = [
            there[0] - projection * here[0],
            there[1] - projection * here[1],
            there[2] - projection * here[2],
        ];
        if (Math.hypot(...perpendicular) > 1e-12) {
            return normalize(perpendicular);
        }
    }
    return [Math.cos(rad(az)), -Math.sin(rad(az)), 0]; // stationary: increasing azimuth
}

// Offset a pointing direction by true angles along and across the target's motion.
function offsetAlongTrack(az, el, offset, site, date, azElAt) {
    const total = Math.hypot(offset.coord1, offset.coord2);
    if (total === 0) {
        return { az, el };
    }
    const here = azElToVector(az, el);
    const along = trackDirection(az, el, site, date, azElAt);
    const across = cross(here, along); // beam x travel: third axis of the right-handed triad
    const direction = [
        (offset.coord1 * along[0] + offset.coord2 * across[0]) / total,
        (offset.coord1 * along[1] + offset.coord2 * across[1]) / total,
        (offset.coord1 * along[2] + offset.coord2 * across[2]) / total,
    ];
    // Rotating about here x direction by total moves the beam exactly total degrees toward
    // direction, so the entered angles are on-sky angles by construction.
    return vectorToAzEl(rotateAbout(here, cross(here, direction), rad(total)));
}

// --- applying an offset ------------------------------------------------------------------

// Offset a fixed celestial position, returning coordinates in the offset's own frame so the
// server can still track them. Returns null for the az/el and track frames, which do not
// describe a fixed point on the sky -- those have to be strobed.
export function offsetFixedPosition(frame, coord1, coord2, offset) {
    if (!SKY_FRAMES.includes(offset.frame)) {
        return null;
    }
    const base = convertFixedFrame(frame, coord1, coord2, offset.frame);
    return { frame: offset.frame, ...addSpherical(base.coord1, base.coord2, offset) };
}

// Offset a horizontal direction, at a given instant. azElAt, when given, is the target's own
// az/el function, used by the track frame to find which way the target is moving.
export function offsetAzEl(az, el, offset, site, date, azElAt = null) {
    if (offset.frame === "track") {
        return offsetAlongTrack(az, el, offset, site, date, azElAt);
    }
    if (offset.frame === "azel") {
        const p = addSpherical(az, el, offset);
        return { az: p.coord1, el: p.coord2 };
    }
    const base = azElToFixedFrame(offset.frame, az, el, site, date);
    const shifted = addSpherical(base.coord1, base.coord2, offset);
    return fixedFrameAzEl(offset.frame, shifted.coord1, shifted.coord2, site, date);
}

// How far the beam actually moves. Track offsets are on-sky angles already; in the
// coordinate frames the longitude-like component shrinks by cos(latitude) of wherever the
// dish is pointing in that frame.
export function skySeparation(offset, latitudeDeg) {
    if (offset.frame === "track") {
        return Math.hypot(offset.coord1, offset.coord2);
    }
    const shrink = Math.cos(rad(latitudeDeg ?? 0));
    return Math.hypot(offset.coord1 * shrink, offset.coord2);
}

// The dish's current latitude-like coordinate in the offset's frame, for skySeparation().
export function currentLatitudeIn(frame, store) {
    if (frame === "track") return 0; // not needed: track offsets are already on-sky angles
    if (frame === "azel") return store.azel?.el;
    if (frame === "radec") return store.radec?.dec;
    return store.gal?.b;
}

export function describeOffset(offset) {
    const frame = OFFSET_FRAMES[offset.frame];
    // trim trailing zeros so a half-degree offset reads "0.5", not "0.500"
    const show = (v) =>
        `${v >= 0 ? "+" : "−"}${Math.abs(v).toFixed(3).replace(/\.?0+$/, "")}°`;
    return `${frame.c1} ${show(offset.coord1)}, ${frame.c2} ${show(offset.coord2)}`;
}
