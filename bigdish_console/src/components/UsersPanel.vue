<script setup>
    import { ref, onMounted, onUnmounted } from 'vue';

    const props = defineProps(['client', 'store']);
    const users = ref([]);

    function ago(timestamp) {
        if (!timestamp) return '—';
        const seconds = Math.max(0, Math.round(Date.now() / 1000 - timestamp));
        if (seconds < 90) return `${seconds} s ago`;
        if (seconds < 5400) return `${Math.round(seconds / 60)} min ago`;
        return `${Math.round(seconds / 3600)} h ago`;
    }

    let timer = null;
    onMounted(() => {
        timer = setInterval(async () => {
            if (!props.client || (props.store.state !== 'AUTHENTICATED' && props.store.state !== 'INITIALIZED')) {
                return;
            }
            try {
                const response = await props.client.get_active_users();
                if (response.success) {
                    users.value = response.users.filter((user) => user.account);
                }
            } catch { /* transient */ }
        }, 2000);
    });
    onUnmounted(() => clearInterval(timer));
</script>

<template>
    <div class="panel">
        <h2 class="panel-title">Connected users</h2>
        <table class="data">
            <thead>
                <tr><th>User</th><th>Control</th><th>Last command</th></tr>
            </thead>
            <tbody>
                <tr v-for="user in users" :key="user.account + user.last_active">
                    <td>{{ user.account }}</td>
                    <td :class="{ controlling: user.state === 'INITIALIZED' }">
                        {{ user.state === 'INITIALIZED' ? 'yes' : '—' }}
                    </td>
                    <td>{{ ago(user.last_active) }}</td>
                </tr>
                <tr v-if="users.length === 0">
                    <td colspan="3" class="empty">No user list yet.</td>
                </tr>
            </tbody>
        </table>
    </div>
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
