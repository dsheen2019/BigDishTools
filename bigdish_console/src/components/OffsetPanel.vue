<script setup>
    // Pointing offset entry. The offset lives in store.offset and App.vue folds it into
    // every pointing command; see lib/offset.js for what each frame combination means.

    import { ref, computed, watch } from 'vue';
    import { parseAngle, formatDeg } from '../lib/format.js';
    import {
        OFFSET_FRAMES, isZeroOffset, skySeparation, describeOffset,
    } from '../lib/offset.js';

    const props = defineProps(['store']);
    const emit = defineEmits(['apply']);

    const frame = ref(props.store.offset.frame);
    const first = ref('0');
    const second = ref('0');
    const parseError = ref('');

    const labels = computed(() => OFFSET_FRAMES[frame.value]);
    const active = computed(() => !isZeroOffset(props.store.offset));
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
        <div class="row coords">
            <label for="offset-c1">{{ labels.c1 }}</label>
            <input id="offset-c1" type="text" v-model="first" placeholder="degrees" @keyup.enter="apply" />
            <label for="offset-c2" class="second">{{ labels.c2 }}</label>
            <input id="offset-c2" type="text" v-model="second" placeholder="degrees" @keyup.enter="apply" />
        </div>
        <div class="buttons">
            <button @click="apply">Apply</button>
            <button class="signal" :disabled="!active" @click="clear">Clear</button>
        </div>
        <!-- One line, and only when there is something in it: an entry that did not parse,
             or where the beam actually ended up once an offset is applied. Nothing is held
             open under the buttons for a message that is usually not there. -->
        <div v-if="parseError || beamPlacement" class="message">
            <p v-if="parseError" class="error-text one-line" :title="parseError">{{ parseError }}</p>
            <p v-else class="hint data one-line">
                {{ formatDeg(beamPlacement.onSky, 2) }}° off source:
                az {{ signed(beamPlacement.dAz) }}, el {{ signed(beamPlacement.dEl) }}
            </p>
        </div>
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

    /* both offsets on one line, in the order the frame names them */
    .coords {
        grid-template-columns: 80px 1fr auto 1fr;
    }

    .coords .second {
        padding-left: 8px;
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

    .message {
        margin-top: 8px;
        font-size: 12px;
        line-height: 1.4;
    }

    .message p {
        margin: 0;
    }
</style>
