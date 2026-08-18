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

// Readout numbers of a fixed length: the same count of characters whatever the value, so a
// figure that runs 9.99 -> 10.00 -> 100.00 never changes width and nothing beside it moves.
// The digits before the point are zero filled to `digits`, which is chosen per quantity --
// three for the ones that run to 360, two for the rest.
//
// The sign is a column of its own rather than something that appears and disappears:
//   "none"     the quantity cannot be negative (azimuth, right ascension, galactic l)
//   "space"    a minus when negative, a space where the plus would be
//   "always"   an explicit + or -, for quantities read for their direction (motor current)
//
// A missing reading fills the same width with dashes, so a dropout does not shift the layout
// either. Values above the digit count are not truncated: better a readout that grows by a
// character than one that lies about where the dish is pointing.
export function fixedNumber(value, { digits = 3, decimals = 2, sign = "space" } = {}) {
    const width = digits + (decimals > 0 ? decimals + 1 : 0);
    if (value === null || value === undefined || !Number.isFinite(value)) {
        return (sign === "none" ? "" : " ") + "-".repeat(width);
    }
    // rounded first, so a value a hair below zero does not come out as "-00.00"
    const rounded = Number(value.toFixed(decimals));
    const body = Math.abs(rounded).toFixed(decimals).padStart(width, "0");
    if (sign === "none") {
        return body;
    }
    return (rounded < 0 ? "-" : sign === "always" ? "+" : " ") + body;
}

export function degToHMS(degrees) {
    if (!Number.isFinite(degrees)) {
        return "--h--m--.-s";   // the width of a real one, so a dropout moves nothing
    }
    // Rounded to the printed precision first, then carried, or a value a whisker short of
    // the wrap prints as 23h59m60.0s -- a time that does not exist.
    const TENTHS = 24 * 3600 * 10;
    const hoursTotal = (((degrees % 360) + 360) % 360) / 15;
    const tenths = Math.round(hoursTotal * 36000) % TENTHS;
    const h = Math.floor(tenths / 36000);
    const m = Math.floor((tenths % 36000) / 600);
    const s = (tenths % 600) / 10;
    return `${String(h).padStart(2, "0")}h${String(m).padStart(2, "0")}m${s.toFixed(1).padStart(4, "0")}s`;
}

export function degToDMS(degrees) {
    if (!Number.isFinite(degrees)) {
        return " --\u00b0--\u2032--\u2033";   // a space where the sign goes, as elsewhere
    }
    const sign = degrees < 0 ? "-" : "+";
    const seconds = Math.round(Math.abs(degrees) * 3600);
    const d = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = seconds % 60;
    return `${sign}${String(d).padStart(2, "0")}\u00b0${String(m).padStart(2, "0")}\u2032${String(s).padStart(2, "0")}\u2033`;
}
