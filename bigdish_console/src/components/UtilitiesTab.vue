<script setup>
    // Utilities: the things that are neither pointing nor watching.
    //
    // For now, adding targets the config does not list -- a satellite from CelesTrak, a source
    // from SIMBAD. Anything added here belongs to this session only: it is in the dropdown
    // until the console is reloaded, and is not written back to config.toml.

    import { computed, ref } from 'vue';
    import SearchPicker from './SearchPicker.vue';
    import { readEphemerisFile } from '../lib/ephemeris_file.js';
    import { describeTarget } from '../lib/targets.js';
    import { parsePointingFile, rowsInThePast } from '../lib/pointing_file.js';
    import { formatWait } from '../lib/schedule.js';

    const props = defineProps(['store', 'log']);
    const emit = defineEmits(['add-target', 'queue-file', 'cancel-file']);

    const added = computed(() => props.store.extraTargets ?? []);
    const pointing = ref(null);        // the parsed file, before anybody commits to it
    const pointingError = ref('');
    const pointingState = computed(() => props.store.schedule?.state ?? 'idle');

    async function readPointingFile(event) {
        const file = event.target.files?.[0];
        if (!file) return;
        pointing.value = null;
        pointingError.value = '';
        try {
            const parsed = parsePointingFile(file.name, await file.text());
            parsed.past = rowsInThePast(parsed);
            pointing.value = parsed;
        } catch (error) {
            pointingError.value = error.message;
        }
        event.target.value = '';
    }

    function clearPointing() {
        pointing.value = null;
        pointingError.value = '';
    }

    const clock = (seconds) =>
        new Date(seconds * 1000).toISOString().slice(0, 19).replace('T', ' ') + 'Z';

    const startsIn = computed(() => {
        if (!pointing.value) return '';
        const wait = pointing.value.summary.start - Date.now() / 1000;
        return wait > 0 ? `starts in ${formatWait(wait)}` : `started ${formatWait(-wait)} ago`;
    });

    const requestedInterval = ref(1.0);
    const logPower = ref(true);
    const snapped = computed(() => props.log.snap(Number(requestedInterval.value) || 0));

    function saveLog() {
        const blob = new Blob([props.log.toCsv()], { type: 'text/csv' });
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = props.log.suggestedFilename();
        link.click();
        URL.revokeObjectURL(url);
    }

    const fileMessage = ref('');
    const fileFailed = ref(false);

    // Read locally: nothing is uploaded, here or anywhere else in this app.
    async function readFile(event) {
        const file = event.target.files?.[0];
        if (!file) return;
        fileMessage.value = '';
        fileFailed.value = false;
        try {
            const target = readEphemerisFile(file.name, await file.text());
            emit('add-target', target);
            const states = target.spec.times?.length;
            fileMessage.value = states
                ? `Added ${target.name}: ${states} state vectors covering `
                  + `${((target.spec.times.at(-1) - target.spec.times[0]) / 3600).toFixed(1)} hours.`
                : `Added ${target.name}.`;
        } catch (error) {
            fileFailed.value = true;
            fileMessage.value = error.message;
        }
        event.target.value = '';   // so the same file can be picked again after a fix
    }
</script>

<template>
    <div class="utilities">
        <div class="stack">
        <div class="panel column pointing">
            <h2 class="panel-title">
                Run a pointing file
                <span v-if="pointingState !== 'idle'" class="count data">{{ pointingState }}</span>
            </h2>
            <label for="pointing-file">File</label>
            <input id="pointing-file" type="file" accept=".csv,.txt" @change="readPointingFile" />

            <p v-if="pointingError" class="error-text">{{ pointingError }}</p>

            <template v-if="pointing">
                <table class="frames data summary">
                    <tbody>
                        <tr><th>rows</th><td>{{ pointing.summary.count }}</td></tr>
                        <tr><th>frames</th><td>{{ pointing.summary.frames.join(', ') }}</td></tr>
                        <tr><th>starts</th><td>{{ clock(pointing.summary.start) }}</td></tr>
                        <tr><th>runs for</th><td>{{ formatWait(pointing.summary.duration) }}</td></tr>
                        <tr><th>step</th><td>{{ pointing.summary.shortestGap }}–{{ pointing.summary.longestGap }} s</td></tr>
                        <tr v-if="pointing.summary.lowestElevation !== null">
                            <th>lowest el</th><td>{{ pointing.summary.lowestElevation }}°</td>
                        </tr>
                    </tbody>
                </table>
                <p v-if="pointing.past" class="error-text">
                    {{ pointing.past }} of {{ pointing.summary.count }} rows are already in the
                    past and would be sent with a time that has gone.
                </p>
                <p v-else class="hint reserve-1">{{ startsIn }}; the pointing offset is zeroed then.</p>
                <div class="row buttons">
                    <button :disabled="store.state !== 'INITIALIZED' || pointingState === 'queued'
                                || pointingState === 'running'"
                            @click="emit('queue-file', pointing)">Queue</button>
                    <button v-if="['queued', 'running'].includes(pointingState)" class="signal"
                            @click="emit('cancel-file')">Cancel</button>
                    <!-- for the file that was not the one you meant to open. Only before it is
                         handed over: once queued, the thing to press is Cancel. -->
                    <button v-else @click="clearPointing">Clear</button>
                </div>
            </template>
            <p v-if="store.schedule?.text" class="hint data">{{ store.schedule.text }}</p>
        </div>

        <!-- under the pointing file, being the other thing you hand the console from disk -->
        <div class="panel column load">
            <h2 class="panel-title">Load an ephemeris</h2>
            <label for="ephemeris-file">File</label>
            <!-- .asc is what NASA names its OEM files. The list is only what the file
                 dialog offers first; what a file actually is gets worked out by reading it. -->
            <input id="ephemeris-file" type="file" accept=".json,.txt,.tle,.oem,.omm,.asc,.e"
                   @change="readFile" />
            <p :class="[fileFailed ? 'error-text' : 'hint', 'reserve-2']">
                {{ fileMessage || 'Accepts OMM (.json), TLE (.txt, .tle) and CCSDS OEM'
                    + ' (.oem, .asc).' }}
            </p>
        </div>
        </div>

        <div class="stack">
        <div class="panel column find-satellite">
            <h2 class="panel-title">Find a satellite</h2>
            <SearchPicker catalogue="satellite" label="CelesTrak"
                          placeholder="ISS, STARLINK-31, 25544, 1998-067A"
                          hint="By name, catalog number or international designator."
                          @add="(target) => emit('add-target', target)" />
        </div>

        <div class="panel column find-source">
            <h2 class="panel-title">Find a source</h2>
            <SearchPicker catalogue="simbad" label="SIMBAD"
                          placeholder="crab, M87, Cas A, 3C273, Sgr A*"
                          hint="Resolved by name or catalogue designation."
                          @add="(target) => emit('add-target', target)" />
        </div>

        </div>

        <div class="stack">
        <div class="panel column log">
            <h2 class="panel-title">
                Log position
                <span v-if="log.running" class="count data">recording</span>
            </h2>
            <div class="row">
                <label for="log-interval">Every</label>
                <input id="log-interval" type="number" min="0.2" step="0.2"
                       v-model="requestedInterval" :disabled="log.running" />
                <span class="data unit">s</span>
            </div>
            <label class="check">
                <input type="checkbox" v-model="logPower" :disabled="log.running" />
                include motor voltages and currents
            </label>
            <div class="row buttons">
                <button v-if="!log.running" @click="log.start(Number(requestedInterval), logPower)">
                    Start
                </button>
                <button v-else class="signal" @click="log.stop()">Stop</button>
                <button :disabled="!log.rows.length" @click="saveLog">Save csv</button>
            </div>
            <!-- the interval that will actually be delivered, since the requested one is
                 snapped to the status poll this logs from -->
            <p class="hint data reserve-1">Rounded to {{ snapped }} s.</p>
        </div>

        <div class="panel added">
            <h2 class="panel-title">
                Added this session
                <span v-if="added.length" class="count data">{{ added.length }}</span>
            </h2>
            <p v-if="!added.length" class="hint">
                Nothing yet. Anything added joins the Targets dropdown until the console is
                reloaded.
            </p>
            <ul v-else class="list">
                <li v-for="target in added" :key="target.name">
                    <span class="data">{{ target.name }}</span>
                    <span class="where data">{{ describeTarget(target) }}</span>
                </li>
            </ul>
        </div>
        </div>
    </div>
</template>

<style scoped>
    /* Two columns of stacked panels. The searches take the left, each holding a list of
     * results and so wanting both the width and the height; the loader, the logger and the
     * list of what has been added share the right, where none of them needs much of either. */
    .utilities {
        flex: 1;
        min-height: 0;
        display: grid;
        grid-template-columns: 1fr 1fr 1fr;
        gap: 10px;
        overflow-y: auto;
    }

    .stack {
        display: flex;
        flex-direction: column;
        gap: 10px;
        min-height: 0;
    }

    .find-satellite, .find-source {
        flex: 1;
        min-height: 0;
    }

    .pointing {
        flex: 1;
        min-height: 0;
        overflow-y: auto;
    }

    .summary th {
        width: 5.5rem;
    }

    /* the list of what has been added takes whatever the two above it leave */
    .added {
        flex: 1;
        min-height: 0;
        overflow-y: auto;
    }

    .column {
        display: flex;
        flex-direction: column;
        min-height: 0;
    }

    .check {
        display: flex;
        align-items: center;
        gap: 6px;
        text-transform: none;
        letter-spacing: 0;
        font-family: var(--font-body);
        font-size: 12px;
    }

    .check input {
        width: auto;
    }

    .row {
        display: flex;
        align-items: center;
        gap: 8px;
    }

    .row input[type="number"] {
        width: 80px;
    }

    .buttons {
        margin-top: 2px;
    }

    .unit {
        color: var(--muted);
        font-size: 12px;
    }

    input[type="file"] {
        font-family: var(--font-body);
        font-size: 12px;
        padding: 4px;
    }

    .count {
        font-size: 12px;
        color: var(--muted);
    }

    .list {
        list-style: none;
        margin: 0;
        padding: 0;
        display: flex;
        flex-wrap: wrap;
        gap: 6px 18px;
        font-size: 12px;
    }

    .list li {
        display: flex;
        gap: 8px;
    }

    .where {
        color: var(--muted);
    }

    .hint {
        font-size: 12px;
        color: var(--muted);
        margin: 0;
    }

    @media (max-width: 900px) {
        .utilities {
            grid-template-columns: 1fr;
        }

        .find-satellite, .find-source, .added {
            flex: none;
        }
    }
</style>
