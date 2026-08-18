<script setup>
    // The diagnostics tab: where the dish has been, how far off target it was, and what the
    // motors were drawing, over the last hour.
    //
    // Position and error on the left, the two motor plots on the right. The error plots are
    // the point of the tab -- their bounds are deliberately tight (config.toml,
    // diagnostics.error_limit_deg) so that a tracking residual of a few hundredths of a degree
    // is visible, which it would not be on an axis scaled to a slew.

    import { computed, watch, nextTick } from 'vue';
    import TimeSeriesPlot from './TimeSeriesPlot.vue';

    const props = defineProps(['store', 'config', 'history', 'visible']);

    // Collected through a function ref rather than by giving all four the same ref name: Vue
    // only builds an array of refs inside a v-for, so four static components sharing a name
    // would leave only the last, and refreshing them all would fail on the rest.
    const plots = [];
    const collectPlot = (plot) => {
        if (plot && !plots.includes(plot)) plots.push(plot);
    };
    const diagnostics = props.config.diagnostics ?? {};
    const windowSeconds = (diagnostics.window_minutes ?? 60) * 60;
    const errorLimit = diagnostics.error_limit_deg ?? 3.0;
    const velocityErrorLimit = diagnostics.velocity_error_limit_dps ?? 0.5;
    const redrawSeconds = diagnostics.redraw_seconds ?? 5;
    const azRange = props.config.dish?.az_range ?? [0, 360];
    const elRange = props.config.dish?.el_range ?? [0, 90];

    // Commanded drawn dotted, behind measured: on any well behaved track the two sit on top
    // of each other, so they have to be told apart by line style rather than by position.
    const positionSeries = [
        { field: 'azCommanded', label: 'az cmd', colour: '--trace-az', dash: [3, 3] },
        { field: 'elCommanded', label: 'el cmd', colour: '--trace-el', dash: [3, 3] },
        { field: 'az', label: 'az', colour: '--trace-az' },
        { field: 'el', label: 'el', colour: '--trace-el' },
    ];
    const errorSeries = [
        { field: 'azError', label: 'az error', colour: '--trace-az' },
        { field: 'elError', label: 'el error', colour: '--trace-el' },
    ];
    const velocityErrorSeries = [
        { field: 'azVelError', label: 'az rate error', colour: '--trace-az' },
        { field: 'elVelError', label: 'el rate error', colour: '--trace-el' },
    ];
    const voltageSeries = [
        { field: 'azVoltage', label: 'az', colour: '--trace-az' },
        { field: 'elVoltage', label: 'el', colour: '--trace-el' },
    ];
    const currentSeries = [
        { field: 'azCurrent', label: 'az', colour: '--trace-az' },
        { field: 'elCurrent', label: 'el', colour: '--trace-el' },
    ];

    // The two position plots share one axis pair covering the dish's travel, so the trace
    // keeps its place on the axis instead of the scale moving under it.
    const positionBounds = { low: Math.min(azRange[0], elRange[0]), high: Math.max(azRange[1], elRange[1]) };
    const errorBounds = { low: -errorLimit, high: errorLimit };
    const velocityErrorBounds = { low: -velocityErrorLimit, high: velocityErrorLimit };

    const status = computed(() => {
        const span = props.history.span;
        if (!span) {
            return 'Waiting for telemetry.';
        }
        const minutes = (span.to - span.from) / 60;
        const collected = minutes < 1
            ? `${Math.round((span.to - span.from))} s of telemetry`
            : `${minutes.toFixed(minutes < 10 ? 1 : 0)} min of telemetry`;
        return props.history.has('azError')
            ? `${collected}; error is measured against where the dish was told to be at each readback.`
            : `${collected}; no error to show until something is commanded.`;
    });

    // The tab is hidden rather than unmounted, so nothing is measured while it has no size:
    // wait for the layout, as the star chart has to.
    watch(() => props.visible, async (visible) => {
        if (!visible) return;
        await nextTick();
        requestAnimationFrame(() => plots.forEach((plot) => plot?.refresh()));
    });

    watch(() => props.store.theme, () => plots.forEach((plot) => plot?.refresh()));
</script>

<template>
    <div class="diagnostics">
        <div class="grid">
            <TimeSeriesPlot class="left-1" :ref="collectPlot" :history="history" title="Position" unit="deg"
                            :series="positionSeries" :bounds="positionBounds"
                            :window-seconds="windowSeconds" :visible="visible" :redraw-seconds="redrawSeconds" />
            <TimeSeriesPlot class="left-2" :ref="collectPlot" :history="history" title="Pointing error" unit="deg"
                            :series="errorSeries" :bounds="errorBounds" zero-line
                            :window-seconds="windowSeconds" :visible="visible" :redraw-seconds="redrawSeconds" />
            <TimeSeriesPlot class="left-3" :ref="collectPlot" :history="history" title="Rate error" unit="deg/s"
                            :series="velocityErrorSeries" :bounds="velocityErrorBounds" zero-line
                            :window-seconds="windowSeconds" :visible="visible" :redraw-seconds="redrawSeconds" />
            <TimeSeriesPlot class="right-1" :ref="collectPlot" :history="history" title="Motor voltage" unit="V"
                            :series="voltageSeries" :bounds="null"
                            :window-seconds="windowSeconds" :visible="visible" :redraw-seconds="redrawSeconds" />
            <TimeSeriesPlot class="right-2" :ref="collectPlot" :history="history" title="Motor current" unit="A"
                            :series="currentSeries" :bounds="null"
                            :window-seconds="windowSeconds" :visible="visible" :redraw-seconds="redrawSeconds" />
        </div>
        <p class="status">{{ status }}</p>
    </div>
</template>

<style scoped>
    .diagnostics {
        flex: 1;
        min-height: 0;
        display: flex;
        flex-direction: column;
        gap: 8px;
    }

    /* Three pointing plots on the left against two motor plots on the right, so the rows are
     * sixths: the left column takes two each, the right column three each, and both columns
     * still reach the bottom. */
    .grid {
        flex: 1;
        min-height: 0;
        display: grid;
        grid-template-columns: 1fr 1fr;
        grid-template-rows: repeat(6, minmax(0, 1fr));
        gap: 10px;
    }

    .left-1 { grid-column: 1; grid-row: 1 / 3; }
    .left-2 { grid-column: 1; grid-row: 3 / 5; }
    .left-3 { grid-column: 1; grid-row: 5 / 7; }
    .right-1 { grid-column: 2; grid-row: 1 / 4; }
    .right-2 { grid-column: 2; grid-row: 4 / 7; }

    .status {
        margin: 0;
        font-size: 12px;
        color: var(--muted);
    }

    @media (max-width: 900px) {
        .grid {
            grid-template-columns: 1fr;
            grid-template-rows: repeat(5, minmax(140px, 1fr));
        }

        .left-1, .left-2, .left-3, .right-1, .right-2 {
            grid-column: 1;
            grid-row: auto;
        }
    }
</style>
