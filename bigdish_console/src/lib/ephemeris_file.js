// Reading an ephemeris somebody hands you, rather than fetching elements for it.
//
// Four things arrive this way and they are two kinds underneath:
//
//   OMM, or a TLE          orbital elements, propagated with SGP4 like any satellite
//   CCSDS OEM              a table of state vectors, interpolated
//   Starlink text          the same table of state vectors in SpaceX's own wrapper
//
// A state-vector table is not elements and cannot be given to SGP4: it is a prediction
// somebody else has already run, often a better one than SGP4 would give, since the operator
// knows about their own manoeuvres. So it becomes a target of its own kind, sampled by
// interpolating between the states -- see makeAzElFunction in ephemeris.js.

const KM_PER_AU = 149597870.69098932;

export function readEphemerisFile(name, text) {
    const trimmed = text.trim();
    if (trimmed.startsWith("[") || trimmed.startsWith("{")) {
        return fromOmmJson(name, trimmed);
    }
    if (/^CCSDS_OEM_VERS/m.test(trimmed) || /^META_START/m.test(trimmed)) {
        return fromOem(name, trimmed);
    }
    if (/^\s*ephemeris_start\s*:/m.test(trimmed)) {
        return fromStarlink(name, trimmed);
    }
    if (/^1 \d{5}/m.test(trimmed) && /^2 \d{5}/m.test(trimmed)) {
        return fromTle(name, trimmed);
    }
    throw new Error(
        `${name} is not something this recognises: expected OMM (json), a TLE, a CCSDS OEM `
        + "(.oem or .asc), or a Starlink text ephemeris. It is read by what is in it rather "
        + "than what it is called, so a renamed file is fine and a mislabelled one is not.");
}

function fromOmmJson(name, text) {
    let parsed;
    try {
        parsed = JSON.parse(text);
    } catch (error) {
        throw new Error(`${name} is not valid JSON: ${error.message}`);
    }
    const omm = Array.isArray(parsed) ? parsed[0] : parsed;
    if (!omm || !Number.isFinite(omm.MEAN_MOTION)) {
        throw new Error(`${name} is JSON but does not carry orbital elements (no MEAN_MOTION).`);
    }
    return {
        name: omm.OBJECT_NAME ?? name,
        category: "Satellites (this session)",
        kind: "strobe",
        catnr: omm.NORAD_CAT_ID,
        spec: { type: "satellite", omm },
        temporary: true,
    };
}

function fromTle(name, text) {
    const lines = text.split("\n").map((line) => line.trimEnd());
    const first = lines.findIndex((line) => /^1 \d{5}/.test(line));
    const tle = [lines[first], lines[first + 1]];
    if (!/^2 \d{5}/.test(tle[1] ?? "")) {
        throw new Error(`${name} has a line 1 without a matching line 2.`);
    }
    // a 3LE carries the name above the elements
    const label = first > 0 && lines[first - 1].trim() ? lines[first - 1].trim() : name;
    return {
        name: label,
        category: "Satellites (this session)",
        kind: "strobe",
        catnr: Number.parseInt(tle[0].slice(2, 7), 10),
        spec: { type: "satellite", tle },
        temporary: true,
    };
}

// CCSDS OEM, key-value notation: a metadata block naming the frame and the object, then lines
// of "epoch x y z vx vy vz" in km and km/s. Covariance blocks, where present, are skipped.
function fromOem(name, text) {
    const lines = text.split("\n").map((line) => line.trim());
    let object = null;
    let frame = null;
    let inCovariance = false;
    const times = [];
    const states = [];

    for (const line of lines) {
        if (!line || line.startsWith("COMMENT")) continue;
        if (line.startsWith("COVARIANCE_START")) { inCovariance = true; continue; }
        if (line.startsWith("COVARIANCE_STOP")) { inCovariance = false; continue; }
        if (inCovariance) continue;

        const keyed = line.match(/^([A-Z_]+)\s*=\s*(.+)$/);
        if (keyed) {
            if (keyed[1] === "OBJECT_NAME") object = keyed[2].trim();
            if (keyed[1] === "REF_FRAME") frame = keyed[2].trim().toUpperCase();
            continue;
        }

        const parts = line.split(/[\s,]+/);
        if (parts.length < 7) continue;
        const time = Date.parse(parts[0].endsWith("Z") ? parts[0] : `${parts[0]}Z`);
        const values = parts.slice(1, 7).map(Number);
        if (!Number.isFinite(time) || values.some((value) => !Number.isFinite(value))) continue;
        times.push(time / 1000);
        states.push(values);
    }

    if (times.length < 2) {
        throw new Error(`${name} has ${times.length} usable state vectors; at least two are needed.`);
    }
    // EME2000, J2000 and GCRS differ by a frame bias of about 20 milliarcseconds, which is
    // four millionths of the dish's beamwidth. Anything else is worth refusing rather than
    // pointing confidently in the wrong place.
    if (frame && !["EME2000", "J2000", "ICRF", "GCRF", "GCRS", "MEME"].includes(frame)) {
        throw new Error(
            `${name} is in the ${frame} frame, which this cannot convert. `
            + "EME2000, J2000, ICRF, GCRF and MEME are understood.");
    }

    return stateVectorTarget(object ?? name, times, states);
}

// Starlink's own ephemeris format, one file per satellite: seventy-two hours of prediction
// refreshed every eight hours, mirrored at api.starlink.com/public-files/ephemerides/.
//
// Underneath it is an OEM by another name -- a table of state vectors in km and km/s -- so it
// ends up at the same sampler. The wrapper differs: four header lines, then records of a state
// vector followed by three lines holding the twenty-one terms of its covariance, which is of
// no use for pointing and is skipped. (The "UVW" header line names the frame that covariance
// is in, not the frame of the states themselves.)
//
// The states are in the frame the filename announces, MEME, which this reads as EQJ, the same
// as the OEM reader does. Worth checking rather than assuming, since mean equator and equinox
// *of date* is a quarter of a degree from J2000 by now, a tenth of the beam. Fitting the node
// of a 72-hour file back to the epoch of the same satellite's CelesTrak elements matches those
// elements to 0.0002 degrees if the states are first rotated from J2000 to the equator of
// date, and misses by half a degree if they are taken as being of-date already. So they are
// J2000, and go to the sampler unrotated like an OEM.
function fromStarlink(name, text) {
    const times = [];
    const states = [];

    for (const line of text.split("\n")) {
        const parts = line.trim().split(/\s+/);
        // A state vector begins with a YYYYDDDHHMMSS.sss epoch. The covariance lines under it
        // are seven numbers as well, but none of them can be mistaken for one of those.
        if (parts.length !== 7 || !/^\d{13}(\.\d+)?$/.test(parts[0])) continue;
        const time = starlinkEpoch(parts[0]);
        const values = parts.slice(1).map(Number);
        if (!Number.isFinite(time) || values.some((value) => !Number.isFinite(value))) continue;
        times.push(time);
        states.push(values);
    }

    if (times.length < 2) {
        throw new Error(
            `${name} looks like a Starlink ephemeris but holds ${times.length} usable state `
            + "vectors; at least two are needed.");
    }
    return stateVectorTarget(starlinkName(name), times, states);
}

// YYYYDDDHHMMSS.sss, in UTC, counting the day of the year rather than the month and the day.
// Returns seconds, or NaN for anything that is not a real instant, so the caller can drop it.
function starlinkEpoch(token) {
    const year = Number(token.slice(0, 4));
    const dayOfYear = Number(token.slice(4, 7));
    const hour = Number(token.slice(7, 9));
    const minute = Number(token.slice(9, 11));
    const second = Number(token.slice(11));   // seconds and their fraction together
    if (dayOfYear < 1 || dayOfYear > 366 || hour > 23 || minute > 59 || second >= 61) {
        return Number.NaN;
    }
    return Date.UTC(year, 0, 1) / 1000
        + (dayOfYear - 1) * 86400 + hour * 3600 + minute * 60 + second;
}

// Nothing inside the file says which satellite it is; the name is carried by the name of the
// file, as MEME_<catalog number>_<object>_<rest>.txt. A renamed file still reads fine and
// simply keeps whatever it was renamed to.
function starlinkName(name) {
    return name.match(/^MEME_\d+_([^_]+)_/i)?.[1] ?? name;
}

// The target a table of state vectors becomes, whichever file it arrived in.
function stateVectorTarget(name, times, states) {
    return {
        name,
        category: "Ephemerides (this session)",
        kind: "strobe",
        temporary: true,
        spec: {
            type: "ephemeris",
            // plain arrays: this crosses to the strobe worker by postMessage
            times,
            // km and km/s as the file gives them, converted where they are used
            states,
            kmPerAu: KM_PER_AU,
        },
    };
}
