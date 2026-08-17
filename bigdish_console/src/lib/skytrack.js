// Where a target goes across the sky: the pass it is in now, or the next one, from rise to
// set, capped at max_hours for anything circumpolar.
//
// Everything comes through an az/el function, so solar-system bodies, satellites and fixed
// celestial coordinates are all handled by the same code -- see makeAzElFunction in
// ephemeris.js. The map draws the result as a polar sky plot and the star chart draws it in
// its own projection; both get the same samples from here.

// Coarse enough to be cheap over 24 hours, fine enough not to step over a two-minute
// satellite pass. Crossings found this way are then bisected to the second.
const SCAN_STEP_S = 30;
// How closely the drawn curve should follow the path.
const DEGREES_PER_SAMPLE = 0.5;

export function skyTrack(azElAt, now, options = {}) {
    const { max_hours: maxHours = 24, max_points: maxPoints = 500 } = options;
    const here = azElAt(now);
    if (!here) {
        return null;
    }

    const windowS = maxHours * 3600;
    const upNow = here.el > 0;
    let rise;
    let set;
    let circumpolar = false;

    if (upNow) {
        // Search a full max_hours each way: an arc can be long (the Crab is up for 15 hours
        // from Boston) and is still one rise-to-set pass. Only something that never sets
        // fails to find a crossing, and that gets max_hours centred on now instead.
        rise = scan(azElAt, now, -1, windowS);
        set = scan(azElAt, now, +1, windowS);
        circumpolar = rise === null && set === null;
        rise = rise ?? new Date(now.getTime() - (windowS / 2) * 1000);
        set = set ?? new Date(now.getTime() + (windowS / 2) * 1000);
    } else {
        rise = scan(azElAt, now, +1, maxHours * 3600);
        if (!rise) {
            return { points: [], up: false, rise: null, set: null, circumpolar: false };
        }
        // A second past the rise it is up, so the same scan finds the set.
        const justUp = new Date(rise.getTime() + 1000);
        const remainingS = maxHours * 3600 - (justUp - now) / 1000;
        set = scan(azElAt, justUp, +1, Math.max(60, remainingS))
            ?? new Date(justUp.getTime() + Math.max(60, remainingS) * 1000);
    }

    const spanS = (set - rise) / 1000;
    let step = DEGREES_PER_SAMPLE / Math.max(angularRate(azElAt, now), 1e-9);
    step = Math.min(Math.max(step, 1), spanS / 8);   // at least a handful of points
    step = Math.max(step, spanS / maxPoints);        // and never more than maxPoints

    const points = [];
    for (let t = 0; t < spanS; t += step) {
        const time = new Date(rise.getTime() + t * 1000);
        const p = azElAt(time);
        if (p) points.push({ time, az: p.az, el: p.el });
    }
    const last = azElAt(set);
    if (last) points.push({ time: set, az: last.az, el: last.el });

    const peak = points.reduce((best, p) => (p.el > best.el ? p : best), points[0]);
    return { points, up: upNow, rise, set, circumpolar, peak };
}

// Walk from `from` in the given direction until the elevation crosses the horizon, and
// return that moment; null if it does not cross within the limit.
function scan(azElAt, from, direction, limitSeconds) {
    const start = azElAt(from);
    if (!start) return null;
    const startUp = start.el > 0;

    let previous = from.getTime();
    for (let t = SCAN_STEP_S; t <= limitSeconds; t += SCAN_STEP_S) {
        const time = from.getTime() + direction * t * 1000;
        const p = azElAt(new Date(time));
        if (!p) return null;
        if ((p.el > 0) !== startUp) {
            return direction > 0
                ? bisectHorizon(azElAt, previous, time, startUp)
                : bisectHorizon(azElAt, time, previous, !startUp);
        }
        previous = time;
    }
    return null;
}

// Narrow the horizon crossing bracketed by two times, to under a second. upAtLow says which
// side of the horizon the earlier of the two is on.
function bisectHorizon(azElAt, lowMs, highMs, upAtLow) {
    for (let i = 0; i < 24 && highMs - lowMs > 500; i++) {
        const middle = (lowMs + highMs) / 2;
        const p = azElAt(new Date(middle));
        if (!p) break;
        if ((p.el > 0) === upAtLow) lowMs = middle;
        else highMs = middle;
    }
    return new Date((lowMs + highMs) / 2);
}

// How fast the target moves across the sky right now, in degrees per second.
export function angularRate(azElAt, now) {
    const a = azElAt(now);
    const b = azElAt(new Date(now.getTime() + 1000));
    if (!a || !b) return 0;
    const rad = (d) => (d * Math.PI) / 180;
    const cosine = Math.sin(rad(a.el)) * Math.sin(rad(b.el))
        + Math.cos(rad(a.el)) * Math.cos(rad(b.el)) * Math.cos(rad(a.az - b.az));
    return (Math.acos(Math.min(1, Math.max(-1, cosine))) * 180) / Math.PI;
}
