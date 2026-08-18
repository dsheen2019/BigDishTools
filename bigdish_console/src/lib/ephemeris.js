// Client-side az/el computation for targets the server cannot track natively (its track
// command only understands radec/gal). Used by the strobe worker to drive the dish and by
// the UI for previews.
//
// Refraction is deliberately not applied, matching the server's coordinate conversions
// (astropy AltAz with no pressure) and the existing example_pointing_scripts.

import * as Astronomy from "astronomy-engine";
import * as satellite from "./satellite_shim.js";

// Build a function (date) => {az, el} (degrees) or null when no solution exists (e.g. a
// decayed satellite). spec comes from targets.js.
export function makeAzElFunction(spec, site) {
    if (spec.type === "fixed") {
        // A fixed celestial coordinate. The server can track these itself, so this is only
        // used when we have to drive one from here anyway -- see lib/offset.js.
        return (date) => fixedFrameAzEl(spec.frame, spec.coord1, spec.coord2, site, date);
    }

    if (spec.type === "ephemeris") {
        return makeStateVectorFunction(spec, site);
    }

    if (spec.type === "body") {
        const observer = new Astronomy.Observer(site.latitude, site.longitude, site.altitude_m);
        return (date) => {
            const eq = Astronomy.Equator(spec.body, date, observer, true, true);
            const hor = Astronomy.Horizon(date, observer, eq.ra, eq.dec);
            return { az: hor.azimuth, el: hor.altitude };
        };
    }

    if (spec.type === "satellite") {
        // OMM is what CelesTrak serves now and what the two-line format has been superseded
        // by; a TLE is still accepted, since a cached one or a hand-pasted one is still a
        // perfectly good set of elements.
        const satrec = spec.omm
            ? satellite.json2satrec(spec.omm)
            : satellite.twoline2satrec(spec.tle[0], spec.tle[1]);
        const observerGd = {
            latitude: satellite.degreesToRadians(site.latitude),
            longitude: satellite.degreesToRadians(site.longitude),
            height: site.altitude_m / 1000,
        };
        return (date) => {
            let eci;
            try {
                eci = satellite.propagate(satrec, date);
            } catch {
                return null;
            }
            if (!eci || !eci.position) {
                return null;
            }
            const ecf = satellite.eciToEcf(eci.position, satellite.gstime(date));
            const look = satellite.ecfToLookAngles(observerGd, ecf);
            return {
                az: satellite.radiansToDegrees(look.azimuth),
                el: satellite.radiansToDegrees(look.elevation),
            };
        };
    }

    throw new Error(`Unknown strobe target type "${spec.type}".`);
}

// Where to point at a table of state vectors: interpolate the orbit, subtract the observer,
// and rotate what is left into the horizontal frame.
//
// Interpolation is cubic Hermite, using the velocities the file gives alongside the positions.
// Straight lines between states would not do: at the sixty second spacing these files use, a
// satellite in low orbit departs from the chord by about four kilometres, which at a few
// hundred kilometres range is half a degree -- a fifth of the beamwidth, and worse than not
// pointing at all. With the velocities in hand the cubic is nearly exact and costs nothing.
function makeStateVectorFunction(spec, site) {
    const observer = new Astronomy.Observer(site.latitude, site.longitude, site.altitude_m);
    const { times, states, kmPerAu } = spec;

    return (date) => {
        const seconds = date.getTime() / 1000;
        if (seconds < times[0] || seconds > times[times.length - 1]) {
            return null;   // outside what the file covers; the caller reports it
        }

        // the interval containing this moment
        let low = 0;
        let high = times.length - 1;
        while (high - low > 1) {
            const middle = (low + high) >> 1;
            if (times[middle] <= seconds) low = middle;
            else high = middle;
        }

        const span = times[high] - times[low];
        const t = span > 0 ? (seconds - times[low]) / span : 0;
        const before = states[low];
        const after = states[high];

        // Hermite basis on the unit interval, with the velocities scaled by the span
        const t2 = t * t;
        const t3 = t2 * t;
        const h00 = 2 * t3 - 3 * t2 + 1;
        const h10 = t3 - 2 * t2 + t;
        const h01 = -2 * t3 + 3 * t2;
        const h11 = t3 - t2;

        const position = [0, 1, 2].map((axis) =>
            h00 * before[axis] + h10 * span * before[axis + 3]
            + h01 * after[axis] + h11 * span * after[axis + 3]);

        const time = Astronomy.MakeTime(date);
        const observerVector = Astronomy.ObserverVector(time, observer, false);
        const toSatellite = new Astronomy.Vector(
            position[0] / kmPerAu - observerVector.x,
            position[1] / kmPerAu - observerVector.y,
            position[2] / kmPerAu - observerVector.z,
            time);
        const horizontal = Astronomy.RotateVector(
            Astronomy.Rotation_EQJ_HOR(time, observer), toSatellite);
        const sphere = Astronomy.HorizonFromVector(horizontal, null);
        return { az: sphere.lon, el: sphere.lat };
    };
}

// Current az/el of a fixed celestial coordinate (J2000 ra/dec or galactic l/b, degrees).
// Used for display, and to point at one of these ourselves when an offset forces us to.
export function fixedFrameAzEl(frame, coord1, coord2, site, date) {
    const observer = new Astronomy.Observer(site.latitude, site.longitude, site.altitude_m);
    const time = Astronomy.MakeTime(date);
    let vec = Astronomy.VectorFromSphere(new Astronomy.Spherical(coord2, coord1, 1), time);
    if (frame === "gal") {
        vec = Astronomy.RotateVector(Astronomy.Rotation_GAL_EQJ(), vec);
    }
    const hor = Astronomy.RotateVector(Astronomy.Rotation_EQJ_HOR(time, observer), vec);
    const sph = Astronomy.HorizonFromVector(hor, null); // no refraction, matching the server
    return { az: sph.lon, el: sph.lat };
}

// The inverse: where a horizontal direction points on the sky, at a given instant.
export function azElToFixedFrame(frame, az, el, site, date) {
    const observer = new Astronomy.Observer(site.latitude, site.longitude, site.altitude_m);
    const time = Astronomy.MakeTime(date);
    const hor = Astronomy.VectorFromHorizon(new Astronomy.Spherical(el, az, 1), time, null);
    let vec = Astronomy.RotateVector(Astronomy.Rotation_HOR_EQJ(time, observer), hor);
    if (frame === "gal") {
        vec = Astronomy.RotateVector(Astronomy.Rotation_EQJ_GAL(), vec);
    }
    const sph = Astronomy.SphereFromVector(vec);
    return { coord1: ((sph.lon % 360) + 360) % 360, coord2: sph.lat };
}

// Convert between the two fixed celestial frames. The rotation itself does not depend on
// time; the AstroTime here only rides along inside the vector.
export function convertFixedFrame(fromFrame, coord1, coord2, toFrame) {
    if (fromFrame === toFrame) {
        return { coord1, coord2 };
    }
    const time = Astronomy.MakeTime(new Date());
    const vec = Astronomy.VectorFromSphere(new Astronomy.Spherical(coord2, coord1, 1), time);
    const rotation = fromFrame === "gal" ? Astronomy.Rotation_GAL_EQJ() : Astronomy.Rotation_EQJ_GAL();
    const sph = Astronomy.SphereFromVector(Astronomy.RotateVector(rotation, vec));
    return { coord1: ((sph.lon % 360) + 360) % 360, coord2: sph.lat };
}

// Position now plus az/el rates from a 1-second finite difference, wrap-aware in azimuth.
export function azElWithVelocity(azElAt, date) {
    const now = azElAt(date);
    if (!now) {
        return null;
    }
    const later = azElAt(new Date(date.getTime() + 1000));
    if (!later) {
        return { ...now, az_vel: 0, el_vel: 0 };
    }
    let dAz = later.az - now.az;
    if (dAz > 180) dAz -= 360;
    if (dAz < -180) dAz += 360;
    return { ...now, az_vel: dAz, el_vel: later.el - now.el };
}
