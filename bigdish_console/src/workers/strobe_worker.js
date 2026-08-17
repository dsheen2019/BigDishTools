// Tracking strobe loop for targets that move in az/el (solar-system bodies, satellites).
//
// Mirrors the approach of example_pointing_scripts/moon_tracker.py: a slow tick computes
// an accurate az/el + velocity solution, and a fast tick extrapolates it and emits a
// goto_posvel_azel command. Runs in a Web Worker because browsers throttle main-thread
// timers in background tabs, and a track must not stall because the operator switched
// windows. The websocket lives on the main thread; this worker only posts messages:
//
//   { type: "command", az, el, az_vel, el_vel }   -> main thread sends goto_posvel
//   { type: "status", az, el, up, on_source_* }   -> current solution, for display
//   { type: "error", message }                    -> fatal, strobing has stopped
//
// The start message may carry a pointing offset (see lib/offset.js), which is folded into
// the az/el solution on every compute tick.

import { makeAzElFunction, azElWithVelocity } from "../lib/ephemeris.js";
import { isZeroOffset, offsetAzEl } from "../lib/offset.js";

let computeTimer = null;
let commandTimer = null;

function stop() {
    clearInterval(computeTimer);
    clearInterval(commandTimer);
    computeTimer = null;
    commandTimer = null;
}

onmessage = (event) => {
    const message = event.data;
    if (message.cmd === "stop") {
        stop();
        return;
    }
    if (message.cmd !== "start") {
        return;
    }

    stop();
    const offset = message.offset;
    const offsetting = !isZeroOffset(offset);
    let onSourceAt;
    let azElAt;
    try {
        onSourceAt = makeAzElFunction(message.spec, message.site);
        // Offset inside the az/el function, so the finite difference in azElWithVelocity()
        // also picks up the rate at which the offset direction itself rotates (small, but
        // free). The unoffset function is passed along too: the track frame needs it to see
        // which way the target is going.
        azElAt = offsetting
            ? (date) => {
                const p = onSourceAt(date);
                return p && offsetAzEl(p.az, p.el, offset, message.site, date, onSourceAt);
            }
            : onSourceAt;
    } catch (error) {
        postMessage({ type: "error", message: String(error.message || error) });
        return;
    }

    let solution = null; // {computedAt, az, el, az_vel, el_vel}

    const computeTick = () => {
        const now = new Date();
        const result = azElWithVelocity(azElAt, now);
        if (!result) {
            stop();
            postMessage({ type: "error", message: "No position solution for target (satellite decayed or propagation failed)." });
            return;
        }
        solution = { computedAt: now.getTime(), ...result };
        // With an offset applied, report where the source itself is too, so the console can
        // show exactly how far off it the beam has been put.
        const onSource = offsetting ? onSourceAt(now) : null;
        postMessage({
            type: "status",
            az: result.az,
            el: result.el,
            up: result.el > 0,
            on_source_az: onSource?.az ?? null,
            on_source_el: onSource?.el ?? null,
        });
    };

    const commandTick = () => {
        if (!solution) {
            return;
        }
        if (solution.el <= 0) {
            // Below the horizon: report via status (computeTick) but never drive the dish
            // at the ground.
            return;
        }
        const dt = (Date.now() - solution.computedAt) / 1000;
        const az = (((solution.az + solution.az_vel * dt) % 360) + 360) % 360;
        const el = solution.el + solution.el_vel * dt;
        postMessage({ type: "command", az, el, az_vel: solution.az_vel, el_vel: solution.el_vel });
    };

    computeTick();
    computeTimer = setInterval(computeTick, message.compute_interval_s * 1000);
    commandTimer = setInterval(commandTick, message.command_interval_s * 1000);
};
