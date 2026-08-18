<script setup>
    // Utilities: the things that are neither pointing nor watching.
    //
    // For now, adding targets the config does not list -- a satellite from CelesTrak, a source
    // from SIMBAD. Anything added here belongs to this session only: it is in the dropdown
    // until the console is reloaded, and is not written back to config.toml.

    import { computed, ref } from 'vue';
    import SearchPicker from './SearchPicker.vue';
    import { readEphemerisFile } from '../lib/ephemeris_file.js';

    const props = defineProps(['store', 'log']);
    const emit = defineEmits(['add-target']);

    const added = computed(() => props.store.extraTargets ?? []);
    const requestedInterval = ref(1.0);
    const logPower = ref(true);
    const snapped = computed(() => props.log.snap(Number(requestedInterval.value) || 0));
    const logSummary = computed(() => {
        const log = props.log;
        if (!log.rows.length) {
            return log.running ? 'Waiting for the first reading.' : 'Not logging.';
        }
        const span = log.span;
        const minutes = span >= 60 ? `${(span / 60).toFixed(1)} min` : `${span.toFixed(0)} s`;
        const missing = log.missingSeconds > 0
            ? ` · ${log.gaps.length} gap${log.gaps.length > 1 ? 's' : ''}, `
              + `${log.missingSeconds.toFixed(0)} s missing`
            : '';
        return `${log.rows.length} rows over ${minutes}${missing}`;
    });

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
        <div class="panel column find-satellite">
            <h2 class="panel-title">Find a satellite</h2>
            <SearchPicker catalogue="satellite" label="CelesTrak"
                          placeholder="ISS, STARLINK-31, 25544, 1998-067A"
                          hint="By name, catalog number or international designator. Elements come back as OMM and are refetched when tracking starts."
                          @add="(target) => emit('add-target', target)" />
        </div>

        <div class="panel column find-source">
            <h2 class="panel-title">Find a source</h2>
            <SearchPicker catalogue="simbad" label="SIMBAD"
                          placeholder="crab, M87, Cas A, 3C273, Sgr A*"
                          hint="Resolved by name or catalogue designation. The first result is what the resolver made of it; anything below is another object whose identifier also matches."
                          @add="(target) => emit('add-target', target)" />
        </div>

        <div class="panel column load">
            <h2 class="panel-title">Load an ephemeris</h2>
            <label for="ephemeris-file">File</label>
            <!-- .asc is what NASA names its OEM files. The list is only what the file
                 dialog offers first; what a file actually is gets worked out by reading it. -->
            <input id="ephemeris-file" type="file" accept=".json,.txt,.tle,.oem,.omm,.asc,.e"
                   @change="readFile" />
            <p :class="fileFailed ? 'error-text' : 'hint'">
                {{ fileMessage || 'OMM (json), a TLE, or a CCSDS OEM (.oem, or .asc as NASA'
                    + ' names them). Elements are propagated;'
                    + ' a table of state vectors is interpolated between, so it points where'
                    + ' whoever produced the file says, not where SGP4 guesses.' }}
            </p>
        </div>

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
            <p class="hint data">{{ logSummary }}</p>
            <p class="hint">
                Rounded to {{ snapped }} s, the nearest multiple of the
                {{ (1 / (store.pollHz ?? 5)).toFixed(1) }} s status poll this logs from — it
                records the readings the console already asks for rather than opening a second
                stream. Same columns as WR66_log_position.py.
            </p>
        </div>

        <div class="panel added">
            <h2 class="panel-title">
                Added this session
                <span v-if="added.length" class="count data">{{ added.length }}</span>
            </h2>
            <p v-if="!added.length" class="hint">
                Nothing yet. Anything added appears in the Targets dropdown, grouped at the
                bottom, and is gone when the console is reloaded — to keep one, put it in
                config.toml.
            </p>
            <ul v-else class="list">
                <li v-for="target in added" :key="target.name">
                    <span class="data">{{ target.name }}</span>
                    <span class="where data">{{ target.catnr ? `catalog ${target.catnr}`
                        : `ra ${target.coord1.toFixed(3)}° dec ${target.coord2.toFixed(3)}°` }}</span>
                </li>
            </ul>
        </div>
    </div>
</template>

<style scoped>
    /* Searches down the left, the two smaller utilities down the right. The searches are what
     * needs the room -- each holds a list of results -- so they take a full half of the width
     * rather than a quarter, and the two on the right take only the height they need. */
    .utilities {
        flex: 1;
        min-height: 0;
        display: grid;
        grid-template-columns: 1fr 1fr;
        grid-template-rows: 1fr 1fr auto;
        gap: 10px;
        overflow-y: auto;
    }

    .find-satellite { grid-column: 1; grid-row: 1; }
    .find-source { grid-column: 1; grid-row: 2; }
    .load { grid-column: 2; grid-row: 1; align-self: start; }
    .log { grid-column: 2; grid-row: 2; align-self: start; }

    .column {
        display: flex;
        flex-direction: column;
        min-height: 0;
    }

    .added {
        grid-column: 1 / 3;
        grid-row: 3;
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

        .find-satellite, .find-source, .load, .log, .added {
            grid-column: 1;
            grid-row: auto;
            align-self: auto;
        }
    }
</style>
