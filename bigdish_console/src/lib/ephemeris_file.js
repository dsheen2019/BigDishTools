// Reading an ephemeris somebody hands you, rather than fetching elements for it.
//
// Three things arrive this way and two of them are the same thing underneath:
//
//   OMM, or a TLE          orbital elements, propagated with SGP4 like any satellite
//   CCSDS OEM              a table of state vectors, interpolated
//
// A state-vector table is not elements and cannot be given to SGP4: it is a prediction
// somebody else has already run, often a better one than SGP4 would give, since the operator
// knows about their own manoeuvres. So it becomes a target of its own kind, sampled by
// interpolating between the states -- see makeAzElFunction in ephemeris.js.
//
// Starlink's Modified ITC files are the same shape as an OEM with a different wrapper, and
// slot in here as another parser once wanted; see docs/utilities-tab.md.

const KM_PER_AU = 149597870.69098932;

export function readEphemerisFile(name, text) {
    const trimmed = text.trim();
    if (trimmed.startsWith("[") || trimmed.startsWith("{")) {
        return fromOmmJson(name, trimmed);
    }
    if (/^CCSDS_OEM_VERS/m.test(trimmed) || /^META_START/m.test(trimmed)) {
        return fromOem(name, trimmed);
    }
    if (/^1 \d{5}/m.test(trimmed) && /^2 \d{5}/m.test(trimmed)) {
        return fromTle(name, trimmed);
    }
    throw new Error(
        `${name} is not something this recognises: expected OMM (json), a TLE, or a CCSDS OEM `
        + "(.oem or .asc). It is read by what is in it rather than what it is called, so a "
        + "renamed file is fine and a mislabelled one is not.");
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

    return {
        name: object ?? name,
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
