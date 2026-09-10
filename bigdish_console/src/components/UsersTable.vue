<script setup>
    // Who else is on the server, drawn wherever it is needed: in the sidebar panel, and in
    // the session menu and the conflict dialog, where it is the thing the operator reads
    // before deciding whether to take control away from somebody.
    //
    // Presentational only. App.vue owns the poll, so all three views show the same list at
    // the same moment rather than each keeping its own.
    import { ago } from '../lib/format.js';

    defineProps(['users']);
</script>

<template>
    <table class="data">
        <thead>
            <tr><th>User</th><th>Control</th><th>Last command</th><th>Last move</th></tr>
        </thead>
        <tbody>
            <tr v-for="user in users" :key="user.account + user.last_active">
                <td>{{ user.account }}</td>
                <td :class="{ controlling: user.state === 'INITIALIZED' }">
                    {{ user.state === 'INITIALIZED' ? 'yes' : '—' }}
                </td>
                <td>{{ ago(user.last_active) }}</td>
                <td>{{ ago(user.last_movement) }}</td>
            </tr>
            <tr v-if="users.length === 0">
                <td colspan="4" class="empty">No user list yet.</td>
            </tr>
        </tbody>
    </table>
</template>

<style scoped>
    table {
        width: 100%;
        border-collapse: collapse;
        font-size: 12px;
    }

    th {
        font-family: var(--font-display);
        font-weight: 500;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        color: var(--muted);
        text-align: left;
        padding: 2px 8px 4px 0;
    }

    td {
        padding: 2px 8px 2px 0;
        border-top: 1px solid var(--panel-edge);
    }

    .controlling {
        color: var(--accent);
    }

    .empty {
        color: var(--muted);
    }
</style>
