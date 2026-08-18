<script setup>
    // Utilities: the things that are neither pointing nor watching.
    //
    // For now, adding targets the config does not list -- a satellite from CelesTrak, a source
    // from SIMBAD. Anything added here belongs to this session only: it is in the dropdown
    // until the console is reloaded, and is not written back to config.toml.

    import { computed } from 'vue';
    import SearchPicker from './SearchPicker.vue';

    const props = defineProps(['store']);
    const emit = defineEmits(['add-target']);

    const added = computed(() => props.store.extraTargets ?? []);
</script>

<template>
    <div class="utilities">
        <div class="panel column">
            <h2 class="panel-title">Find a satellite</h2>
            <SearchPicker catalogue="satellite" label="CelesTrak"
                          placeholder="ISS, STARLINK-31, 25544, 1998-067A"
                          hint="By name, catalog number or international designator. Elements come back as OMM and are refetched when tracking starts."
                          @add="(target) => emit('add-target', target)" />
        </div>

        <div class="panel column">
            <h2 class="panel-title">Find a source</h2>
            <SearchPicker catalogue="simbad" label="SIMBAD"
                          placeholder="crab, M87, Cas A, 3C273, Sgr A*"
                          hint="Resolved by name or catalogue designation. The first result is what the resolver made of it; anything below is another object whose identifier also matches."
                          @add="(target) => emit('add-target', target)" />
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
    .utilities {
        flex: 1;
        min-height: 0;
        display: grid;
        grid-template-columns: 1fr 1fr;
        grid-template-rows: 1fr auto;
        gap: 10px;
        overflow-y: auto;
    }

    .column {
        display: flex;
        flex-direction: column;
        min-height: 0;
    }

    .added {
        grid-column: 1 / 3;
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

        .added {
            grid-column: 1;
        }
    }
</style>
