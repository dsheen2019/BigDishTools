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
        <!-- the two coordinates are one thing, and read as one: side by side, in the order
             they are always said in -->
        <div class="row coords">
            <label :for="'cmd-c1'">{{ frame.c1 }}</label>
            <input id="cmd-c1" type="text" v-model="entry.coord1" :placeholder="frame.hint" @keyup.enter="goto_" />
            <label :for="'cmd-c2'" class="second">{{ frame.c2 }}</label>
            <input id="cmd-c2" type="text" v-model="entry.coord2" :placeholder="'degrees'" @keyup.enter="goto_" />
        </div>
        <!-- greyed out for the frames that cannot be tracked, rather than taken away:
             switching frame should not move everything below this panel -->
        <div class="row">
            <label for="cmd-duration">Track for</label>
            <div class="duration">
                <input id="cmd-duration" type="number" min="1" v-model="duration"
                       :disabled="!frame.track" />
                <span class="data seconds">s</span>
                <!-- the buttons ride on this row: the duration only fills a third of it -->
                <div class="buttons">
                    <button :disabled="!canMove" @click="goto_">Go to</button>
                    <button :disabled="!canMove || !frame.track" @click="track">Track</button>
                </div>
            </div>
        </div>
        <!-- only when an entry did not parse; nothing is held open for it -->
        <p v-if="parseError" class="error-text one-line message" :title="parseError">{{ parseError }}</p>
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

    /* first label column matches the rows above it so the fields line up; the second takes
     * what its label needs, since "dec" and "el" are not the same width */
    .coords {
        grid-template-columns: 80px 1fr auto 1fr;
    }

    .coords .second {
        padding-left: 8px;
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
        margin-left: auto;   /* pushed to the end of the duration row */
    }

    /* the buttons sit on the last row, and nothing follows it */
    .row:last-child {
        margin-bottom: 0;
    }

    .message {
        margin: 8px 0 0;
        font-size: 12px;
        line-height: 1.4;
    }
</style>
