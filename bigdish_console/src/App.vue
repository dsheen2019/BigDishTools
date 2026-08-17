<script setup>
    import { reactive, ref, computed, watchEffect, onUnmounted } from 'vue';
    import { DishClient } from '@client/bigdish_client.js';
    import { buildTargets, fetchTLE } from './lib/targets.js';
    import { isZeroOffset, offsetAzEl, offsetFixedPosition } from './lib/offset.js';
    import { fixedFrameAzEl, makeAzElFunction } from './lib/ephemeris.js';
    import LoginModal from './components/LoginModal.vue';
    import StatusPanel from './components/StatusPanel.vue';
    import CommandPanel from './components/CommandPanel.vue';
    import TargetPanel from './components/TargetPanel.vue';
    import OffsetPanel from './components/OffsetPanel.vue';
    import UsersPanel from './components/UsersPanel.vue';
    import MapView from './components/MapView.vue';
    import StarChart from './components/StarChart.vue';

    const props = defineProps(['config']);
    const config = props.config;
    const targets = buildTargets(config);

    const client = ref(null);
    const showLogin = ref(true);
    const loginError = ref('');
    const connecting = ref(false);
    const tab = ref('map');

    // Single source of truth the panels and charts render from.
    const store = reactive({
        state: 'DISCONNECTED',
        azel: null,      // {az, el, az_vel, el_vel}
        radec: null,     // {ra, dec}
        gal: null,       // {l, b}
        power: null,     // {az_voltage, az_current, el_voltage, el_current}
        activeCommand: null,
        commandedAzEl: null, // last az/el this console commanded (manual or strobe)
        strobe: null,        // {name, active, az, el, up, onSourceAz, onSourceEl, error}
        // Pointing offset added to every pointing command; see lib/offset.js.
        offset: { frame: 'azel', coord1: 0, coord2: 0 },
        // {name, spec} of the target whose sky path the map and star chart draw: whichever
        // one the target dropdown has selected, or is being tracked.
        focus: null,
        theme: 'dark',   // 'dark' | 'light', mirrored here for the charts to watch
        lastError: '',
    });

    // Coordinate-entry fields, shared so the map and star chart can fill them on click.
    const entry = reactive({ frame: 'azel', coord1: '', coord2: '' });

    // Light or dark, following the operator's system preference until they choose. The map
    // keeps its own colours either way; the star chart flips with the theme.
    const theme = ref(localStorage.getItem('theme')
        ?? (window.matchMedia?.('(prefers-color-scheme: light)').matches ? 'light' : 'dark'));

    watchEffect(() => {
        document.documentElement.dataset.theme = theme.value;
        store.theme = theme.value;
    });

    function toggleTheme() {
        theme.value = theme.value === 'dark' ? 'light' : 'dark';
        localStorage.setItem('theme', theme.value);
    }

    // Something is following a moving target: either the server's own track or our strobe.
    const tracking = computed(() =>
        Boolean(store.strobe?.active || store.activeCommand?.type === 'track'));

    let posTimer = null;
    let commandTimer = null;
    let pollInFlight = false;

    function stopPolling() {
        clearInterval(posTimer);
        clearInterval(commandTimer);
        posTimer = null;
        commandTimer = null;
    }

    function startPolling() {
        stopPolling();
        posTimer = setInterval(async () => {
            if (!readable() || pollInFlight) return;
            pollInFlight = true;
            try {
                const d = await client.value.get_posvel(['azel', 'radec', 'gal'], true);
                if (d.success) {
                    store.azel = { az: d.az_pos, el: d.el_pos, az_vel: d.az_vel, el_vel: d.el_vel };
                    store.radec = { ra: d.ra_pos, dec: d.dec_pos };
                    store.gal = { l: d.l_pos, b: d.b_pos };
                    store.power = {
                        az_voltage: d.az_voltage, az_current: d.az_current,
                        el_voltage: d.el_voltage, el_current: d.el_current,
                    };
                }
            } catch { /* transient; connection loss is handled by onstatechange */ }
            finally { pollInFlight = false; }
        }, 1000 / config.status_poll_hz);

        commandTimer = setInterval(async () => {
            if (!readable()) return;
            try {
                const d = await client.value.get_active_movement_command();
                if (d.success !== false) {
                    // the server sends "command"; protocol.md says "active_command" -- accept both
                    store.activeCommand = d.command ?? d.active_command ?? null;
                }
            } catch { /* transient */ }
        }, 1000);
    }

    function readable() {
        return client.value && (store.state === 'AUTHENTICATED' || store.state === 'INITIALIZED');
    }

    async function connect({ host, port, user, password, control, kick }) {
        loginError.value = '';
        connecting.value = true;
        if (client.value) {
            client.value.close();
            client.value = null;
        }
        const c = new DishClient(host, port);
        c.onstatechange = (state) => {
            store.state = state;
            if (state === 'DISCONNECTED' && client.value === c) {
                stopStrobe('Connection to the dish server was lost.');
                stopPolling();
                loginError.value = 'Connection to the dish server was lost.';
                showLogin.value = true;
            }
        };
        try {
            await c.connect();
            const auth = await c.auth(user, password);
            if (!auth.success) {
                loginError.value = auth.reason || 'Authentication failed.';
                c.close();
                return;
            }
            if (control) {
                const init = await c.init(kick);
                if (!init.success) {
                    loginError.value = `${init.reason || 'Could not get dish control.'} You can retry with "kick other users", or connect for viewing only.`;
                    c.close();
                    return;
                }
            }
            client.value = c;
            showLogin.value = false;
            startPolling();
        } catch (error) {
            loginError.value = error.message;
            c.close();
        } finally {
            connecting.value = false;
        }
    }

    // --- strobe tracking (client-computed az/el targets: bodies, satellites) ---

    let worker = null;

    async function trackTarget(target) {
        lastRequest = { kind: 'strobe', target };
        return startStrobe(target);
    }

    async function startStrobe(target) {
        if (store.state !== 'INITIALIZED') {
            store.lastError = 'Dish control is required to track. Reconnect with control.';
            return;
        }
        stopStrobe();
        const spec = { ...target.spec };
        try {
            if (spec.type === 'satellite') {
                spec.tle = await fetchTLE(target.catnr, config.tle_max_age_hours);
            }
        } catch (error) {
            store.strobe = { name: target.name, active: false, error: error.message };
            return;
        }
        store.strobe = { name: target.name, active: true, az: null, el: null, up: null, error: '' };
        store.focus = { name: target.name, spec };
        worker = new Worker(new URL('./workers/strobe_worker.js', import.meta.url), { type: 'module' });
        worker.onmessage = async (event) => {
            const message = event.data;
            if (message.type === 'status') {
                if (store.strobe) {
                    Object.assign(store.strobe, {
                        az: message.az, el: message.el, up: message.up,
                        onSourceAz: message.on_source_az, onSourceEl: message.on_source_el,
                    });
                }
            } else if (message.type === 'command') {
                store.commandedAzEl = { az: message.az, el: message.el };
                try {
                    const response = await client.value.goto_posvel(
                        'azel', message.az, message.el, message.az_vel, message.el_vel);
                    if (!response.success) {
                        stopStrobe(`Tracking stopped: ${response.reason}`);
                    }
                } catch (error) {
                    stopStrobe(`Tracking stopped: ${error.message}`);
                }
            } else if (message.type === 'error') {
                stopStrobe(message.message);
            }
        };
        worker.postMessage({
            cmd: 'start',
            spec,
            site: config.site,
            // plain copy: the reactive store object cannot be structured-cloned
            offset: { ...store.offset },
            compute_interval_s: config.strobe.compute_interval_s,
            command_interval_s: config.strobe.command_interval_s,
        });
    }

    function stopStrobe(error = '') {
        if (worker) {
            worker.terminate();
            worker = null;
        }
        if (error && store.strobe) {
            store.strobe = { name: store.strobe.name, active: false, error };
        } else if (!error) {
            store.strobe = null;
        }
    }

    // --- commands from the panels ---

    // The last pointing request as the operator expressed it, before any offset, so that
    // changing the offset can re-point at the same target.
    let lastRequest = null; // {kind: 'command', command} | {kind: 'strobe', target}

    function sendCommand(command) {
        if (command.action === 'stow' || command.action === 'service') {
            lastRequest = null;
            return rawCommand(command);
        }
        lastRequest = { kind: 'command', command };
        return issueCommand(command);
    }

    // Apply the pointing offset to a command, which may change how it has to be carried out
    // -- see the frame table in lib/offset.js.
    function issueCommand(command) {
        const offset = store.offset;
        const now = new Date();
        if (isZeroOffset(offset)) {
            return rawCommand(command);
        }
        if (command.frame === 'azel') {
            // No target motion to hand over: a track-frame offset falls back to the sky's
            // drift at this direction (see trackDirection in lib/offset.js).
            const p = offsetAzEl(command.coord1, command.coord2, offset, config.site, now);
            return rawCommand({ ...command, coord1: p.az, coord2: p.el });
        }
        const shifted = offsetFixedPosition(command.frame, command.coord1, command.coord2, offset);
        if (shifted) {
            // Still a fixed point on the sky, expressed in the offset's frame.
            return rawCommand({ ...command, ...shifted });
        }
        // An az/el or track offset on a sky target drifts across the sky as the source
        // moves, so the console computes az/el itself: once for a goto, continuously for a
        // track.
        const spec = {
            type: 'fixed',
            frame: command.frame,
            coord1: command.coord1,
            coord2: command.coord2,
        };
        if (command.action === 'goto') {
            const onSourceAt = makeAzElFunction(spec, config.site);
            const base = onSourceAt(now);
            const p = offsetAzEl(base.az, base.el, offset, config.site, now, onSourceAt);
            return rawCommand({ action: 'goto', frame: 'azel', coord1: p.az, coord2: p.el });
        }
        return startStrobe({
            name: `${command.frame === 'gal' ? 'l/b' : 'ra/dec'} `
                + `${command.coord1.toFixed(3)}, ${command.coord2.toFixed(3)}`,
            spec,
        });
    }

    // Stop whatever is tracking and hold position. There is no cancel message in the
    // protocol; any movement command preempts a running command, so a goto at the current
    // position both takes the track down and stops the dish where it is.
    async function stopTracking() {
        const wasTracking = tracking.value;
        stopStrobe();
        lastRequest = null;
        if (wasTracking && store.azel) {
            await rawCommand({
                action: 'goto', frame: 'azel', coord1: store.azel.az, coord2: store.azel.el,
            });
        }
        store.activeCommand = null;
    }

    // Called when the operator applies or clears the offset: re-point whatever is tracking
    // so the beam moves now, rather than waiting for the next command.
    function applyOffset() {
        if (!lastRequest || !(store.strobe?.active || store.activeCommand?.type === 'track')) {
            return;
        }
        if (lastRequest.kind === 'strobe') {
            startStrobe(lastRequest.target);
        } else {
            issueCommand(lastRequest.command);
        }
    }

    async function rawCommand(command) {
        stopStrobe(); // a manual command always preempts client-side tracking
        store.lastError = '';
        try {
            let response;
            if (command.action === 'stow') {
                response = await client.value.stow_pos();
            } else if (command.action === 'service') {
                response = await client.value.service_pos();
            } else if (command.action === 'track') {
                response = await client.value.track(
                    command.frame, command.coord1, command.coord2, command.duration);
            } else {
                response = await client.value.goto_posvel(
                    command.frame, command.coord1, command.coord2,
                    command.vel1 ?? 0.0, command.vel2 ?? 0.0);
            }
            if (!response.success) {
                store.lastError = response.reason || `${command.action} command failed.`;
            } else if (command.frame === 'azel') {
                store.commandedAzEl = { az: command.coord1, el: command.coord2 };
            }
        } catch (error) {
            store.lastError = error.message;
        }
    }

    function setEntry(frame, coord1, coord2) {
        entry.frame = frame;
        if (coord1 !== null) entry.coord1 = coord1;
        if (coord2 !== null) entry.coord2 = coord2;
    }

    onUnmounted(() => {
        stopPolling();
        stopStrobe();
        if (client.value) client.value.close();
    });

    const stateLabel = {
        DISCONNECTED: 'offline',
        CONNECTED: 'connected',
        AUTHENTICATED: 'viewing',
        INITIALIZED: 'control',
    };
</script>

<template>
    <div id="console">
        <header>
            <h1>{{ config.site.name }}<span class="subtitle">control console</span></h1>
            <div class="header-state" :class="'state-' + store.state.toLowerCase()">
                <span class="lamp"></span>
                <span class="state-word">{{ stateLabel[store.state] }}</span>
            </div>
            <div class="header-actions">
                <button class="signal" :disabled="store.state !== 'INITIALIZED' || !tracking"
                        @click="stopTracking">Stop tracking</button>
                <button :disabled="store.state !== 'INITIALIZED'" @click="sendCommand({ action: 'stow' })">Stow</button>
                <button :disabled="store.state !== 'INITIALIZED'" @click="sendCommand({ action: 'service' })">Service</button>
                <button class="theme-toggle" @click="toggleTheme"
                        :title="`Switch to the ${theme === 'dark' ? 'light' : 'dark'} theme`"
                        :aria-label="`Switch to the ${theme === 'dark' ? 'light' : 'dark'} theme`">{{ theme === 'dark' ? '☀' : '☾' }}</button>
            </div>
        </header>

        <main>
            <aside>
                <StatusPanel :store="store" />
                <CommandPanel :store="store" :entry="entry" @command="sendCommand" />
                <TargetPanel :store="store" :targets="targets" :config="config"
                             @command="sendCommand" @start-strobe="trackTarget" @stop-strobe="stopStrobe" />
                <OffsetPanel :store="store" @apply="applyOffset" />
                <UsersPanel :client="client" :store="store" />
            </aside>

            <section class="chart-area panel">
                <div class="chart-tabs" role="tablist">
                    <button role="tab" :aria-selected="tab === 'map'" :class="{ active: tab === 'map' }" @click="tab = 'map'">Map</button>
                    <button role="tab" :aria-selected="tab === 'sky'" :class="{ active: tab === 'sky' }" @click="tab = 'sky'">Sky</button>
                </div>
                <MapView v-show="tab === 'map'" :store="store" :config="config" :targets="targets"
                         @set-azimuth="(az) => setEntry('azel', az.toFixed(2), null)" />
                <StarChart v-show="tab === 'sky'" :visible="tab === 'sky'" :store="store" :config="config"
                           @set-radec="(ra, dec) => setEntry('radec', ra.toFixed(3), dec.toFixed(3))" />
            </section>
        </main>

        <LoginModal v-if="showLogin" :config="config" :error-text="loginError" :busy="connecting" @connect="connect" />
    </div>
</template>

<style scoped>
    #console {
        height: 100%;
        display: flex;
        flex-direction: column;
        padding: 10px;
        gap: 10px;
    }

    header {
        display: flex;
        align-items: center;
        gap: 18px;
        padding: 0 4px;
    }

    h1 {
        font-family: var(--font-display);
        font-weight: 600;
        font-size: 24px;
        letter-spacing: 0.18em;
        text-transform: uppercase;
        margin: 0;
    }

    .subtitle {
        font-weight: 500;
        color: var(--muted);
        margin-left: 12px;
        letter-spacing: 0.22em;
        font-size: 16px;
    }

    .header-state {
        display: flex;
        align-items: center;
        gap: 7px;
        font-family: var(--font-display);
        letter-spacing: 0.14em;
        text-transform: uppercase;
        font-size: 14px;
        color: var(--muted);
    }

    .lamp {
        width: 9px;
        height: 9px;
        border-radius: 50%;
        background: #555;
    }

    .state-authenticated .lamp { background: #c9a83c; }
    .state-initialized .lamp { background: var(--accent); box-shadow: 0 0 6px var(--accent); }
    .state-initialized .state-word { color: var(--accent); }

    .header-actions {
        margin-left: auto;
        display: flex;
        gap: 8px;
    }

    .theme-toggle {
        /* the glyphs are not in the condensed display face */
        font-family: var(--font-body);
        font-size: 15px;
        line-height: 1;
        padding: 6px 10px;
        margin-left: 8px;
    }

    main {
        flex: 1;
        display: flex;
        gap: 10px;
        min-height: 0;
    }

    aside {
        /* Wide enough that the az/el readout in StatusPanel never wraps, which on a moving
         * dish would otherwise reflow line by line and read as a fault. Each axis needs
         * label 18 + gap 8 + 7ch at 26px (109) + gap 8 + 10ch at 11px (66) = 209 px, so two
         * of them with a 20 px gap need 438, plus the panel's 24 px padding and 2 px border.
         * IBM Plex Mono advances 0.6em, so those ch figures are exact. */
        width: 480px;
        flex-shrink: 0;
        display: flex;
        flex-direction: column;
        gap: 10px;
        overflow-y: auto;
    }

    .chart-area {
        flex: 1;
        display: flex;
        flex-direction: column;
        min-width: 0;
        position: relative;
    }

    .chart-tabs {
        display: flex;
        gap: 6px;
        margin-bottom: 8px;
    }

    .chart-tabs button {
        background: none;
        border: none;
        border-bottom: 2px solid transparent;
        border-radius: 0;
        color: var(--muted);
        padding: 2px 4px 4px;
        font-size: 15px;
    }

    .chart-tabs button.active {
        color: var(--text);
        border-bottom-color: var(--signal);
    }

    @media (max-width: 900px) {
        main { flex-direction: column; }
        aside { width: 100%; }
        .chart-area { min-height: 70vh; }
    }
</style>
