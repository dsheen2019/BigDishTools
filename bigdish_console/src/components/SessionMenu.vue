<script setup>
    // The session control in the header: who you are signed in as, who else is on, and the
    // one action that applies to the state you are in -- log in, take control, release it,
    // log out.
    //
    // Control used to be something you committed to in the startup dialog and could only give
    // up by closing the tab. Here it is a state you can enter and leave while the console goes
    // on running: the charts, the diagnostics history and the position log all need nothing
    // more than an authenticated connection, so stepping back to view only costs none of them.
    import { ref, computed, onMounted, onUnmounted } from 'vue';
    import UsersTable from './UsersTable.vue';

    const props = defineProps(['store', 'session', 'tracking']);
    const emit = defineEmits(['open-login', 'take-control', 'release', 'logout']);

    const open = ref(false);
    // '' | 'release' | 'logout' -- which action is waiting on the confirm step below
    const confirming = ref('');
    const stopFirst = ref(true);
    const root = ref(null);

    const connected = computed(() => props.store.state !== 'DISCONNECTED');
    const controlling = computed(() => props.store.state === 'INITIALIZED');
    const chip = computed(() => (connected.value
        ? `${props.session.user}@${props.session.host}:${props.session.port}`
        : 'not connected'));

    function close() {
        open.value = false;
        confirming.value = '';
    }

    function toggle() {
        if (open.value) close();
        else open.value = true;
    }

    // Releasing and logging out both give up control, and while something is following a
    // target that decision has a second half: the server runs the command it already has
    // whether or not anyone is left in control, so the dish carries on tracking unless it is
    // told to stop. That is worth one deliberate click; everything else acts at once.
    function ask(action) {
        if (controlling.value && props.tracking) {
            confirming.value = action;
            stopFirst.value = true;
            return;
        }
        act(action, false);
    }

    function act(action, stop) {
        close();
        emit(action, { stopFirst: stop });
    }

    function login() {
        close();
        emit('open-login');
    }

    function take() {
        close();
        emit('take-control');
    }

    // Close when the click was somewhere else. Registered in the capture phase, which matters
    // more than it looks: in the bubble phase this runs *after* the button's own handler, and
    // the browser takes a microtask checkpoint between the two listeners. Vue flushes its
    // re-render in that gap, so a click on a button that removes itself -- Release control
    // swapping the button row for the confirm block -- arrives here with event.target already
    // detached from the document. contains() then says false, an ordinary click inside the
    // menu reads as a click outside it, and the menu closes on the very interaction that was
    // meant to open the next step of it. Capturing runs before any of that happens.
    function onDocumentClick(event) {
        if (open.value && root.value && !root.value.contains(event.target)) {
            close();
        }
    }

    function onKeydown(event) {
        if (event.key === 'Escape') close();
    }

    onMounted(() => {
        document.addEventListener('click', onDocumentClick, true);
        document.addEventListener('keydown', onKeydown);
    });
    onUnmounted(() => {
        document.removeEventListener('click', onDocumentClick, true);
        document.removeEventListener('keydown', onKeydown);
    });
</script>

<template>
    <div class="session" ref="root">
        <button class="chip" :class="{ controlling }" :aria-expanded="open" @click="toggle">
            <span class="who one-line" :title="chip">{{ chip }}</span>
            <span class="caret" aria-hidden="true">▾</span>
        </button>

        <div v-if="open" class="popover panel">
            <h2 class="panel-title">Session</h2>

            <p class="line">
                <template v-if="connected">
                    Signed in as <b>{{ session.user }}</b> —
                    {{ controlling ? 'you have dish control.' : 'view only.' }}
                </template>
                <template v-else>Not connected to a dish server.</template>
            </p>

            <template v-if="connected">
                <h3 class="sub">Connected users</h3>
                <UsersTable :users="store.users" />
            </template>

            <p v-if="session.notice" class="error-text line">{{ session.notice }}</p>

            <div v-if="confirming" class="confirm">
                <p class="line">
                    The dish is following a target. Giving up control does not stop it: the
                    server runs the command it already has until that command ends.
                </p>
                <label class="check">
                    <input type="checkbox" v-model="stopFirst" />
                    Stop the dish first
                </label>
                <div class="buttons">
                    <button @click="confirming = ''">Cancel</button>
                    <button class="signal" @click="act(confirming, stopFirst)">
                        {{ confirming === 'release' ? 'Release control' : 'Log out' }}
                    </button>
                </div>
            </div>

            <div v-else class="buttons">
                <button v-if="!connected" @click="login">Log in…</button>
                <button v-if="connected && !controlling" :disabled="Boolean(session.busy)"
                        @click="take">Take control</button>
                <button v-if="controlling" :disabled="Boolean(session.busy)"
                        @click="ask('release')">Release control</button>
                <button v-if="connected" @click="ask('logout')">Log out</button>
            </div>
        </div>
    </div>
</template>

<style scoped>
    .session {
        position: relative;
    }

    .chip {
        display: flex;
        align-items: center;
        gap: 6px;
        max-width: 260px;
    }

    .chip .who {
        /* the account and server are data, and long ones are cut rather than allowed to
         * stretch the header */
        font-family: var(--font-data);
        font-size: 12px;
        letter-spacing: 0;
        text-transform: none;
        max-width: 210px;
    }

    .chip.controlling {
        border-color: var(--accent);
    }

    .caret {
        font-size: 10px;
        color: var(--muted);
    }

    .popover {
        position: absolute;
        top: calc(100% + 6px);
        right: 0;
        width: 340px;
        z-index: 9;
        box-shadow: 0 6px 20px var(--backdrop);
    }

    .sub {
        font-family: var(--font-display);
        font-weight: 500;
        font-size: 13px;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        color: var(--muted);
        margin: 12px 0 4px;
    }

    .line {
        font-size: 13px;
        margin: 0 0 4px;
    }

    .confirm {
        margin-top: 12px;
        border-top: 1px solid var(--panel-edge);
        padding-top: 10px;
    }

    .check {
        display: flex;
        align-items: center;
        gap: 8px;
        text-transform: none;
        letter-spacing: 0.02em;
        font-family: var(--font-body);
        font-size: 13px;
        color: var(--text);
        margin: 8px 0;
    }

    .check input {
        width: auto;
    }

    .buttons {
        display: flex;
        justify-content: flex-end;
        gap: 8px;
        margin-top: 12px;
    }
</style>
