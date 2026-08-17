import "./assets/main.css";

import { createApp } from "vue";
import App from "./App.vue";

async function start() {
    const config = await (await fetch("config.json")).json();
    createApp(App, { config }).mount("#app");
}

start();
