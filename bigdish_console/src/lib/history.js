// Recent telemetry, kept so the diagnostics plots have something to draw.
//
// The console already asks the server for position, velocity and motor power several times a
// second and throws away everything but the latest reading. This keeps a window of them.
//
// App.vue records one reading a second (diagnostics.sample_seconds), rather than all of them:
// an hour of plot is about six seconds to the pixel, so the rest cannot be seen. Thinning to
// the width of the plot then happens when drawing, and takes the minimum and maximum of the
// samples in each column rather than their average, the way a waveform display does, so an
// excursion between gridlines still shows up as a spike.
//
// Nothing here is reactive: putting a window of samples behind a Vue proxy would cost far
// more than it helps, so the diagnostics tab redraws on its own timer instead.

export class TelemetryHistory {
    constructor(windowSeconds = 3600) {
        this.windowSeconds = windowSeconds;
        this.samples = [];
        // bumped on every change, so a component can tell there is something new without
        // comparing contents
        this.version = 0;
    }

    // sample: {time (unix seconds, as the server reported it), az, el, azError, elError,
    // azVoltage, azCurrent, elVoltage, elCurrent}. Any field may be null, which draws as a
    // gap rather than as zero: there is no error to plot until something has been commanded.
    push(sample) {
        const previous = this.samples[this.samples.length - 1];
        if (previous && sample.time < previous.time) {
            // the server's clock moved backwards, so the window would never expire again;
            // start over rather than keep samples that claim to be from the future
            this.samples = [];
        }
        this.samples.push(sample);

        const oldest = sample.time - this.windowSeconds;
        let drop = 0;
        while (drop < this.samples.length && this.samples[drop].time < oldest) {
            drop++;
        }
        // splice moves every remaining element, so dropping one sample at a time turns each
        // push into a walk of the whole window. Let them accumulate and drop them together;
        // the extra few seconds of history costs nothing and is clipped when drawn anyway.
        if (drop >= 64) {
            this.samples.splice(0, drop);
        }
        this.version++;
    }

    clear() {
        this.samples = [];
        this.version++;
    }

    get span() {
        if (this.samples.length === 0) {
            return null;
        }
        return { from: this.samples[0].time, to: this.samples[this.samples.length - 1].time };
    }

    // Whether anything in the window has a value for this field, so the tab can say "nothing
    // commanded yet" rather than drawing an empty box.
    has(field) {
        return this.samples.some((sample) => Number.isFinite(sample[field]));
    }

    // Thin one field into `columns` buckets between `from` and `to` (unix seconds). One entry
    // per occupied column: {x (0..1 across the span), min, max}. Empty columns are left out,
    // so a gap in the data stays a gap in the line.
    decimate(field, from, to, columns) {
        const span = to - from;
        if (!(span > 0) || columns < 1) {
            return [];
        }

        const buckets = new Array(columns).fill(null);
        for (const sample of this.samples) {
            const value = sample[field];
            if (!Number.isFinite(value) || sample.time < from || sample.time > to) {
                continue;
            }
            const index = Math.min(columns - 1, Math.floor(((sample.time - from) / span) * columns));
            const bucket = buckets[index];
            if (bucket === null) {
                buckets[index] = { x: (index + 0.5) / columns, min: value, max: value };
            } else {
                if (value < bucket.min) bucket.min = value;
                if (value > bucket.max) bucket.max = value;
            }
        }
        return buckets.filter((bucket) => bucket !== null);
    }

    // Smallest range covering the given fields over the window, with a little room added, for
    // the plots that are autoscaled rather than given fixed bounds. Null when there is
    // nothing to show.
    extent(fields, from, to) {
        let low = Infinity;
        let high = -Infinity;
        for (const sample of this.samples) {
            if (sample.time < from || sample.time > to) continue;
            for (const field of fields) {
                const value = sample[field];
                if (!Number.isFinite(value)) continue;
                if (value < low) low = value;
                if (value > high) high = value;
            }
        }
        if (low > high) {
            return null;
        }
        if (low === high) {
            // a flat line, which is what a healthy supply voltage looks like: give it room
            // rather than dividing by a zero-height range
            const margin = Math.max(Math.abs(low) * 0.05, 0.5);
            return { low: low - margin, high: high + margin };
        }
        const margin = (high - low) * 0.08;
        return { low: low - margin, high: high + margin };
    }
}
