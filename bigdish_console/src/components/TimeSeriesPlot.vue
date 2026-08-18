<script setup>
    // One diagnostics plot: a time axis running back over the window, one or two series drawn
    // from the telemetry history, and either fixed bounds or autoscale.
    //
    // Drawn on canvas like the other charts here, rather than with a plotting library, so the
    // app keeps no runtime dependencies, works offline, and looks like the rest of the
    // console. Each pixel column shows the range of the samples in it (see history.js), so a
    // brief spike survives being thinned to the plot's width.

    import { ref, onMounted, onUnmounted, watch } from 'vue';

    const props = defineProps({
        history: Object,
        title: String,
        unit: String,
        // [{field, label, colour}]
        series: Array,
        // {low, high} to fix the axis, or null to scale to the data
        bounds: Object,
        windowSeconds: Number,
        // draw a line at zero, for the error plots
        zeroLine: Boolean,
    });

    const canvasEl = ref(null);
    const wrapEl = ref(null);

    const PALETTE = {
        text: '--text',
        muted: '--muted',
        grid: '--chart-scale',
        panel: '--panel-inset',
        edge: '--panel-edge',
    };
    const colour = {};

    function readPalette() {
        const styles = getComputedStyle(document.documentElement);
        for (const [name, variable] of Object.entries(PALETTE)) {
            colour[name] = styles.getPropertyValue(variable).trim();
        }
        for (const entry of props.series) {
            colour[entry.field] = styles.getPropertyValue(entry.colour).trim() || '#888';
        }
    }

    let drawQueued = false;
    function scheduleDraw() {
        if (drawQueued) return;
        drawQueued = true;
        requestAnimationFrame(() => {
            drawQueued = false;
            draw();
        });
    }

    function niceStep(range, target) {
        const rough = range / target;
        const magnitude = 10 ** Math.floor(Math.log10(rough));
        for (const multiple of [1, 2, 2.5, 5, 10]) {
            if (magnitude * multiple >= rough) return magnitude * multiple;
        }
        return magnitude * 10;
    }

    function draw() {
        const canvas = canvasEl.value;
        if (!canvas || !wrapEl.value) return;
        const rect = wrapEl.value.getBoundingClientRect();
        if (rect.width < 60 || rect.height < 40) return;

        const dpr = window.devicePixelRatio || 1;
        canvas.width = Math.round(rect.width * dpr);
        canvas.height = Math.round(rect.height * dpr);
        canvas.style.width = `${rect.width}px`;
        canvas.style.height = `${rect.height}px`;
        const ctx = canvas.getContext('2d');
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        ctx.clearRect(0, 0, rect.width, rect.height);

        const left = 52;
        const right = 8;
        const top = 20;
        const bottom = 20;
        const plotWidth = rect.width - left - right;
        const plotHeight = rect.height - top - bottom;
        if (plotWidth < 30 || plotHeight < 20) return;

        // --- the window, which ends now and runs back however far was asked for ---
        const span = props.history.span;
        const to = span ? span.to : Date.now() / 1000;
        const from = to - props.windowSeconds;

        const fields = props.series.map((entry) => entry.field);
        const bounds = props.bounds ?? props.history.extent(fields, from, to);

        ctx.fillStyle = colour.panel;
        ctx.fillRect(left, top, plotWidth, plotHeight);
        ctx.strokeStyle = colour.edge;
        ctx.lineWidth = 1;
        ctx.strokeRect(left + 0.5, top + 0.5, plotWidth - 1, plotHeight - 1);

        ctx.font = '600 11px "Barlow Condensed"';
        ctx.fillStyle = colour.muted;
        ctx.textAlign = 'left';
        ctx.textBaseline = 'top';
        ctx.fillText(props.unit ? `${props.title}  (${props.unit})` : props.title, left, 4);

        if (!bounds) {
            ctx.font = '11px "IBM Plex Mono"';
            ctx.fillStyle = colour.muted;
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';
            ctx.fillText('no data yet', left + plotWidth / 2, top + plotHeight / 2);
            drawLegend(ctx, rect, left);
            return;
        }

        const yOf = (value) =>
            top + plotHeight * (1 - (value - bounds.low) / (bounds.high - bounds.low));
        const xOf = (fraction) => left + fraction * plotWidth;

        // --- gridlines and labels ---
        ctx.font = '10px "IBM Plex Mono"';
        ctx.textAlign = 'right';
        ctx.textBaseline = 'middle';
        const step = niceStep(bounds.high - bounds.low, 4);
        const decimals = step < 0.1 ? 2 : step < 1 ? 1 : 0;
        for (let value = Math.ceil(bounds.low / step) * step; value <= bounds.high; value += step) {
            const y = yOf(value);
            ctx.strokeStyle = colour.grid;
            ctx.beginPath();
            ctx.moveTo(left, Math.round(y) + 0.5);
            ctx.lineTo(left + plotWidth, Math.round(y) + 0.5);
            ctx.stroke();
            ctx.fillStyle = colour.muted;
            ctx.fillText(value.toFixed(decimals), left - 6, y);
        }

        if (props.zeroLine && bounds.low < 0 && bounds.high > 0) {
            ctx.strokeStyle = colour.muted;
            ctx.beginPath();
            ctx.moveTo(left, Math.round(yOf(0)) + 0.5);
            ctx.lineTo(left + plotWidth, Math.round(yOf(0)) + 0.5);
            ctx.stroke();
        }

        // minutes ago, which is what you actually want to know when something twitched
        ctx.textAlign = 'center';
        ctx.textBaseline = 'top';
        const minutes = props.windowSeconds / 60;
        const minuteStep = minutes <= 5 ? 1 : minutes <= 20 ? 5 : minutes <= 70 ? 10 : 30;
        for (let ago = 0; ago <= minutes; ago += minuteStep) {
            const x = xOf(1 - ago / minutes);
            ctx.strokeStyle = colour.grid;
            ctx.beginPath();
            ctx.moveTo(Math.round(x) + 0.5, top);
            ctx.lineTo(Math.round(x) + 0.5, top + plotHeight);
            ctx.stroke();
            ctx.fillStyle = colour.muted;
            ctx.fillText(ago === 0 ? 'now' : `-${ago}m`, x, top + plotHeight + 4);
        }

        // --- the series ---
        const columns = Math.max(1, Math.round(plotWidth));
        for (const entry of props.series) {
            const buckets = props.history.decimate(entry.field, from, to, columns);
            if (buckets.length === 0) continue;

            // Where a bucket runs past the axis, mark the column at the edge instead of
            // clamping silently, so a slew reads as off the scale rather than as a steady
            // error sitting exactly on the bound.
            ctx.strokeStyle = colour[entry.field];
            ctx.lineWidth = 1.25;
            ctx.beginPath();
            let drawing = false;
            for (const bucket of buckets) {
                const x = xOf(bucket.x);
                const yMin = yOf(Math.max(bucket.min, bounds.low));
                const yMax = yOf(Math.min(bucket.max, bounds.high));
                if (!drawing) {
                    ctx.moveTo(x, yMax);
                    drawing = true;
                } else {
                    ctx.lineTo(x, yMax);
                }
                if (yMin !== yMax) ctx.lineTo(x, yMin);
            }
            ctx.stroke();

            ctx.fillStyle = colour[entry.field];
            for (const bucket of buckets) {
                if (bucket.max > bounds.high) {
                    ctx.fillRect(xOf(bucket.x) - 0.5, top + 1, 1.5, 3);
                }
                if (bucket.min < bounds.low) {
                    ctx.fillRect(xOf(bucket.x) - 0.5, top + plotHeight - 4, 1.5, 3);
                }
            }
        }

        drawLegend(ctx, rect, left);
    }

    function drawLegend(ctx, rect, left) {
        ctx.font = '10px "IBM Plex Mono"';
        ctx.textAlign = 'right';
        ctx.textBaseline = 'top';
        let x = rect.width - 8;
        for (const entry of [...props.series].reverse()) {
            const width = ctx.measureText(entry.label).width;
            ctx.fillStyle = colour[entry.field];
            ctx.fillText(entry.label, x, 4);
            ctx.fillRect(x - width - 12, 9, 8, 2);
            x -= width + 20;
        }
    }

    let resizeObserver = null;
    let timer = null;
    let lastVersion = -1;

    onMounted(() => {
        readPalette();
        resizeObserver = new ResizeObserver(scheduleDraw);
        resizeObserver.observe(wrapEl.value);
        // redrawing on every sample would be five times a second for no benefit: a plot an
        // hour wide moves by a pixel every few seconds
        timer = setInterval(() => {
            if (props.history.version !== lastVersion) {
                lastVersion = props.history.version;
                scheduleDraw();
            }
        }, 1000);
        scheduleDraw();
    });

    onUnmounted(() => {
        resizeObserver?.disconnect();
        clearInterval(timer);
    });

    defineExpose({ refresh: () => { readPalette(); scheduleDraw(); } });
</script>

<template>
    <div ref="wrapEl" class="plot">
        <canvas ref="canvasEl"></canvas>
    </div>
</template>

<style scoped>
    .plot {
        position: relative;
        flex: 1;
        min-height: 0;
    }

    canvas {
        position: absolute;
        inset: 0;
    }
</style>
