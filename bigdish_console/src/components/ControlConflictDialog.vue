<script setup>
    // Shown when control is asked for and somebody else has it.
    //
    // The kick used to be a checkbox on the startup dialog, ticked before there was any way of
    // knowing whether it mattered. Taking the dish out from under another operator is not a
    // preference, it is a decision about somebody else's observation, so it is made here, with
    // their name and how long since they last moved the dish in front of you. A user who has
    // not commanded anything for an hour is probably a forgotten browser tab; one who moved it
    // a minute ago is at the controls.
    import { computed } from 'vue';
    import UsersTable from './UsersTable.vue';
    import { ago } from '../lib/format.js';

    const props = defineProps(['holders', 'reason', 'busy']);
    defineEmits(['cancel', 'confirm']);

    // The usual case is one holder -- the server allows only one INITIALIZED connection -- so
    // it gets a sentence rather than a table to read.
    const only = computed(() => (props.holders?.length === 1 ? props.holders[0] : null));
</script>

<template>
    <div class="modal-backdrop">
        <div class="modal panel">
            <h2 class="panel-title">Another user has control</h2>

            <p v-if="only" class="line">
                <b>{{ only.account }}</b> is controlling the dish. They last sent a command
                {{ ago(only.last_active) }}, and last moved the dish
                {{ ago(only.last_movement) }}.
            </p>
            <template v-else>
                <p class="line">These users are controlling the dish:</p>
                <UsersTable :users="holders" />
            </template>

            <p class="line warn">
                Taking control disconnects them from control without warning and clears
                whatever the dish has been told to do, including any commands they had
                scheduled ahead.
            </p>

            <p v-if="reason" class="line muted">Server said: {{ reason }}</p>

            <div class="buttons">
                <button :disabled="busy" @click="$emit('cancel')">Stay view only</button>
                <button class="signal" :disabled="busy" @click="$emit('confirm')">
                    {{ busy ? 'Taking…' : 'Take control anyway' }}
                </button>
            </div>
        </div>
    </div>
</template>

<style scoped>
    .modal-backdrop {
        position: fixed;
        inset: 0;
        background: var(--backdrop);
        display: flex;
        align-items: center;
        justify-content: center;
        z-index: 11;
    }

    .modal {
        width: min(440px, 92vw);
        padding: 18px 20px 20px;
    }

    .line {
        font-size: 13px;
        margin: 0 0 8px;
    }

    .warn {
        color: var(--signal);
    }

    .muted {
        color: var(--muted);
    }

    .buttons {
        display: flex;
        justify-content: flex-end;
        gap: 8px;
        margin-top: 14px;
    }
</style>
