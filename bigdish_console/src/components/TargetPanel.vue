<script setup>
    import { ref, computed, watch, onUnmounted } from 'vue';
    import { makeAzElFunction, fixedFrameAzEl } from '../lib/ephemeris.js';
    import { fetchElements } from '../lib/targets.js';
    import { formatDeg } from '../lib/format.js';

    const props = defineProps(['store', 'targets', 'config']);
    const emit = defineEmits(['command', 'start-strobe', 'stop-strobe']);

    const categories = computed(() => {
        const groups = new Map();
        for (const target of props.targets) {
            if (!groups.has(target.category)) groups.set(target.category, []);
            groups.get(target.category).push(target);
        }
        return groups;
    });

    // Starts on "none": no target selected means no sky track drawn over the charts.
    const selectedName = ref('');
    const selected = computed(() => props.targets.find((t) => t.name === selectedName.value));
    const duration = ref(300);
    const preview = ref('');
    const canMove = computed(() => props.store.state === 'INITIALIZED');
    const strobeActiveHere = computed(() =>
        props.store.strobe?.active && props.store.strobe.name === selectedName.value);

    // what the selected target supports, which decides what is greyed out rather than what
    // is on show: a station has a position but no track, a satellite the reverse
    const hasFixedPosition = computed(() => ['goto', 'track'].includes(selected.value?.kind));
    const canTrack = computed(() => selected.value?.kind === 'track');
    const canStrobe = computed(() => selected.value?.kind === 'strobe');

    // Live az/el preview for targets the console computes itself. Satellites need their
    // TLE first; it is fetched (and cached) as soon as one is selected.
    let previewTimer = null;
    let previewGeneration = 0;

    async function setupPreview(target) {
        clearInterval(previewTimer);
        previewTimer = null;
        preview.value = '';
        const generation = ++previewGeneration;
        // The map and star chart draw the selected target's sky path. Stations are fixed to
        // the ground and have no path, so they clear it; satellites fill it in below, once
        // the TLE is in hand.
        props.store.focus = target && target.kind !== 'goto'
            ? {
                name: target.name,
                spec: target.kind === 'track'
                    ? {
                        type: 'fixed',
                        frame: target.frame,
                        coord1: target.coord1,
                        coord2: target.coord2,
                    }
                    : target.spec,
            }
            : null;
        if (!target) return;

        if (target.kind === 'track') {
            const coords = `${target.frame === 'gal' ? 'l/b' : 'ra/dec'} ${formatDeg(target.coord1, 3)}°, ${formatDeg(target.coord2, 3)}°`;
            const tick = () => {
                const p = fixedFrameAzEl(target.frame, target.coord1, target.coord2,
                    props.config.site, new Date());
                preview.value = `${coords} · az ${formatDeg(p.az, 1)}°, el ${formatDeg(p.el, 1)}° ${p.el > 0 ? '(up)' : '(below horizon)'}`;
            };
            tick();
            previewTimer = setInterval(tick, 2000);
            return;
        }
        if (target.kind === 'goto') {
            preview.value = target.distance_miles !== undefined
                ? `bearing ${formatDeg(target.coord1, 1)}°, ${target.distance_miles.toFixed(0)} mi away`
                : `az ${formatDeg(target.coord1, 2)}°, el ${formatDeg(target.coord2, 2)}°`;
            return;
        }

        const spec = { ...target.spec };
        if (spec.type === 'satellite') {
            preview.value = 'fetching elements…';
            try {
                spec.omm = await fetchElements(target.catnr, props.config.tle_max_age_hours);
            } catch (error) {
                if (generation === previewGeneration) preview.value = error.message;
                return;
            }
            if (generation !== previewGeneration) return;
            props.store.focus = { name: target.name, spec };
        }
        let azElAt;
        try {
            azElAt = makeAzElFunction(spec, props.config.site);
        } catch (error) {
            preview.value = error.message;
            return;
        }
        const tick = () => {
            const p = azElAt(new Date());
            preview.value = p
                ? `az ${formatDeg(p.az, 2)}°, el ${formatDeg(p.el, 2)}° ${p.el > 0 ? '(up)' : '(below horizon)'}`
                : 'no position solution';
        };
        tick();
        previewTimer = setInterval(tick, 2000);
    }

    watch(selected, setupPreview, { immediate: true });
    onUnmounted(() => clearInterval(previewTimer));

    function goto_() {
        const t = selected.value;
        if (!t) return;
        emit('command', { action: 'goto', frame: t.frame, coord1: t.coord1, coord2: t.coord2 });
    }

    function track() {
        const t = selected.value;
        if (!t) return;
        emit('command', {
            action: 'track', frame: t.frame, coord1: t.coord1, coord2: t.coord2,
            duration: Number(duration.value),
        });
    }
</script>

<template>
    <div class="panel">
        <h2 class="panel-title">Targets</h2>
        <select v-model="selectedName" aria-label="Target">
            <option value="">None</option>
            <optgroup v-for="[category, list] in categories" :key="category" :label="category">
                <option v-for="target in list" :key="target.name" :value="target.name">{{ target.name }}</option>
            </optgroup>
        </select>
        <!-- two lines: the preview carries coordinates in two frames for a fixed target, and
             a fetch failure where a satellite's would be -->
        <p class="preview data reserve-2">{{ preview }}</p>

        <!-- Every control the panel has, always in the same place: what a given target does
             not support is greyed out rather than taken away. A control that vanishes moves
             everything under it and leaves you wondering whether you imagined it. -->
        <div class="row">
            <label for="target-duration">Track for</label>
            <input id="target-duration" type="number" min="1" v-model="duration"
                   :disabled="!canTrack" />
            <span class="data seconds">s</span>
        </div>
        <div class="buttons">
            <button :disabled="!canMove || !hasFixedPosition" @click="goto_">Go to</button>
            <button :disabled="!canMove || !canTrack" @click="track">Track</button>
            <button v-if="!strobeActiveHere" :disabled="!canMove || !canStrobe"
                    @click="emit('start-strobe', selected)">Track continuously</button>
            <button v-else class="signal" @click="emit('stop-strobe')">Stop tracking</button>
        </div>
    </div>
</template>

<style scoped>
    .preview {
        font-size: 12px;
        color: var(--muted);
        margin: 8px 0;
    }

    .row {
        display: flex;
        align-items: center;
        gap: 8px;
        margin-bottom: 7px;
    }

    .row input {
        width: 90px;
    }

    .seconds {
        color: var(--muted);
        font-size: 12px;
    }

    .buttons {
        display: flex;
        gap: 8px;
    }
</style>
