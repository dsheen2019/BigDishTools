// Running a prepared pointing file against the dish.
//
// Rows are handed to the server as track commands carrying executeat, the way
// WR66_run_pointing_file.py does, rather than by sleeping until each moment and firing then.
// The server holds a command until its time and applies it to the second; the console only has
// to deliver each row a little in advance. That is also what makes cancelling possible: at any
// moment only the next row or two has been committed, so stopping means not sending the rest.
//
// The states, and what the operator can do in each:
//
//   idle       nothing loaded
//   queued     a file is loaded and waiting for its first row. Ordinary commands still work;
//              the dish is nobody's but yours until the file starts.
//   running    rows are going out. Ordinary commands would fight the file, so the panel says
//              what is happening and offers cancelling instead.
//   finished   the last row has gone; the dish holds wherever it left off
//   cancelled  stopped by hand
//   failed     the connection was gone when the file was due to start, or a send failed

const LOOKAHEAD_S = 5;      // how far in advance a row is handed over
const TICK_MS = 500;
// A row whose moment has gone by more than this is skipped rather than sent. executeat in the
// past is not a command to point somewhere in the past -- it is a command to go there now, out
// of order, which for a file describing a moving target means chasing where it used to be.
// Rows fall behind when a file is queued late, or when the browser throttles a background tab.
const STALE_S = 3;

export class Schedule {
    // send(row, durationSeconds) delivers one row; hold() stops the dish where it is;
    // onStart() is called once when the file takes over, for zeroing the offset and standing
    // down anything else that was running.
    constructor({ send, hold, onStart, onState }) {
        this.send = send;
        this.hold = hold;
        this.onStart = onStart;
        this.onState = onState ?? (() => {});
        this.state = "idle";
        this.file = null;
        this.sent = 0;
        this.skipped = 0;
        this.message = "";
        this.timer = null;
        this.connected = true;
    }

    get startsAt() {
        return this.file ? this.file.rows[0].time : null;
    }

    get endsAt() {
        return this.file ? this.file.rows[this.file.rows.length - 1].time : null;
    }

    get remaining() {
        return this.file ? this.file.rows.length - this.sent : 0;
    }

    queue(file) {
        this.cancel({ quiet: true });
        this.file = file;
        this.sent = 0;
        this.skipped = 0;
        this.state = "queued";
        this.message = "";
        this.timer = setInterval(() => this.tick(), TICK_MS);
        this.onState();
    }

    // Told from outside whether the console still has a connection. A file that is only queued
    // is left alone: an outage that clears before its start time costs nothing, which is the
    // whole reason for not discarding it the moment the socket drops.
    setConnected(connected) {
        this.connected = connected;
        if (!connected && this.state === "running") {
            this.stop("failed", "The connection dropped while the file was running.");
        }
    }

    cancel({ quiet = false } = {}) {
        if (this.state === "running") {
            this.hold?.();
        }
        this.stop("cancelled", quiet ? "" : "Cancelled.");
    }

    stop(state, message) {
        clearInterval(this.timer);
        this.timer = null;
        if (state === "cancelled" && this.state === "idle") {
            return;   // nothing was loaded; do not announce a cancellation of nothing
        }
        this.state = state;
        this.message = message;
        this.onState();
    }

    async tick() {
        if (!this.file) return;
        const now = Date.now() / 1000;

        if (this.state === "queued") {
            if (now < this.startsAt - LOOKAHEAD_S) {
                this.onState();     // so the countdown moves
                return;
            }
            if (!this.connected) {
                this.stop("failed",
                    "The file was due to start, but there is no connection to the dish.");
                return;
            }
            this.state = "running";
            // Whatever offset somebody left applied is not part of this file: it starts from a
            // known state. Also stands down a strobe, since two things commanding at once is
            // nobody's idea of a good time.
            this.onStart?.();
            this.onState();
        }

        if (this.state !== "running") return;

        // hand over every row now within the lookahead, oldest first
        while (this.sent < this.file.rows.length
               && this.file.rows[this.sent].time - now <= LOOKAHEAD_S) {
            const row = this.file.rows[this.sent];
            const next = this.file.rows[this.sent + 1];
            // hold each row until the next is due, as the python does, so the dish is never
            // left without a command between rows
            const duration = next ? next.time - row.time + 1 : 1;
            this.sent++;

            if (row.time < now - STALE_S) {
                this.skipped++;
                continue;
            }
            try {
                const response = await this.send(row, duration);
                if (response && response.success === false) {
                    this.stop("failed", `Row ${row.line} was refused: ${response.reason ?? "no reason given"}.`);
                    return;
                }
            } catch (error) {
                this.stop("failed", `Row ${row.line} could not be sent: ${error.message}`);
                return;
            }
            this.onState();
        }

        if (this.sent >= this.file.rows.length && now > this.endsAt) {
            const ran = this.file.rows.length - this.skipped;
            this.stop("finished", this.skipped
                ? `Ran ${ran} of ${this.file.rows.length} rows; ${this.skipped} were already `
                  + "past by the time they came up and were skipped."
                : `Ran all ${this.file.rows.length} rows.`);
        }
    }

    describe() {
        const now = Date.now() / 1000;
        switch (this.state) {
            case "queued": {
                const wait = Math.max(0, this.startsAt - now);
                return `${this.file.name}: ${this.file.rows.length} rows, starts in ${formatWait(wait)}.`;
            }
            case "running": {
                const skipped = this.skipped ? `, ${this.skipped} skipped as stale` : "";
                return `${this.file.name}: row ${this.sent} of ${this.file.rows.length}${skipped}, `
                    + `${formatWait(Math.max(0, this.endsAt - now))} left.`;
            }
            case "finished":
            case "cancelled":
            case "failed":
                return `${this.file?.name ?? "Pointing file"}: ${this.message}`;
            default:
                return "";
        }
    }
}

export function formatWait(seconds) {
    if (seconds < 60) return `${Math.round(seconds)} s`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)} m ${Math.round(seconds % 60)} s`;
    return `${Math.floor(seconds / 3600)} h ${Math.round((seconds % 3600) / 60)} m`;
}
