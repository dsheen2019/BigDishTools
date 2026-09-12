<script setup>
    // The sidebar's copy of the user list, visible from any tab without opening the session
    // menu. The list itself is polled by App.vue and drawn by UsersTable.
    import UsersTable from './UsersTable.vue';

    defineProps(['store']);
</script>

<template>
    <div class="panel">
        <h2 class="panel-title">Connected users</h2>
        <UsersTable :users="store.users" />
    </div>
</template>
