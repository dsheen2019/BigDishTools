<script setup>
    // Pointing offset entry. The offset lives in store.offset and App.vue folds it into
    // every pointing command; see lib/offset.js for what each frame combination means.

    import { ref, computed, watch } from 'vue';
    import { parseAngle, formatDeg } from '../lib/format.js';
    import {
        OFFSET_FRAMES, isZeroOffset, skySeparation, currentLatitudeIn, describeOffset,
    } from '../lib/offset.js';

    const props = defineProps(['store']);
    const emit = defineEmits(['apply']);

    const frame = ref(props.store.offset.frame);
    const first = ref('0');
    const second = ref('0');
    const parseError = ref('');

    const labels = computed(() => OFFSET_FRAMES[frame.value]);
    const active = computed(() => !isZeroOffset(props.store.offset));
    const tracking = computed(() =>
        props.store.strobe?.active || props.store.activeCommand?.type === 'track');

    // What the beam actually moves, which for the longitude-like axis depends on where the
    // dish is pointing now.
    const separation = computed(() => {
        const offset = props.store.offset;
        const latitude = currentLatitudeIn(offset.frame, props.store);
        if (isZeroOffset(offset) || latitude === undefined || latitude === null) return null;
        return skySeparation(offset, latitude);
    });

    // An az/el or track offset on a sky target has to be strobed: say so up front.
    const strobeWarning = computed(() =>
        (frame.value === 'azel' || frame.value === 'track')
        && props.store.activeCommand?.type === 'track');

    // While the console is driving the track it knows where the source itself is, so it can
    // report exactly where the beam was put rather than a first-order estimate.
    const beamPlacement = computed(() => {
        const s = props.store.strobe;
        if (!s?.active || s.onSourceAz === null || s.onSourceAz === undefined) return null;
        const dAz = ((s.az - s.onSourceAz + 540) % 360) - 180;
        const dEl = s.el - s.onSourceEl;
        const onSky = skySeparation(
            { frame: 'azel', coord1: dAz, coord2: dEl }, (s.el + s.onSourceEl) / 2);
        return { dAz, dEl, onSky };
    });

    const signed = (value) => `${value >= 0 ? '+' : '−'}${formatDeg(Math.abs(value), 2)}°`;

    function apply() {
        const coord1 = parseAngle(first.value);
        const coord2 = parseAngle(second.value);
        if (coord1 === null || coord2 === null) {
            parseError.value = `Enter ${labels.value.c1} and ${labels.value.c2} in degrees `
                + '(0.5, 0:30:00 and 0d30m all mean half a degree).';
            return;
        }
        parseError.value = '';
        Object.assign(props.store.offset, { frame: frame.value, coord1, coord2 });
        emit('apply');
    }

    function clear() {
        first.value = '0';
        second.value = '0';
        parseError.value = '';
        Object.assign(props.store.offset, { coord1: 0, coord2: 0 });
        emit('apply');
    }

    // Switching frames while an offset is applied would silently reinterpret it, so the
    // fields go back to zero and the operator applies the new frame deliberately.
    watch(frame, () => {
        if (props.store.offset.frame !== frame.value) {
            first.value = '0';
            second.value = '0';
        }
    });
</script>

<template>
    <div class="panel">
        <h2 class="panel-title">
            Offset
            <span v-if="active" class="badge data">{{ describeOffset(store.offset) }}</span>
        </h2>
        <div class="row">
            <label for="offset-frame">Frame</label>
            <select id="offset-frame" v-model="frame">
                <option v-for="(f, key) in OFFSET_FRAMES" :key="key" :value="key">{{ f.label }}</option>
            </select>
        </div>
        <div class="row">
            <label for="offset-c1">{{ labels.c1 }}</label>
            <input id="offset-c1" type="text" v-model="first" placeholder="degrees" @keyup.enter="apply" />
        </div>
        <div class="row">
            <label for="offset-c2">{{ labels.c2 }}</label>
            <input id="offset-c2" type="text" v-model="second" placeholder="degrees" @keyup.enter="apply" />
        </div>
        <div class="buttons">
            <button @click="apply">Apply</button>
            <button v-if="active" class="signal" @click="clear">Clear</button>
        </div>
        <p v-if="parseError" class="error-text">{{ parseError }}</p>
        <p v-if="beamPlacement" class="hint data">
            Beam is {{ formatDeg(beamPlacement.onSky, 2) }}° off source:
            az {{ signed(beamPlacement.dAz) }}, el {{ signed(beamPlacement.dEl) }}
        </p>
        <p class="hint">
            <template v-if="active && store.offset.frame === 'track'">
                Δ∥ leads the target along its path, Δ⊥ steps across it, both in true on-sky
                degrees ({{ formatDeg(separation, 2) }}° total).
            </template>
            <template v-else-if="active && separation !== null">
                Beam moves {{ formatDeg(separation, 2) }}° on sky from the current pointing.
            </template>
            <template v-else-if="active">Applied to commanded coordinates.</template>
            <template v-else-if="tracking">Applying re-points what is tracking now.</template>
            <template v-else>Added to every pointing command until cleared.</template>
            <template v-if="strobeWarning">
                This offset does not stay put on the sky, so the console will take over
                tracking from the server.
            </template>
        </p>
    </div>
</template>

<style scoped>
    .row {
        display: grid;
        grid-template-columns: 80px 1fr;
        gap: 8px;
        align-items: center;
        margin-bottom: 7px;
    }

    .badge {
        float: right;
        text-transform: none;
        letter-spacing: 0;
        font-size: 11px;
        color: var(--signal);
    }

    .buttons {
        display: flex;
        gap: 8px;
        margin-top: 4px;
    }

    .hint {
        font-size: 12px;
        color: var(--muted);
        margin: 8px 0 0;
    }
</style>
