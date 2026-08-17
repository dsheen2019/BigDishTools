// JavaScript client library for the Big Dish control protocol, the browser counterpart to
// bigdish_client.py beside it. Written for the console UI in ../bigdish_console, which
// imports it as @client/bigdish_client.js, but it has no dependencies beyond WebSocket and is
// usable from any page or from Node 22+. The protocol is specified in protocol.md in the
// w1xm/BigDishControlServer repository, alongside the server itself.
//
// Derived from that repository's big-dish-web-client-vue/src/big_dish_client.js, restructured to
// use a single message dispatcher with per-request timeouts instead of one listener per
// request, and to fail all pending requests promptly when the connection drops.
//
// Every request resolves with the full decoded response message, including ones where the
// server reports "success": false -- callers check .success and .reason. Rejection is
// reserved for transport problems: timeouts and connection loss.

const RESPONSE_TIMEOUT_MS = 10000;
const PROTOCOL_VERSION = "0.1.0";

export class DishClient {
    constructor(host, port) {
        this.host = host;
        this.port = port;
        this.state = "DISCONNECTED";
        this.message_id = 0;
        this.pending = new Map(); // id -> {resolve, reject, timer}
        this.onstatechange = null; // optional callback(state)
        this.websocket = null;
    }

    _setState(state) {
        this.state = state;
        if (this.onstatechange) {
            this.onstatechange(state);
        }
    }

    connect() {
        this._setState("DISCONNECTED");
        this.websocket = new WebSocket(`ws://${this.host}:${this.port}`);

        this.websocket.addEventListener("message", (event) => {
            let decoded;
            try {
                decoded = JSON.parse(event.data);
            } catch {
                return;
            }
            const waiter = this.pending.get(decoded.id);
            if (waiter) {
                this.pending.delete(decoded.id);
                clearTimeout(waiter.timer);
                waiter.resolve(decoded);
            }
        });

        this.websocket.addEventListener("close", () => {
            this._failAllPending(new Error("Connection to the dish server closed."));
            this._setState("DISCONNECTED");
        });

        return new Promise((resolve, reject) => {
            this.websocket.addEventListener("open", () => {
                this._setState("CONNECTED");
                resolve();
            });
            this.websocket.addEventListener("error", () => {
                reject(new Error(`Cannot reach dish server at ${this.host}:${this.port}.`));
            });
        });
    }

    close() {
        if (this.websocket) {
            this.websocket.close();
        }
    }

    _failAllPending(error) {
        for (const waiter of this.pending.values()) {
            clearTimeout(waiter.timer);
            waiter.reject(error);
        }
        this.pending.clear();
    }

    _request(message) {
        const id = this.message_id++;
        message.id = id;
        return new Promise((resolve, reject) => {
            if (!this.websocket || this.websocket.readyState !== WebSocket.OPEN) {
                reject(new Error("Not connected to the dish server."));
                return;
            }
            const timer = setTimeout(() => {
                this.pending.delete(id);
                reject(new Error(`No response to "${message.type}" within ${RESPONSE_TIMEOUT_MS / 1000} s.`));
            }, RESPONSE_TIMEOUT_MS);
            this.pending.set(id, { resolve, reject, timer });
            this.websocket.send(JSON.stringify(message));
        });
    }

    async auth(user, password) {
        const response = await this._request({ type: "auth", user, password, version: PROTOCOL_VERSION });
        if (response.success) {
            this._setState("AUTHENTICATED");
        }
        return response;
    }

    async init(kick_others) {
        const response = await this._request({ type: "init", kick_others });
        if (response.success) {
            this._setState("INITIALIZED");
        }
        return response;
    }

    get_connections() {
        return this._request({ type: "get_connections" });
    }

    get_active_users() {
        return this._request({ type: "get_active_users" });
    }

    get_active_movement_command() {
        return this._request({ type: "get_active_movement_command" });
    }

    get_posvel(coords, power = false) {
        return this._request({ type: "get_posvel", coords, power });
    }

    get_offset() {
        return this._request({ type: "get_offset" });
    }

    set_offset(az_offset, el_offset) {
        return this._request({ type: "set_offset", az_offset, el_offset });
    }

    stow_pos() {
        return this._request({ type: "stow_pos" });
    }

    service_pos() {
        return this._request({ type: "service_pos" });
    }

    // frame is "azel", "radec", or "gal"; coord1/coord2 and vel1/vel2 are in the frame's
    // natural order (az/el, ra/dec, l/b), degrees and deg/s.
    goto_posvel(frame, coord1, coord2, vel1 = 0.0, vel2 = 0.0, executeat = null) {
        const message = { type: "goto_posvel", coords: frame, ...framePayload(frame, coord1, coord2, vel1, vel2) };
        if (executeat !== null) {
            message.executeat = executeat;
        }
        return this._request(message);
    }

    // Sustained server-side tracking; the server only supports moving frames here
    // ("radec" or "gal").
    track(frame, coord1, coord2, duration, vel1 = 0.0, vel2 = 0.0, executeat = null) {
        const message = { type: "track", coords: frame, duration, ...framePayload(frame, coord1, coord2, vel1, vel2) };
        if (executeat !== null) {
            message.executeat = executeat;
        }
        return this._request(message);
    }
}

const FRAME_KEYS = {
    azel: ["az", "el"],
    radec: ["ra", "dec"],
    gal: ["l", "b"],
};

function framePayload(frame, coord1, coord2, vel1, vel2) {
    const keys = FRAME_KEYS[frame];
    if (!keys) {
        throw new Error(`Unknown coordinate frame "${frame}".`);
    }
    return {
        [`${keys[0]}_pos`]: coord1,
        [`${keys[1]}_pos`]: coord2,
        [`${keys[0]}_vel`]: vel1,
        [`${keys[1]}_vel`]: vel2,
    };
}

export { FRAME_KEYS };
