<script setup>
    // Star chart, powered by the vendored VirtualSky (the same library behind the old
    // rci_interface star chart). The dish's current pointing is drawn as a pointer that
    // follows the ra/dec reported by the server; clicking the sky fills the coordinate
    // entry with the clicked ra/dec.
    //
    // The target in focus gets its rise-to-set path drawn over the chart, in VirtualSky's own
    // projection: we wrap the instance's drawImmediate so our overlay is repainted with
    // every redraw, using its azel2xy so the two always agree on where the sky is.
    //
    // VirtualSky is not a module: it hangs off the global `S` loaded in index.html.

    import { ref, watch, nextTick, onUnmounted } from 'vue';
    import { skyTrack } from '../lib/skytrack.js';
    import { makeAzElFunction } from '../lib/ephemeris.js';

    const props = defineProps(['store', 'config', 'visible']);
    const emit = defineEmits(['set-radec']);

    const TRACK_REFRESH_MS = 30000;

    // The chart flips with the theme -- VirtualSky has a "negative" palette for exactly this
    // -- so the overlay's colours come from the stylesheet rather than being fixed here.
    const colour = { track: '#8cc4ef', trackDim: 'rgba(140, 196, 239, 0.55)' };

    function readPalette() {
        const styles = getComputedStyle(document.documentElement);
        colour.track = styles.getPropertyValue('--track-live').trim() || colour.track;
        colour.trackDim = styles.getPropertyValue('--track-live-dim').trim() || colour.trackDim;
    }

    function applyTheme() {
        readPalette();
        if (!planetarium) return;
        planetarium.negative = props.store.theme === 'light';
        planetarium.updateColours();
        planetarium.drawImmediate();
    }

    const projectionChoice = ref('stereo');
    const PROJECTIONS = {
        stereo: 'Stereographic',
        polar: 'Polar',
        fisheye: 'Fisheye',
        orthographic: 'Orthographic',
    };

    const skyEl = ref(null);
    let planetarium = null;
    let pointerTimer = null;
    let trackTimer = null;
    let track = null;
    let focusAzElAt = null;

    function refreshTrack() {
        track = null;
        focusAzElAt = null;
        const focus = props.store.focus;
        if (focus?.spec) {
            try {
                focusAzElAt = makeAzElFunction(focus.spec, props.config.site);
                track = skyTrack(focusAzElAt, new Date(), props.config.map?.sky_track ?? {});
            } catch {
                track = null;
                focusAzElAt = null;
            }
        }
        planetarium?.draw();
    }

    // Draw the focused target's path on VirtualSky's canvas, after it has drawn itself.
    // azel2xy wants radians and expects the pan offset taken out, the same as VirtualSky's
    // own call sites; points outside the projection come back as (-1, -1), which breaks the
    // line rather than drawing a stray segment across the chart.
    function drawTrack() {
        if (!planetarium || !track?.points.length) return;
        const context = planetarium.c?.getContext('2d');
        if (!context) return;
        const d2r = Math.PI / 180;
        const project = (az, el) => {
            const point = planetarium.azel2xy(
                az * d2r - planetarium.az_off * planetarium.d2r, el * d2r,
                planetarium.wide, planetarium.tall);
            return planetarium.isPointBad(point) || !planetarium.isVisible(el * d2r)
                ? null : point;
        };

        context.save();
        context.lineWidth = 1.5;
        context.strokeStyle = colour.track;
        context.beginPath();
        let drawing = false;
        for (const p of track.points) {
            const point = project(p.az, p.el);
            if (!point) { drawing = false; continue; }
            if (drawing) context.lineTo(point.x, point.y);
            else context.moveTo(point.x, point.y);
            drawing = true;
        }
        context.stroke();

        // hour marks along the path, and the rise and set ends
        const spanS = (track.set - track.rise) / 1000;
        const tickS = spanS <= 900 ? 120 : spanS <= 3600 ? 600 : spanS <= 14400 ? 1800 : 3600;
        context.font = '10px "IBM Plex Mono"';
        context.fillStyle = colour.trackDim;
        context.textAlign = 'left';
        context.textBaseline = 'middle';
        for (let i = 1; i < track.points.length; i++) {
            const p = track.points[i];
            if (Math.floor(p.time.getTime() / 1000 / tickS)
                === Math.floor(track.points[i - 1].time.getTime() / 1000 / tickS)) continue;
            const point = project(p.az, p.el);
            if (!point) continue;
            context.beginPath();
            context.arc(point.x, point.y, 2, 0, 2 * Math.PI);
            context.fillStyle = colour.track;
            context.fill();
            context.fillStyle = colour.trackDim;
            context.fillText(
                p.time.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
                point.x + 5, point.y - 6);
        }

        const live = focusAzElAt?.(new Date());
        const livePoint = live && live.el > 0 ? project(live.az, live.el) : null;
        if (livePoint) {
            context.beginPath();
            context.arc(livePoint.x, livePoint.y, 4, 0, 2 * Math.PI);
            context.fillStyle = colour.track;
            context.fill();
            context.beginPath();
            context.arc(livePoint.x, livePoint.y, 9, 0, 2 * Math.PI);
            context.strokeStyle = colour.track;
            context.stroke();
            context.font = '600 12px "Barlow Condensed"';
            context.fillText(props.store.focus?.name ?? '', livePoint.x + 13, livePoint.y);
        }
        context.restore();
    }

    function init() {
        if (planetarium || !window.S) return;
        readPalette();
        planetarium = window.S.virtualsky({
            id: 'starmap',
            negative: props.store.theme === 'light',
            projection: projectionChoice.value,
            latitude: props.config.site.latitude,
            longitude: props.config.site.longitude,
            live: true,
            showplanets: true,
            showstarlabels: true,
            gridlines_az: true,
            cardinalpoints: true,
            constellations: true,
            showgalaxy: true,
            callback: {
                click: (event) => {
                    if (event.ra !== undefined && event.dec !== undefined) {
                        emit('set-radec', event.ra, event.dec);
                    }
                },
            },
        });
        planetarium.addPointer({
            ra: 0,
            dec: 0,
            label: 'dish',
            colour: '#e0562f',
            d: 6,
            html: '<div style="padding:4px 8px;color:#fff;">Current dish pointing</div>',
        });
        // Repaint the overlay with every redraw, whoever triggered it.
        const drawImmediate = planetarium.drawImmediate.bind(planetarium);
        planetarium.drawImmediate = (projection) => {
            const result = drawImmediate(projection);
            drawTrack();
            return result;
        };

        pointerTimer = setInterval(() => {
            if (!props.visible) return;
            if (props.store.radec) {
                planetarium.pointers[0].ra = props.store.radec.ra;
                planetarium.pointers[0].dec = props.store.radec.dec;
            }
            // also moves the target marker along its track
            planetarium.draw();
        }, 1000);
        refreshTrack();
        trackTimer = setInterval(refreshTrack, TRACK_REFRESH_MS);
    }

    // Bring the chart back after the tab was away. VirtualSky.resize() is not safe to call
    // while the container is hidden: it zeroes the canvas CSS before measuring, and when the
    // measurement comes back 0 its setWH() bails, so nothing restores the canvas and wide and
    // tall keep their old values -- which makes the next resize() return early as a no-op and
    // the chart stays blank for good. So measure only once the container is laid out again,
    // and set the size ourselves, which also repairs a chart already zeroed this way (by
    // VirtualSky's own window resize handler, say, while this tab was hidden).
    async function show() {
        await nextTick();
        if (!planetarium) {
            requestAnimationFrame(init);
            return;
        }
        requestAnimationFrame(() => {
            const width = skyEl.value?.offsetWidth ?? 0;
            const height = skyEl.value?.offsetHeight ?? 0;
            if (!width || !height) return;
            planetarium.setWH(width, height);
            planetarium.drawImmediate();
        });
    }

    watch(() => props.visible, (visible) => {
        if (visible) {
            show();
            // VirtualSky's live clock is a one second interval that redraws every star,
            // constellation and planet. It runs from startup whether or not anybody can see
            // it, so it is stopped while this tab is hidden.
            planetarium?.start();
        } else {
            planetarium?.stop();
        }
    }, { immediate: true });

    watch(projectionChoice, (choice) => {
        if (planetarium) {
            planetarium.selectProjection(choice);
            planetarium.draw();
        }
    });

    watch(() => props.store.focus, refreshTrack);
    watch(() => props.store.theme, applyTheme);

    onUnmounted(() => {
        clearInterval(pointerTimer);
        clearInterval(trackTimer);
    });
</script>

<template>
    <div class="sky-wrap">
        <div class="sky-controls">
            <label for="sky-projection">Projection</label>
            <select id="sky-projection" v-model="projectionChoice">
                <option v-for="(label, key) in PROJECTIONS" :key="key" :value="key">{{ label }}</option>
            </select>
            <span class="hint">Drag to look around · click a spot to load its ra/dec · double-click for fullscreen</span>
        </div>
        <div id="starmap" ref="skyEl"></div>
    </div>
</template>

<style scoped>
    .sky-wrap {
        flex: 1;
        min-height: 0;
        display: flex;
        flex-direction: column;
        gap: 8px;
    }

    .sky-controls {
        display: flex;
        align-items: center;
        gap: 8px;
    }

    .sky-controls select {
        width: 160px;
    }

    .hint {
        font-size: 12px;
        color: var(--muted);
        margin-left: auto;
    }

    #starmap {
        flex: 1;
        min-height: 0;
        background: var(--sky-bg);
        border-radius: 6px;
        overflow: hidden;
    }
</style>
