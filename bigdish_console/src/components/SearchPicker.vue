<script setup>
    // A search box and the list of what it found, for either catalogue.
    //
    // Searching happens when asked, not as you type: every search is a request to somebody
    // else's server, and the console has no business firing one off per keystroke.

    import { ref } from 'vue';
    import { searchCatalogue } from '../lib/search.js';

    const props = defineProps(['catalogue', 'label', 'placeholder', 'hint']);
    const emit = defineEmits(['add']);

    const query = ref('');
    const results = ref([]);
    const total = ref(0);
    const state = ref('idle');   // idle | searching | done | error
    const message = ref('');

    async function search() {
        const text = query.value.trim();
        if (text.length < 2) {
            state.value = 'error';
            message.value = 'Type at least two characters.';
            return;
        }
        state.value = 'searching';
        message.value = '';
        results.value = [];
        try {
            const found = await searchCatalogue(props.catalogue, text);
            results.value = found.results;
            total.value = found.total;
            state.value = 'done';
            if (found.total === 0) {
                message.value = `Nothing matching "${text}".`;
            } else if (found.total > found.results.length) {
                message.value = `${found.total} matches; showing the first `
                    + `${found.results.length}. Narrow the search to see the rest.`;
            }
        } catch (error) {
            state.value = 'error';
            message.value = error.message;
        }
    }
</script>

<template>
    <div class="search">
        <label :for="`search-${catalogue}`">{{ label }}</label>
        <div class="row">
            <input :id="`search-${catalogue}`" type="text" v-model="query"
                   :placeholder="placeholder" @keyup.enter="search" />
            <button :disabled="state === 'searching'" @click="search">
                {{ state === 'searching' ? 'Searching…' : 'Search' }}
            </button>
        </div>
        <p v-if="hint && state === 'idle'" class="hint">{{ hint }}</p>
        <p v-if="message" :class="state === 'error' ? 'error-text' : 'hint'">{{ message }}</p>

        <ul v-if="results.length" class="results">
            <li v-for="result in results" :key="result.key">
                <div class="what">
                    <span class="name data">{{ result.name }}</span>
                    <span class="detail data">{{ result.detail }}</span>
                </div>
                <button @click="emit('add', result.target)">Add</button>
            </li>
        </ul>
    </div>
</template>

<style scoped>
    .search {
        display: flex;
        flex-direction: column;
        gap: 6px;
        min-height: 0;
    }

    .row {
        display: flex;
        gap: 8px;
    }

    .row input {
        flex: 1;
    }

    .row button {
        white-space: nowrap;
    }

    .results {
        list-style: none;
        margin: 4px 0 0;
        padding: 0;
        overflow-y: auto;
        border: 1px solid var(--panel-edge);
        border-radius: 4px;
    }

    .results li {
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 5px 8px;
        border-bottom: 1px solid var(--panel-edge);
    }

    .results li:last-child {
        border-bottom: none;
    }

    .what {
        flex: 1;
        min-width: 0;
        display: flex;
        flex-direction: column;
    }

    .name {
        font-size: 13px;
    }

    .detail {
        font-size: 11px;
        color: var(--muted);
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }

    .hint {
        font-size: 12px;
        color: var(--muted);
        margin: 0;
    }
</style>
