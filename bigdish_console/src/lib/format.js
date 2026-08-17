// Parsing and formatting of angles for the coordinate entry fields and readouts.

// Parse an angle entered by the operator, returning degrees or null if unparseable.
//
// Accepted forms:
//   "12.5"                        decimal degrees (always degrees, even for RA)
//   "12:34:56.7" / "12 34 56.7"   sexagesimal; hours for RA fields, degrees otherwise
//   "12h34m56.7s"                 hours (RA style)
//   "-5d 30m 15s" / "12d34'56\""  sexagesimal degrees
// Seconds and minutes may be omitted ("12:34", "12h").
export function parseAngle(text, { raHours = false } = {}) {
    if (typeof text === "number") {
        return Number.isFinite(text) ? text : null;
    }
    const trimmed = text.trim().toLowerCase();
    if (trimmed === "") {
        return null;
    }

    // Plain decimal number: degrees.
    if (/^[+-]?(\d+\.?\d*|\.\d+)$/.test(trimmed)) {
        return parseFloat(trimmed);
    }

    // Sexagesimal. Explicit h/m/s markers force hours; explicit d marker forces degrees;
    // bare "a:b:c" or "a b c" is hours for RA fields and degrees otherwise.
    const match = trimmed.match(
        /^([+-])?\s*(\d+\.?\d*)\s*(h|d|°|:|\s|$)\s*(?:(\d+\.?\d*)\s*(m|'|′|:|\s|$)\s*)?(?:(\d+\.?\d*)\s*(s|"|″)?\s*)?$/,
    );
    if (!match) {
        return null;
    }
    const sign = match[1] === "-" ? -1 : 1;
    const first = parseFloat(match[2]);
    const minutes = match[4] !== undefined ? parseFloat(match[4]) : 0;
    const seconds = match[6] !== undefined ? parseFloat(match[6]) : 0;
    if (minutes >= 60 || seconds >= 60) {
        return null;
    }

    const isHours = match[3] === "h" || (raHours && match[3] !== "d" && match[3] !== "°");
    const value = sign * (first + minutes / 60 + seconds / 3600);
    return isHours ? value * 15 : value;
}

export function formatDeg(value, digits = 2) {
    if (value === null || value === undefined || !Number.isFinite(value)) {
        return "---";
    }
    return value.toFixed(digits);
}

export function degToHMS(degrees) {
    if (!Number.isFinite(degrees)) {
        return "---";
    }
    const hoursTotal = (((degrees % 360) + 360) % 360) / 15;
    const h = Math.floor(hoursTotal);
    const m = Math.floor((hoursTotal - h) * 60);
    const s = ((hoursTotal - h) * 60 - m) * 60;
    return `${String(h).padStart(2, "0")}h${String(m).padStart(2, "0")}m${s.toFixed(1).padStart(4, "0")}s`;
}

export function degToDMS(degrees) {
    if (!Number.isFinite(degrees)) {
        return "---";
    }
    const sign = degrees < 0 ? "-" : "+";
    const abs = Math.abs(degrees);
    const d = Math.floor(abs);
    const m = Math.floor((abs - d) * 60);
    const s = ((abs - d) * 60 - m) * 60;
    return `${sign}${String(d).padStart(2, "0")}°${String(m).padStart(2, "0")}′${s.toFixed(0).padStart(2, "0")}″`;
}
