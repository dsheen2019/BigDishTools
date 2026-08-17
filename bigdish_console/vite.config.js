import { fileURLToPath, URL } from 'node:url'

import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// The dev server binds to loopback only: this UI is meant to run on the operator's own
// machine, not to be served to others. Production use is `vite build` + serve.py, which
// also binds loopback.
export default defineConfig({
    plugins: [vue()],
    resolve: {
        alias: {
            '@': fileURLToPath(new URL('./src', import.meta.url)),
            // The protocol client lives with its Python counterpart in the repo's
            // dish_client/ directory rather than inside this app, since it is not specific
            // to this UI.
            '@client': fileURLToPath(new URL('../dish_client', import.meta.url)),
        },
    },
    server: {
        host: '127.0.0.1',
        fs: {
            // ...so the dev server may read it from outside this app's root.
            allow: [fileURLToPath(new URL('..', import.meta.url))],
        },
        proxy: {
            // Same-origin TLE endpoint so the browser never talks to CelesTrak directly
            // (avoids CORS and keeps the door open for caching). serve.py implements the
            // identical endpoint, with a disk cache, for production use.
            '/tle': {
                target: 'https://celestrak.org',
                changeOrigin: true,
                rewrite: (path) => {
                    const catnr = new URLSearchParams(path.split('?')[1]).get('catnr')
                    return `/NORAD/elements/gp.php?CATNR=${encodeURIComponent(catnr)}&FORMAT=TLE`
                },
            },
        },
    },
})
