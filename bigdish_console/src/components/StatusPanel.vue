<script setup>
    import { computed } from 'vue';
    import { formatDeg, degToHMS, degToDMS } from '../lib/format.js';
    import { isZeroOffset, describeOffset } from '../lib/offset.js';

    const props = defineProps(['store']);

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
                    <td>{{ formatDeg(store.radec?.ra, 3) }}° <span class="alt">{{ degToHMS(store.radec?.ra ?? NaN) }}</span></td>
                    <td>{{ formatDeg(store.radec?.dec, 3) }}° <span class="alt">{{ degToDMS(store.radec?.dec ?? NaN) }}</span></td>
                </tr>
                <tr>
                    <th>l / b</th>
                    <td>{{ formatDeg(store.gal?.l, 3) }}°</td>
                    <td>{{ formatDeg(store.gal?.b, 3) }}°</td>
                </tr>
                <tr v-if="store.power">
                    <th>motors</th>
                    <td>{{ formatDeg(store.power.az_voltage, 1) }} V {{ formatDeg(store.power.az_current, 2) }} A</td>
                    <td>{{ formatDeg(store.power.el_voltage, 1) }} V {{ formatDeg(store.power.el_current, 2) }} A</td>
                </tr>
                <tr v-if="offsetActive">
                    <th>offset</th>
                    <td colspan="2" class="offset">{{ describeOffset(store.offset) }}</td>
                </tr>
            </tbody>
        </table>
        <p class="active-command">{{ activeCommandText }}</p>
        <p v-if="store.strobe && !store.strobe.active && store.strobe.error" class="error-text">{{ store.strobe.error }}</p>
        <p v-if="store.lastError" class="error-text">{{ store.lastError }}</p>
    </div>
</template>

<style scoped>
    .readout-main {
        display: flex;
        flex-wrap: wrap; /* never clip: a too-wide readout drops to its own line instead */
        gap: 8px 24px;
        margin-bottom: 10px;
    }

    .axis {
        display: flex;
        align-items: baseline;
        gap: 8px;
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
    }

    .unit {
        color: var(--muted);
        font-weight: 400;
    }

    .axis-vel {
        font-size: 11px;
        color: var(--muted);
    }

    .frames {
        width: 100%;
        border-collapse: collapse;
        font-size: 12px;
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

    .active-command {
        margin: 10px 0 0;
        font-size: 12px;
        color: var(--muted);
    }
</style>
