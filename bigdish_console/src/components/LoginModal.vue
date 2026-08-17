<script setup>
    // Connection dialog; structure borrowed from the sibling Vue client's LoginModal.
    import { ref } from 'vue';

    const props = defineProps(['config', 'errorText', 'busy']);
    const emit = defineEmits(['connect']);

    // Remember the last server and user across sessions; fall back to config defaults.
    const remembered = JSON.parse(localStorage.getItem('login') ?? '{}');
    const host = ref(remembered.host ?? props.config.server.host);
    const port = ref(remembered.port ?? props.config.server.port);
    const user = ref(remembered.user ?? '');
    const password = ref('');
    const kick = ref(false);

    function connect(control) {
        if (props.busy) return;
        localStorage.setItem('login', JSON.stringify({
            host: host.value, port: Number(port.value), user: user.value,
        }));
        emit('connect', {
            host: host.value,
            port: Number(port.value),
            user: user.value,
            password: password.value,
            control,
            kick: kick.value,
        });
    }
</script>

<template>
    <div class="modal-backdrop">
        <div class="modal panel">
            <h2 class="panel-title">Connect to dish server</h2>
            <div class="grid">
                <label for="login-host">Server</label>
                <div class="host-row">
                    <input id="login-host" type="text" v-model="host" />
                    <input id="login-port" type="number" v-model="port" aria-label="Port" />
                </div>
                <label for="login-user">User</label>
                <input id="login-user" type="text" v-model="user" @keyup.enter="connect(true)" />
                <label for="login-password">Password</label>
                <input id="login-password" type="password" v-model="password" @keyup.enter="connect(true)" />
            </div>
            <div class="kick-row">
                <input id="login-kick" type="checkbox" v-model="kick" />
                <label for="login-kick">Kick any user currently controlling the dish</label>
            </div>
            <div class="buttons">
                <button :disabled="busy" @click="connect(false)">View only</button>
                <button class="signal" :disabled="busy" @click="connect(true)">
                    {{ busy ? 'Connecting…' : 'Connect with control' }}
                </button>
            </div>
            <p v-if="busy" class="hint">Connecting to {{ host }}:{{ port }}…</p>
            <p v-if="props.errorText && !busy" class="error-text">{{ props.errorText }}</p>
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
        z-index: 10;
    }

    .modal {
        width: min(420px, 92vw);
        padding: 18px 20px 20px;
    }

    .grid {
        display: grid;
        grid-template-columns: 90px 1fr;
        gap: 10px;
        align-items: center;
    }

    .host-row {
        display: flex;
        gap: 8px;
    }

    .host-row input[type="number"] {
        width: 90px;
    }

    .kick-row {
        display: flex;
        align-items: center;
        gap: 8px;
        margin: 14px 0 6px;
    }

    .kick-row label {
        text-transform: none;
        letter-spacing: 0.02em;
        font-family: var(--font-body);
        font-size: 13px;
    }

    .buttons {
        display: flex;
        justify-content: flex-end;
        gap: 8px;
        margin-top: 10px;
    }

    .hint {
        font-size: 12px;
        color: var(--muted);
        margin: 8px 0 0;
    }
</style>
