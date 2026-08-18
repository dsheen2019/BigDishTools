<script setup>
    import { ref, computed } from 'vue';
    import { parseAngle } from '../lib/format.js';

    const props = defineProps(['store', 'entry']);
    const emit = defineEmits(['command']);

    const FRAMES = {
        azel: { label: 'Az / El', c1: 'az', c2: 'el', track: false, hint: 'degrees' },
        radec: { label: 'RA / Dec', c1: 'ra', c2: 'dec', track: true, hint: 'degrees or 05h34m32s' },
        gal: { label: 'Galactic l / b', c1: 'l', c2: 'b', track: true, hint: 'degrees' },
    };

    const duration = ref(300);
    const parseError = ref('');
    const canMove = computed(() => props.store.state === 'INITIALIZED');
    const frame = computed(() => FRAMES[props.entry.frame]);

    function parsed() {
        const raHours = props.entry.frame === 'radec';
        const coord1 = parseAngle(props.entry.coord1, { raHours });
        const coord2 = parseAngle(props.entry.coord2);
        if (coord1 === null || coord2 === null) {
            parseError.value = `Enter ${frame.value.c1} and ${frame.value.c2} as ${frame.value.hint}.`;
            return null;
        }
        parseError.value = '';
        return { coord1, coord2 };
    }

    function goto_() {
        const coords = parsed();
        if (coords) {
            emit('command', { action: 'goto', frame: props.entry.frame, ...coords });
        }
    }

    function track() {
        const coords = parsed();
        if (coords) {
            emit('command', { action: 'track', frame: props.entry.frame, ...coords, duration: Number(duration.value) });
        }
    }
</script>

<template>
    <div class="panel">
        <h2 class="panel-title">Point</h2>
        <div class="row">
            <label for="cmd-frame">Frame</label>
            <select id="cmd-frame" v-model="entry.frame">
                <option v-for="(f, key) in FRAMES" :key="key" :value="key">{{ f.label }}</option>
            </select>
        </div>
        <div class="row">
            <label :for="'cmd-c1'">{{ frame.c1 }}</label>
            <input id="cmd-c1" type="text" v-model="entry.coord1" :placeholder="frame.hint" @keyup.enter="goto_" />
        </div>
        <div class="row">
            <label :for="'cmd-c2'">{{ frame.c2 }}</label>
            <input id="cmd-c2" type="text" v-model="entry.coord2" :placeholder="'degrees'" @keyup.enter="goto_" />
        </div>
        <!-- kept for the frames that cannot be tracked, so switching frame does not move
             everything below this panel up and down -->
        <div class="row" :class="{ hidden: !frame.track }">
            <label for="cmd-duration">Track for</label>
            <div class="duration">
                <input id="cmd-duration" type="number" min="1" v-model="duration" />
                <span class="data seconds">s</span>
            </div>
        </div>
        <div class="buttons">
            <button :disabled="!canMove" @click="goto_">Go to</button>
            <button v-if="frame.track" :disabled="!canMove" @click="track">Track</button>
        </div>
        <!-- two lines held for whichever applies -->
        <div class="messages reserve-2">
            <p v-if="parseError" class="error-text">{{ parseError }}</p>
            <p v-else-if="!canMove" class="hint">Connect with control to move the dish. Clicking the map or sky fills these fields.</p>
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

    .duration {
        display: flex;
        align-items: center;
        gap: 6px;
    }

    .duration input {
        width: 90px;
    }

    .seconds {
        color: var(--muted);
        font-size: 12px;
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

    .messages {
        margin-top: 8px;
        font-size: 12px;
    }

    .messages p {
        margin: 0;
    }
</style>
