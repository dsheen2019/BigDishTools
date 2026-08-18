<script setup>
    import { computed } from 'vue';
    import { fixedNumber, degToHMS, degToDMS } from '../lib/format.js';
    import { isZeroOffset, describeOffset } from '../lib/offset.js';

    const props = defineProps(['store']);

    const offsetActive = computed(() => !isZeroOffset(props.store.offset));

    // How each quantity is written. Every figure on a line is the same width whatever the
    // reading, so the only thing that moves in this panel is the digits themselves.
    const LONGITUDE = { digits: 3, decimals: 2, sign: 'none' };    // 0 to 360: az, ra, l
    const LATITUDE = { digits: 2, decimals: 2 };                   // el, dec, b
    const RATE = { digits: 2, decimals: 3 };                       // deg/s, up to 30
    const VOLTS = { digits: 2, decimals: 1 };
    const AMPS = { digits: 2, decimals: 2, sign: 'always' };       // read for direction

    const num = (value, options) => fixedNumber(value, options);
</script>

<template>
    <div class="panel">
        <h2 class="panel-title">Position</h2>
        <!-- Two columns, one per axis, each field labelled beside itself. Everything below
             the headline is on the same grid, so az, ra, l and the volts start at the same
             place down the panel, as do el, dec, b and their amps. -->
        <div class="readout data">
            <div class="field big">
                <span class="key">az</span>
                <span class="value">{{ num(store.azel?.az, LONGITUDE) }}<span class="unit">°</span></span>
            </div>
            <div class="field big">
                <span class="key">el</span>
                <span class="value">{{ num(store.azel?.el, LATITUDE) }}<span class="unit">°</span></span>
            </div>

            <div class="field">
                <span class="key">az vel</span>
                <span class="value">{{ num(store.azel?.az_vel, RATE) }}<span class="unit">°/s</span></span>
            </div>
            <div class="field">
                <span class="key">el vel</span>
                <span class="value">{{ num(store.azel?.el_vel, RATE) }}<span class="unit">°/s</span></span>
            </div>

            <div class="field">
                <span class="key">ra</span>
                <span class="value">{{ num(store.radec?.ra, LONGITUDE) }}<span class="unit">°</span></span>
            </div>
            <div class="field">
                <span class="key">dec</span>
                <span class="value">{{ num(store.radec?.dec, LATITUDE) }}<span class="unit">°</span></span>
            </div>

            <!-- the same right ascension and declination in the units they are spoken in -->
            <div class="field">
                <span class="key"></span>
                <span class="value alt">{{ degToHMS(store.radec?.ra ?? NaN) }}</span>
            </div>
            <div class="field">
                <span class="key"></span>
                <span class="value alt">{{ degToDMS(store.radec?.dec ?? NaN) }}</span>
            </div>

            <div class="field">
                <span class="key">l</span>
                <span class="value">{{ num(store.gal?.l, LONGITUDE) }}<span class="unit">°</span></span>
            </div>
            <div class="field">
                <span class="key">b</span>
                <span class="value">{{ num(store.gal?.b, LATITUDE) }}<span class="unit">°</span></span>
            </div>

            <!-- the motors are here whether or not the server is sending power readings: a
                 line arriving mid-observation would shove everything below it down -->
            <div class="field" :class="{ hidden: !store.power }">
                <span class="key">az motor</span>
                <span class="value">{{ num(store.power?.az_voltage, VOLTS) }}<span class="unit">V</span>
                    {{ num(store.power?.az_current, AMPS) }}<span class="unit">A</span></span>
            </div>
            <div class="field" :class="{ hidden: !store.power }">
                <span class="key">el motor</span>
                <span class="value">{{ num(store.power?.el_voltage, VOLTS) }}<span class="unit">V</span>
                    {{ num(store.power?.el_current, AMPS) }}<span class="unit">A</span></span>
            </div>

            <div class="field wide" :class="{ hidden: !offsetActive }">
                <span class="key">offset</span>
                <span class="value offset">{{ offsetActive ? describeOffset(store.offset) : '\u2014' }}</span>
            </div>
        </div>

        <!-- A glance at what is queued and nothing more: which file, how long until it starts
             or how far through it is. The whole state, and the buttons for doing anything
             about it, are in the utilities tab. Live state only -- a file that has run its
             course belongs there too, not sitting here afterwards; a failure stays, since it
             wants attention. The line keeps its space either way, which is the point of
             queueing a file hours ahead: nothing should shift when it comes due. -->
        <p class="schedule reserve-1"
           :class="{ hidden: !['queued', 'running', 'failed'].includes(store.schedule?.state) }">
            <span class="one-line" :title="store.schedule?.text"
                  :class="store.schedule?.state === 'running' ? 'running' : ''">{{ store.schedule?.summary }}</span>
        </p>
        <!-- one line held for whatever goes wrong; the full text is in the tooltip -->
        <div class="messages reserve-1">
            <p v-if="store.strobe && !store.strobe.active && store.strobe.error"
               class="error-text one-line" :title="store.strobe.error">{{ store.strobe.error }}</p>
            <p v-else-if="store.lastError" class="error-text one-line" :title="store.lastError">{{ store.lastError }}</p>
        </div>
    </div>
</template>

<style scoped>
    /* Two columns of labelled fields, az on the left and el on the right the whole way down.
     * The label column is fixed so every value starts at the same place, and the values are
     * IBM Plex Mono with tabular figures at a width the formatter guarantees, so nothing in
     * here moves while the dish does. The sidebar width in App.vue is set to fit it. */
    .readout {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 2px 20px;
        margin-bottom: 10px;
    }

    .field {
        display: grid;
        grid-template-columns: 4.5rem auto;
        align-items: baseline;
        gap: 8px;
        white-space: nowrap;
    }

    .field.wide {
        grid-column: 1 / -1;
    }

    .key {
        font-family: var(--font-display);
        text-transform: uppercase;
        letter-spacing: 0.1em;
        color: var(--muted);
        font-size: 11px;
    }

    .value {
        font-size: 13px;
    }

    /* the headline pair, big enough to read from across the room */
    .big {
        align-items: baseline;
        margin-bottom: 4px;
    }

    .big .key {
        font-size: 14px;
    }

    .big .value {
        font-size: 26px;
        font-weight: 600;
    }

    .unit {
        color: var(--muted);
        font-weight: 400;
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
        /* so the ellipsis happens inside the line rather than the line growing */
        min-width: 0;
    }

    .schedule span {
        min-width: 0;
    }

    .schedule .running {
        color: var(--signal);
    }

    .messages {
        margin-top: 10px;
    }

    .messages p {
        margin: 0;
    }
</style>
