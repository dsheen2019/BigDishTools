import { fileURLToPath, URL } from 'node:url'

import { readFileSync } from 'node:fs'

import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// config.json deliberately does not live in public/, so that the build does not copy it into
// dist/ and leave two copies -- the one that gets edited and the one that gets served. In
// production serve.py serves it; in development this does, from the same file, so the two
// behave alike. BIGDISH_CONSOLE_CONFIG picks a different one, as --config does for serve.py.
function serveConfig() {
    const path = fileURLToPath(new URL(
        process.env.BIGDISH_CONSOLE_CONFIG ?? './config.json', import.meta.url))
    return {
        name: 'bigdish-console-config',
        configureServer(server) {
            server.middlewares.use('/config.json', (request, response) => {
                try {
                    // read per request, so an edit needs only a browser reload
                    const body = readFileSync(path)
                    JSON.parse(body)
                    response.setHeader('Content-Type', 'application/json')
                    response.setHeader('Cache-Control', 'no-store')
                    response.end(body)
                } catch (error) {
                    response.statusCode = error.code === 'ENOENT' ? 404 : 500
                    response.end(`${path}: ${error.message}`)
                }
            })
        },
    }
}

// The dev server binds to loopback only: this UI is meant to run on the operator's own
// machine, not to be served to others. Production use is `vite build` + serve.py, which
// also binds loopback.
export default defineConfig({
    plugins: [vue(), serveConfig()],
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
