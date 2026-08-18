// Reading a prepared pointing file: the csv WR66_run_pointing_file.py runs, and the format
// oem_to_bigdish_commands.py writes.
//
//     UTC in ISO form, frame, coordinate, coordinate [, rate, rate]
//     2026-04-04T03:54:20Z, azel, 127.891, 0.003, 0.000, 0.000
//
// The time on each row is when the dish should already be there, not when to start moving.
//
// Every check the Python makes is made here, for the same reason it makes them: this file is
// about to command a large piece of machinery, unattended, possibly for hours. A row that is
// wrong in a way nobody notices until the dish is driving into a limit is the thing to avoid,
// so the whole file is checked before any of it runs, and a bad row is reported by number.

const FRAMES = ["azel", "gal", "radec"];
const MIN_ELEVATION = -3.0;      // matching the Python's floor for azel commands
const MAX_RATE = 20.0;           // deg/s; the motor controllers enforce their own limits too

export function parsePointingFile(name, text) {
    const rows = [];
    const lines = text.split(/\r?\n/);

    for (let index = 0; index < lines.length; index++) {
        const line = lines[index].trim();
        if (!line || line.startsWith("#")) continue;
        const where = `${name} line ${index + 1}`;

        const fields = line.split(",").map((field) => field.trim());
        if (fields.length < 4) {
            throw new Error(
                `${where}: expected at least four fields (time, frame, two coordinates), got ${fields.length}.`);
        }

        const time = Date.parse(/[zZ]$|[+-]\d{2}:?\d{2}$/.test(fields[0])
            ? fields[0] : `${fields[0]}Z`);
        if (!Number.isFinite(time)) {
            throw new Error(`${where}: "${fields[0]}" is not a time this understands (use ISO, e.g. 2026-04-04T03:54:20Z).`);
        }

        const frame = fields[1].toLowerCase();
        if (!FRAMES.includes(frame)) {
            throw new Error(`${where}: "${fields[1]}" is not a frame; use ${FRAMES.join(", ")}.`);
        }

        const numbers = fields.slice(2).map(Number);
        if (numbers.some((value) => !Number.isFinite(value))) {
            throw new Error(`${where}: coordinates must be numbers, got "${fields.slice(2).join(", ")}".`);
        }
        const [coord1, coord2, vel1 = 0, vel2 = 0] = numbers;

        if (coord1 < 0 || coord1 > 360) {
            throw new Error(`${where}: first coordinate ${coord1} is outside 0 to 360 degrees.`);
        }
        if (Math.abs(coord2) > 90) {
            throw new Error(`${where}: second coordinate ${coord2} is outside plus or minus 90 degrees.`);
        }
        if (frame === "azel" && coord2 < MIN_ELEVATION) {
            throw new Error(`${where}: elevation ${coord2} is below ${MIN_ELEVATION} degrees.`);
        }
        if (Math.abs(vel1) > MAX_RATE || Math.abs(vel2) > MAX_RATE) {
            throw new Error(`${where}: rates ${vel1}, ${vel2} are beyond ${MAX_RATE} degrees a second.`);
        }

        // seconds from here on, matching what the rows carry: comparing the milliseconds
        // Date.parse returns against a row's seconds silently never fires
        const seconds = time / 1000;
        const previous = rows[rows.length - 1];
        if (previous && seconds < previous.time) {
            throw new Error(
                `${where}: goes backwards in time, to ${new Date(time).toISOString()} after `
                + `${new Date(previous.time * 1000).toISOString()}. Rows must be in order.`);
        }

        rows.push({ time: seconds, frame, coord1, coord2, vel1, vel2, line: index + 1 });
    }

    if (rows.length === 0) {
        throw new Error(`${name} has no command rows in it.`);
    }

    return {
        name,
        rows,
        // what the panel shows before anybody commits the dish to this
        summary: summarise(rows),
    };
}

function summarise(rows) {
    const first = rows[0];
    const last = rows[rows.length - 1];
    const frames = [...new Set(rows.map((row) => row.frame))];
    const gaps = rows.slice(1).map((row, index) => row.time - rows[index].time);
    const elevations = rows.filter((row) => row.frame === "azel").map((row) => row.coord2);

    return {
        count: rows.length,
        start: first.time,
        end: last.time,
        duration: last.time - first.time,
        frames,
        shortestGap: gaps.length ? Math.min(...gaps) : 0,
        longestGap: gaps.length ? Math.max(...gaps) : 0,
        lowestElevation: elevations.length ? Math.min(...elevations) : null,
    };
}

// Rows that have already come and gone by the time the file is loaded. A file prepared for
// this morning, opened this afternoon, would otherwise be handed to the server as a pile of
// commands whose executeat has passed, which is not obviously anything good.
export function rowsInThePast(file, now = Date.now() / 1000) {
    return file.rows.filter((row) => row.time < now).length;
}
