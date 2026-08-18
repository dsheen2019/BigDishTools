<script setup>
    import { computed } from 'vue';
    import { formatDeg, degToHMS, degToDMS } from '../lib/format.js';
    import { isZeroOffset, describeOffset } from '../lib/offset.js';

    const props = defineProps(['store']);
    const emit = defineEmits(['cancel-file']);

    const offsetActive = computed(() => !isZeroOffset(props.store.offset));

    const activeCommandText = computed(() => {
        const command = props.store.activeCommand;
        if (props.store.strobe?.active) {
            const s = props.store.strobe;
            const where = s.az !== null ? ` at az ${formatDeg(s.az, 1)}° el ${formatDeg(s.el, 1)}°` : '';
            return s.up === false
                ? `${s.name} is below the horizon${where}; waiting for it to rise.`
                : `Tracking ${s.name}${where} (console-computed).`;
        }
        if (!command) {
            return 'No movement command running.';
        }
        if (command.type === 'track') {
            const endsAt = (command.executeat ?? 0) + (command.duration ?? 0);
            const remaining = Math.max(0, Math.round(endsAt - Date.now() / 1000));
            return `Server tracking (${command.coords}), ${remaining} s remaining.`;
        }
        return `Running ${command.type} (${command.coords ?? ''}).`;
    });
</script>

<template>
    <div class="panel">
        <h2 class="panel-title">Position</h2>
        <div class="readout-main data">
            <div class="axis">
                <span class="axis-label">az</span>
                <span class="axis-value">{{ formatDeg(store.azel?.az) }}<span class="unit">°</span></span>
                <span class="axis-vel">{{ formatDeg(store.azel?.az_vel, 3) }}°/s</span>
            </div>
            <div class="axis">
                <span class="axis-label">el</span>
                <span class="axis-value">{{ formatDeg(store.azel?.el) }}<span class="unit">°</span></span>
                <span class="axis-vel">{{ formatDeg(store.azel?.el_vel, 3) }}°/s</span>
            </div>
        </div>
        <table class="frames data">
            <tbody>
                <tr>
                    <th>ra / dec</th>
                    <td><span class="figure">{{ formatDeg(store.radec?.ra, 3) }}°</span> <span class="alt">{{ degToHMS(store.radec?.ra ?? NaN) }}</span></td>
                    <td><span class="figure">{{ formatDeg(store.radec?.dec, 3) }}°</span> <span class="alt">{{ degToDMS(store.radec?.dec ?? NaN) }}</span></td>
                </tr>
                <tr>
                    <th>l / b</th>
                    <td><span class="figure">{{ formatDeg(store.gal?.l, 3) }}°</span></td>
                    <td><span class="figure">{{ formatDeg(store.gal?.b, 3) }}°</span></td>
                </tr>
                <tr v-if="store.power">
                    <th>motors</th>
                    <td><span class="figure-small">{{ formatDeg(store.power.az_voltage, 1) }}</span> V <span class="figure-small">{{ formatDeg(store.power.az_current, 2) }}</span> A</td>
                    <td><span class="figure-small">{{ formatDeg(store.power.el_voltage, 1) }}</span> V <span class="figure-small">{{ formatDeg(store.power.el_current, 2) }}</span> A</td>
                </tr>
                <tr v-if="offsetActive">
                    <th>offset</th>
                    <td colspan="2" class="offset">{{ describeOffset(store.offset) }}</td>
                </tr>
            </tbody>
        </table>
        <p class="active-command">{{ activeCommandText }}</p>
        <p v-if="store.schedule?.text" class="schedule">
            <span :class="store.schedule.state === 'running' ? 'running' : ''">{{ store.schedule.text }}</span>
            <button v-if="['queued', 'running'].includes(store.schedule.state)"
                    class="signal small" @click="emit('cancel-file')">Cancel</button>
        </p>
        <p v-if="store.strobe && !store.strobe.active && store.strobe.error" class="error-text">{{ store.strobe.error }}</p>
        <p v-if="store.lastError" class="error-text">{{ store.lastError }}</p>
    </div>
</template>

<style scoped>
    /* Az and el sit side by side and stay there: reflowing onto two lines as the digits
     * change looks like a fault on a moving dish. Every field below reserves the width of
     * its widest possible value in ch, which is exact here because the readout is IBM Plex
     * Mono with tabular figures, so the layout never moves while the numbers do. The
     * sidebar width in App.vue is set to fit the total. */
    .readout-main {
        display: flex;
        flex-wrap: nowrap;
        gap: 8px 20px;
        margin-bottom: 10px;
    }

    .axis {
        display: flex;
        align-items: baseline;
        gap: 8px;
        white-space: nowrap;
    }

    .axis-label {
        font-family: var(--font-display);
        text-transform: uppercase;
        letter-spacing: 0.1em;
        color: var(--muted);
        font-size: 14px;
    }

    .axis-value {
        font-size: 26px;
        font-weight: 600;
        /* "-90.00" plus the degree sign: the widest either axis can be. Right aligned, and
         * since the number of decimals never changes, that pins the decimal point and the
         * degree sign; only the leading digits grow, leftwards into the reserved space. */
        min-width: 7ch;
        text-align: right;
    }

    .unit {
        color: var(--muted);
        font-weight: 400;
    }

    .axis-vel {
        font-size: 11px;
        color: var(--muted);
        /* "-30.000°/s": the dish can manage 30 degrees a second, so allow the sign, five
         * digits and the unit */
        min-width: 10ch;
        text-align: right;
    }

    /* Fixed layout, or each column sizes itself to its widest content and the columns shove
     * each other sideways as the numbers change: ra crossing from 83.633 to 359.633 would
     * move the whole dec column. The width is spent deliberately instead. */
    .frames {
        width: 100%;
        table-layout: fixed;
        border-collapse: collapse;
        font-size: 12px;
    }

    .frames th {
        width: 5rem;
    }

    /* A slot wide enough for "-359.633°", right aligned, so the figure ends in the same place
     * whatever its magnitude and the hms/dms beside it never shifts. */
    .figure {
        display: inline-block;
        min-width: 9ch;
        text-align: right;
    }

    /* volts and amps: "-28.5", "-1.23" */
    .figure-small {
        display: inline-block;
        min-width: 5ch;
        text-align: right;
    }

    .frames th {
        font-family: var(--font-display);
        font-weight: 500;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        color: var(--muted);
        text-align: left;
        padding: 3px 8px 3px 0;
        white-space: nowrap;
    }

    .frames td {
        padding: 3px 8px 3px 0;
        white-space: nowrap;
    }

    .alt {
        color: var(--muted);
    }

    .offset {
        color: var(--signal);
    }

    .schedule {
        margin: 6px 0 0;
        font-size: 12px;
        color: var(--muted);
        display: flex;
        align-items: center;
        gap: 8px;
    }

    .schedule .running {
        color: var(--signal);
    }

    .schedule button.small {
        font-size: 11px;
        padding: 2px 8px;
    }

    .active-command {
        margin: 10px 0 0;
        font-size: 12px;
        color: var(--muted);
    }
</style>
