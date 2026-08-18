// Recording the dish's position to a file, in the format WR66_log_position.py writes.
//
// It logs what the console is already asking the server for, rather than opening a second
// stream of requests: the status poll runs several times a second for the readouts, and every
// row here is one of those readings kept instead of discarded. That has one consequence worth
// knowing, which the panel says out loud: an interval finer than the poll period cannot be
// honoured, and one that is not a multiple of it gets rounded to the nearest that is.
//
// Rows accumulate until saved. At five a second an eight hour run is around 150000 of them,
// tens of megabytes, which is worth the simplicity of not streaming anywhere.

// Two decimal places short of what the server sends, matching the Python.
const DEGREES = 4;

export class PositionLog {
    constructor(pollPeriodSeconds) {
        this.pollPeriodSeconds = pollPeriodSeconds;
        this.reset();
    }

    reset() {
        this.rows = [];
        this.running = false;
        this.interval = this.pollPeriodSeconds;
        this.withPower = true;
        this.startedAt = null;
        this.lastRowAt = null;
        // stretches where readings stopped arriving: a gap in a log that looks continuous is
        // worse than a short log, so they are counted and reported rather than papered over
        this.gaps = [];
    }

    // The nearest interval that can actually be delivered, never shorter than one poll.
    snap(requestedSeconds) {
        const polls = Math.max(1, Math.round(requestedSeconds / this.pollPeriodSeconds));
        return Number((polls * this.pollPeriodSeconds).toFixed(6));
    }

    start(requestedSeconds, withPower = true) {
        this.reset();
        this.interval = this.snap(requestedSeconds);
        this.withPower = withPower;
        this.running = true;
        this.startedAt = Date.now() / 1000;
    }

    stop() {
        this.running = false;
    }

    // Offer one reading from the status poll. Kept if it is far enough past the last one.
    record(reading) {
        if (!this.running || !Number.isFinite(reading.az_pos)) {
            return false;
        }
        const time = Number.isFinite(reading.time) ? reading.time : Date.now() / 1000;
        if (this.lastRowAt !== null) {
            const since = time - this.lastRowAt;
            // half a poll of slack, so jitter in when the reply arrives does not drop rows
            if (since < this.interval - this.pollPeriodSeconds / 2) {
                return false;
            }
            if (since > this.interval * 2) {
                this.gaps.push({ from: this.lastRowAt, to: time });
            }
        }
        this.lastRowAt = time;
        this.rows.push({
            time,
            az: reading.az_pos, el: reading.el_pos,
            azVel: reading.az_vel, elVel: reading.el_vel,
            azVoltage: reading.az_voltage, elVoltage: reading.el_voltage,
            azCurrent: reading.az_current, elCurrent: reading.el_current,
        });
        return true;
    }

    get span() {
        if (this.rows.length < 2) return 0;
        return this.rows[this.rows.length - 1].time - this.rows[0].time;
    }

    get missingSeconds() {
        return this.gaps.reduce((total, gap) => total + (gap.to - gap.from), 0);
    }

    // The file itself. Same columns, same order and the same CRLF line endings as the Python,
    // so anything that reads one of those logs reads this without knowing the difference.
    toCsv() {
        const header = this.withPower
            ? "UTC, az, el, az vel, el vel, az volts, el volts, az amps, el amps"
            : "UTC, az, el, az vel, el vel";
        const lines = [header];
        for (const row of this.rows) {
            const stamp = new Date(row.time * 1000).toISOString().replace("Z", "") + "Z";
            const fields = [
                stamp,
                row.az.toFixed(DEGREES), row.el.toFixed(DEGREES),
                row.azVel.toFixed(DEGREES), row.elVel.toFixed(DEGREES),
            ];
            if (this.withPower) {
                fields.push(
                    String(row.azVoltage), String(row.elVoltage),
                    Number(row.azCurrent).toFixed(DEGREES), Number(row.elCurrent).toFixed(DEGREES));
            }
            lines.push(fields.join(", "));
        }
        return lines.join("\r\n") + "\r\n";
    }

    suggestedFilename() {
        const start = new Date((this.rows[0]?.time ?? Date.now() / 1000) * 1000);
        return `bigdish_position_${start.toISOString().slice(0, 19).replace(/[-:]/g, "")}.csv`;
    }
}
