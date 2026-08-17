<script setup>
    // The azimuth chart: the static regional map presented as a circular polar plot, the
    // way antenna patterns are drawn -- paper disc, polar graticule, degree ring, and the
    // dish's azimuth as an ink needle. Map image and projection come from
    // tools/generate_map.py via map.png + map_meta.json.

    import { ref, onMounted, onUnmounted, watch } from 'vue';
    import { makeProjection, azimuthPathPixels, initialBearing, haversineDistance, METERS_PER_MILE } from '../lib/projection.js';
    import { makeInverseProjection } from '../lib/projection_inverse.js';
    import { skyTrack } from '../lib/skytrack.js';
    import { makeAzElFunction } from '../lib/ephemeris.js';

    const props = defineProps(['store', 'config', 'targets']);
    const emit = defineEmits(['set-azimuth']);

    const canvasEl = ref(null);
    const wrapEl = ref(null);
    const loadError = ref('');

    const INK = '#232830';
    const PAPER = '#f2efe6';
    const GRID = 'rgba(70, 90, 115, 0.30)';
    const SIGNAL = '#e0562f';
    const BEAM = 'rgba(63, 174, 148, 0.30)';
    const TRACK = '#2f5d8e';                       // the target's sky path, on cream paper
    const TRACK_DIM = 'rgba(47, 93, 142, 0.45)';   // its elevation guides and tick labels
    const TRACK_REFRESH_MS = 30000;

    // The colours above are the chart paper itself and stay put in both themes. Everything
    // drawn around it -- the degree ring, the elevation quadrant, the hover readout, the
    // attribution, the target line -- follows the theme, and comes from the stylesheet so
    // there is one source of truth for both.
    const PALETTE = {
        label: '--muted',
        readout: '--text',
        ringTick: '--chart-ring-tick',
        scale: '--chart-scale',
        accent: '--accent',
        live: '--track-live',
    };
    const colour = { label: '#838b96', readout: '#cfd3d9',
        ringTick: 'rgba(131, 139, 150, 0.45)', scale: 'rgba(131, 139, 150, 0.6)',
        accent: '#3fae94', live: '#8cc4ef' };

    function readPalette() {
        const styles = getComputedStyle(document.documentElement);
        for (const [name, variable] of Object.entries(PALETTE)) {
            colour[name] = styles.getPropertyValue(variable).trim() || colour[name];
        }
    }

    let meta = null;
    let projection = null;
    let inverse = null;
    let mapImage = null;
    let hover = null; // {bearing, distanceMiles, x, y}
    let stationMarkers = []; // {x, y (canvas), name, bearing}
    let drawQueued = false;

    // Sky path of the target in focus (store.focus), sampled on a timer; its position now is
    // computed on every draw.
    let track = null;
    let focusAzElAt = null;
    let trackTimer = null;

    // Geometry recomputed each draw: center, disc radius, and the map-pixel <-> canvas
    // transform.
    let geom = null;

    function scheduleDraw() {
        if (drawQueued) return;
        drawQueued = true;
        requestAnimationFrame(() => {
            drawQueued = false;
            draw();
        });
    }

    function mapToCanvas(p) {
        const scale = (2 * geom.disc) / meta.image_size_px;
        return {
            x: geom.cx - geom.disc + p.x * scale,
            y: geom.cy - geom.disc + p.y * scale,
        };
    }

    function canvasToMapPixel(x, y) {
        const scale = meta.image_size_px / (2 * geom.disc);
        return {
            x: (x - (geom.cx - geom.disc)) * scale,
            y: (y - (geom.cy - geom.disc)) * scale,
        };
    }

    function refreshTrack() {
        track = null;
        focusAzElAt = null;
        const focus = props.store.focus;
        if (focus?.spec) {
            try {
                focusAzElAt = makeAzElFunction(focus.spec, props.config.site);
                track = skyTrack(focusAzElAt, new Date(), props.config.map?.sky_track ?? {});
            } catch {
                // a bad TLE or spec just means no overlay; the target panel reports the error
                track = null;
                focusAzElAt = null;
            }
        }
        scheduleDraw();
    }

    // Where a target sits in the polar sky plot laid over the chart: azimuth is shared with
    // the map beneath, and radius is zenith angle, so the middle is overhead and the rim is
    // the horizon -- which is also, conveniently, where the map's own outer range ring is.
    function skyToCanvas(az, el) {
        const r = (geom.disc * (90 - Math.max(0, Math.min(90, el)))) / 90;
        const angle = ((az - 90) * Math.PI) / 180;
        return { x: geom.cx + r * Math.cos(angle), y: geom.cy + r * Math.sin(angle) };
    }

    // The focused target's path from rise to set, drawn in that sky plot. Unlike the ground
    // beneath it this is angular, so it works the same for a satellite pass, the moon, or a
    // calibrator source -- and the dish's azimuth needle lines up with it directly.
    function drawSkyTrack(ctx) {
        if (!track?.points.length) return;

        // elevation guides, so the radial axis can be read as angle rather than miles
        ctx.setLineDash([2, 4]);
        ctx.strokeStyle = TRACK_DIM;
        ctx.lineWidth = 1;
        for (const el of [30, 60]) {
            const r = (geom.disc * (90 - el)) / 90;
            ctx.beginPath();
            ctx.arc(geom.cx, geom.cy, r, 0, 2 * Math.PI);
            ctx.stroke();
        }
        ctx.setLineDash([]);

        // and the scale itself, on the radial opposite the range labels so the two ways of
        // reading the same radius never sit on top of each other
        const axisAngle = ((330 - 90) * Math.PI) / 180;
        const across = axisAngle + Math.PI / 2;
        ctx.font = '10px "IBM Plex Mono"';
        ctx.fillStyle = TRACK_DIM;
        ctx.strokeStyle = TRACK_DIM;
        ctx.textAlign = 'right';
        ctx.textBaseline = 'middle';
        for (let el = 15; el <= 75; el += 15) {
            const r = (geom.disc * (90 - el)) / 90;
            const x = geom.cx + r * Math.cos(axisAngle);
            const y = geom.cy + r * Math.sin(axisAngle);
            ctx.beginPath();
            ctx.moveTo(x - 3 * Math.cos(across), y - 3 * Math.sin(across));
            ctx.lineTo(x + 3 * Math.cos(across), y + 3 * Math.sin(across));
            ctx.stroke();
            ctx.fillText(`${el}°`, x - 6, y);
        }

        // the path itself
        ctx.beginPath();
        track.points.forEach((p, i) => {
            const c = skyToCanvas(p.az, p.el);
            if (i === 0) ctx.moveTo(c.x, c.y);
            else ctx.lineTo(c.x, c.y);
        });
        ctx.strokeStyle = TRACK;
        ctx.lineWidth = 1.5;
        ctx.stroke();

        // clock ticks: often enough to read the pass, sparse enough not to crowd it
        const spanS = (track.set - track.rise) / 1000;
        const tickS = spanS <= 900 ? 120 : spanS <= 3600 ? 600 : spanS <= 14400 ? 1800 : 3600;
        ctx.font = '9px "IBM Plex Mono"';
        ctx.textAlign = 'left';
        for (let i = 1; i < track.points.length; i++) {
            const p = track.points[i];
            const crossed = Math.floor(p.time.getTime() / 1000 / tickS)
                !== Math.floor(track.points[i - 1].time.getTime() / 1000 / tickS);
            if (!crossed) continue;
            const c = skyToCanvas(p.az, p.el);
            ctx.beginPath();
            ctx.arc(c.x, c.y, 1.8, 0, 2 * Math.PI);
            ctx.fillStyle = TRACK;
            ctx.fill();
            ctx.fillStyle = TRACK_DIM;
            ctx.fillText(
                p.time.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
                c.x + 4, c.y - 5);
        }

        // rise and set, unless it never sets
        if (!track.circumpolar) {
            ctx.font = '600 10px "Barlow Condensed"';
            for (const [label, point] of [['rise', track.points[0]],
                ['set', track.points[track.points.length - 1]]]) {
                const c = skyToCanvas(point.az, point.el);
                const inward = 0.93;
                const x = geom.cx + (c.x - geom.cx) * inward;
                const y = geom.cy + (c.y - geom.cy) * inward;
                ctx.beginPath();
                ctx.arc(x, y, 3.5, 0, 2 * Math.PI);
                ctx.strokeStyle = TRACK;
                ctx.lineWidth = 1.5;
                ctx.stroke();
                ctx.fillStyle = TRACK;
                ctx.textAlign = x > geom.cx ? 'right' : 'left';
                ctx.fillText(`${label} ${point.time.toLocaleTimeString([],
                    { hour: '2-digit', minute: '2-digit' })}`,
                    x + (x > geom.cx ? -7 : 7), y);
            }
        }

        // where it is now, recomputed rather than taken from the samples
        const live = focusAzElAt?.(new Date());
        if (!live || live.el <= 0) return;
        const c = skyToCanvas(live.az, live.el);
        ctx.beginPath();
        ctx.arc(c.x, c.y, 4, 0, 2 * Math.PI);
        ctx.fillStyle = TRACK;
        ctx.fill();
        ctx.beginPath();
        ctx.arc(c.x, c.y, 8.5, 0, 2 * Math.PI);
        ctx.strokeStyle = TRACK;
        ctx.lineWidth = 1.5;
        ctx.stroke();
        ctx.font = '600 11px "Barlow Condensed"';
        ctx.textAlign = 'left';
        ctx.fillText(props.store.focus?.name ?? '', c.x + 12, c.y + 1);
    }

    // A caret on the degree ring at the target's azimuth now, tying the sky plot to the
    // chart's own azimuth scale.
    function drawAzimuthCaret(ctx, cx, cy, outer, ringWidth) {
        const live = focusAzElAt?.(new Date());
        if (!live || live.el <= 0) return;
        const angle = ((live.az - 90) * Math.PI) / 180;
        const tip = outer - ringWidth;
        ctx.beginPath();
        ctx.moveTo(cx + tip * Math.cos(angle), cy + tip * Math.sin(angle));
        ctx.lineTo(cx + (tip + 9) * Math.cos(angle - 0.035),
            cy + (tip + 9) * Math.sin(angle - 0.035));
        ctx.lineTo(cx + (tip + 9) * Math.cos(angle + 0.035),
            cy + (tip + 9) * Math.sin(angle + 0.035));
        ctx.closePath();
        ctx.fillStyle = colour.live;
        ctx.fill();
    }

    // One line, top right: where the focused target is, or when it comes up.
    function focusSummary() {
        const name = props.store.focus?.name;
        if (!name || !focusAzElAt) return null;
        const live = focusAzElAt(new Date());
        if (!live) return `${name}  no position solution`;
        const clock = (date) =>
            date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        if (live.el > 0) {
            const sets = track && !track.circumpolar ? `  sets ${clock(track.set)}` : '';
            return `${name}  az ${live.az.toFixed(1)}°  el ${live.el.toFixed(1)}°${sets}`;
        }
        if (!track?.rise) {
            const hours = props.config.map?.sky_track?.max_hours ?? 24;
            return `${name}  below horizon, no pass within ${hours} h`;
        }
        return `${name}  below horizon, rises ${clock(track.rise)} at `
            + `az ${track.points[0].az.toFixed(0)}°, peak el ${track.peak.el.toFixed(0)}°`;
    }

    function drawAzimuthPath(ctx, azimuth, fraction = 1.0) {
        const points = azimuthPathPixels(
            meta, projection, azimuth, meta.radius_miles * METERS_PER_MILE * fraction);
        ctx.beginPath();
        points.forEach((p, i) => {
            const c = mapToCanvas(p);
            if (i === 0) ctx.moveTo(c.x, c.y);
            else ctx.lineTo(c.x, c.y);
        });
        ctx.stroke();
        return points.map(mapToCanvas);
    }

    function draw() {
        const canvas = canvasEl.value;
        if (!canvas || !wrapEl.value) return;
        const rect = wrapEl.value.getBoundingClientRect();
        if (rect.width < 40 || rect.height < 40) return;
        const dpr = window.devicePixelRatio || 1;
        canvas.width = Math.round(rect.width * dpr);
        canvas.height = Math.round(rect.height * dpr);
        canvas.style.width = `${rect.width}px`;
        canvas.style.height = `${rect.height}px`;
        const ctx = canvas.getContext('2d');
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        ctx.clearRect(0, 0, rect.width, rect.height);

        const cx = rect.width / 2;
        const cy = rect.height / 2;
        const outer = Math.min(rect.width, rect.height) / 2 - 6;
        const ringWidth = 30;
        const disc = outer - ringWidth - 6;
        geom = { cx, cy, disc };
        if (disc < 60) return;

        // --- degree ring ---
        // Left unpainted, so the panel behind shows through exactly rather than being
        // matched to it: only the ticks and figures mark the ring out.

        for (let d = 0; d < 360; d += 2) {
            const major = d % 30 === 0;
            const medium = d % 10 === 0;
            const angle = ((d - 90) * Math.PI) / 180;
            const r1 = outer - ringWidth + 2;
            const len = major ? 10 : medium ? 7 : 4;
            ctx.beginPath();
            ctx.moveTo(cx + r1 * Math.cos(angle), cy + r1 * Math.sin(angle));
            ctx.lineTo(cx + (r1 + len) * Math.cos(angle), cy + (r1 + len) * Math.sin(angle));
            ctx.strokeStyle = major ? colour.label : colour.ringTick;
            ctx.lineWidth = major ? 1.5 : 1;
            ctx.stroke();
        }
        ctx.fillStyle = colour.label;
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        for (let d = 0; d < 360; d += 30) {
            const angle = ((d - 90) * Math.PI) / 180;
            const r = outer - 8;
            const cardinal = { 0: 'N', 90: 'E', 180: 'S', 270: 'W' }[d];
            ctx.font = cardinal ? '600 14px "Barlow Condensed"' : '500 12px "Barlow Condensed"';
            ctx.fillStyle = cardinal ? colour.readout : colour.label;
            ctx.fillText(cardinal ?? String(d), cx + r * Math.cos(angle), cy + r * Math.sin(angle));
        }

        // --- paper disc with map ---
        ctx.save();
        ctx.beginPath();
        ctx.arc(cx, cy, disc, 0, 2 * Math.PI);
        ctx.fillStyle = PAPER;
        ctx.fill();
        ctx.clip();
        if (mapImage) {
            ctx.drawImage(mapImage, 0, 0, meta.image_size_px, meta.image_size_px,
                cx - disc, cy - disc, 2 * disc, 2 * disc);
            // cream wash to pull the tiles toward chart paper
            ctx.fillStyle = 'rgba(242, 239, 230, 0.30)';
            ctx.fillRect(cx - disc, cy - disc, 2 * disc, 2 * disc);
        }

        // polar graticule: range rings + radials, like pattern-plot paper
        const ringStepMiles = meta.radius_miles > 150 ? 50 : 25;
        ctx.strokeStyle = GRID;
        ctx.lineWidth = 1;
        for (let miles = ringStepMiles; miles <= meta.radius_miles; miles += ringStepMiles) {
            ctx.beginPath();
            ctx.arc(cx, cy, (miles / meta.radius_miles) * disc, 0, 2 * Math.PI);
            ctx.stroke();
        }
        for (let d = 0; d < 360; d += 30) {
            const angle = ((d - 90) * Math.PI) / 180;
            ctx.beginPath();
            ctx.moveTo(cx, cy);
            ctx.lineTo(cx + disc * Math.cos(angle), cy + disc * Math.sin(angle));
            ctx.stroke();
        }
        ctx.font = '10px "IBM Plex Mono"';
        ctx.fillStyle = 'rgba(70, 90, 115, 0.7)';
        const labelAngle = ((150 - 90) * Math.PI) / 180;
        for (let miles = ringStepMiles; miles < meta.radius_miles; miles += ringStepMiles) {
            const r = (miles / meta.radius_miles) * disc;
            ctx.fillText(`${miles}`, cx + (r + 1) * Math.cos(labelAngle) + 8, cy + r * Math.sin(labelAngle));
        }

        // --- station markers ---
        stationMarkers = [];
        ctx.font = '600 11px "Barlow Condensed"';
        for (const target of props.targets) {
            if (target.latitude === undefined) continue;
            const c = mapToCanvas(projection.latLonToPixel(target.latitude, target.longitude));
            const inside = Math.hypot(c.x - cx, c.y - cy) <= disc - 4;
            if (!inside) continue;
            stationMarkers.push({ x: c.x, y: c.y, name: target.name, bearing: target.coord1 });
            ctx.beginPath();
            ctx.arc(c.x, c.y, 3.5, 0, 2 * Math.PI);
            ctx.fillStyle = INK;
            ctx.fill();
            ctx.beginPath();
            ctx.arc(c.x, c.y, 6.5, 0, 2 * Math.PI);
            ctx.strokeStyle = INK;
            ctx.lineWidth = 1;
            ctx.stroke();
            ctx.fillStyle = INK;
            ctx.textAlign = 'left';
            ctx.fillText(target.name.split(' ')[0], c.x + 9, c.y + 1);
        }

        drawSkyTrack(ctx);

        // --- beam wedge and needles ---
        const currentAz = props.store.azel?.az;
        const commandedAz = props.store.commandedAzEl?.az;
        const beamwidth = props.config.dish.beamwidth_deg;

        if (currentAz !== undefined && currentAz !== null) {
            // beam wedge: the great-circle edges at az +/- half the beamwidth
            const left = azimuthPathPixels(meta, projection, currentAz - beamwidth / 2,
                meta.radius_miles * METERS_PER_MILE).map(mapToCanvas);
            const right = azimuthPathPixels(meta, projection, currentAz + beamwidth / 2,
                meta.radius_miles * METERS_PER_MILE).map(mapToCanvas);
            ctx.beginPath();
            left.forEach((p, i) => (i === 0 ? ctx.moveTo(p.x, p.y) : ctx.lineTo(p.x, p.y)));
            right.reverse().forEach((p) => ctx.lineTo(p.x, p.y));
            ctx.closePath();
            ctx.fillStyle = BEAM;
            ctx.fill();
        }

        if (commandedAz !== undefined && commandedAz !== null) {
            ctx.strokeStyle = SIGNAL;
            ctx.lineWidth = 1.5;
            ctx.setLineDash([6, 5]);
            drawAzimuthPath(ctx, commandedAz);
            ctx.setLineDash([]);
        }

        if (currentAz !== undefined && currentAz !== null) {
            ctx.strokeStyle = INK;
            ctx.lineWidth = 2.5;
            const path = drawAzimuthPath(ctx, currentAz);
            const tip = path[path.length - 1];
            const prev = path[path.length - 2];
            const angle = Math.atan2(tip.y - prev.y, tip.x - prev.x);
            ctx.beginPath();
            ctx.moveTo(tip.x, tip.y);
            ctx.lineTo(tip.x - 11 * Math.cos(angle - 0.32), tip.y - 11 * Math.sin(angle - 0.32));
            ctx.lineTo(tip.x - 11 * Math.cos(angle + 0.32), tip.y - 11 * Math.sin(angle + 0.32));
            ctx.closePath();
            ctx.fillStyle = INK;
            ctx.fill();
        }

        // center: the dish
        ctx.beginPath();
        ctx.arc(cx, cy, 4, 0, 2 * Math.PI);
        ctx.fillStyle = INK;
        ctx.fill();
        ctx.beginPath();
        ctx.arc(cx, cy, 8, 0, 2 * Math.PI);
        ctx.strokeStyle = INK;
        ctx.lineWidth = 1.5;
        ctx.stroke();
        ctx.restore();

        drawAzimuthCaret(ctx, cx, cy, outer, ringWidth);

        // --- elevation quadrant, lower-left on the console ---
        drawElevation(ctx, rect);

        // hover readout + attribution, corners
        ctx.textAlign = 'right';
        ctx.textBaseline = 'bottom';
        const summary = focusSummary();
        if (summary) {
            ctx.textBaseline = 'top';
            ctx.font = '12px "IBM Plex Mono"';
            ctx.fillStyle = colour.live;
            ctx.fillText(summary, rect.width - 8, 6);
            ctx.textBaseline = 'bottom';
        }
        if (hover) {
            ctx.font = '12px "IBM Plex Mono"';
            ctx.fillStyle = colour.readout;
            ctx.fillText(`az ${hover.bearing.toFixed(1)}°  ${hover.distanceMiles.toFixed(0)} mi`,
                rect.width - 8, rect.height - 22);
        }
        ctx.font = '10px system-ui';
        ctx.fillStyle = colour.label;
        ctx.fillText(meta.attribution, rect.width - 8, rect.height - 6);
    }

    function drawElevation(ctx, rect) {
        const size = 108;
        const ox = 14;
        const oy = rect.height - 14;
        ctx.save();
        ctx.strokeStyle = colour.scale;
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.arc(ox, oy, size, -Math.PI / 2, 0);
        ctx.stroke();
        for (let d = 0; d <= 90; d += 10) {
            const angle = -(d * Math.PI) / 180;
            const major = d % 30 === 0;
            const r1 = size - (major ? 9 : 5);
            ctx.beginPath();
            ctx.moveTo(ox + r1 * Math.cos(angle), oy + r1 * Math.sin(angle));
            ctx.lineTo(ox + size * Math.cos(angle), oy + size * Math.sin(angle));
            ctx.stroke();
        }
        ctx.font = '500 11px "Barlow Condensed"';
        ctx.fillStyle = colour.label;
        ctx.textAlign = 'left';
        ctx.textBaseline = 'middle';
        for (let d = 0; d <= 90; d += 30) {
            const angle = -(d * Math.PI) / 180;
            const r = size - 20;
            ctx.fillText(String(d), ox + r * Math.cos(angle) - 4, oy + r * Math.sin(angle));
        }

        const commandedEl = props.store.commandedAzEl?.el;
        if (commandedEl !== undefined && commandedEl !== null) {
            const angle = -(Math.max(0, Math.min(90, commandedEl)) * Math.PI) / 180;
            ctx.strokeStyle = SIGNAL;
            ctx.lineWidth = 1.5;
            ctx.setLineDash([5, 4]);
            ctx.beginPath();
            ctx.moveTo(ox, oy);
            ctx.lineTo(ox + (size - 12) * Math.cos(angle), oy + (size - 12) * Math.sin(angle));
            ctx.stroke();
            ctx.setLineDash([]);
        }
        const currentEl = props.store.azel?.el;
        if (currentEl !== undefined && currentEl !== null) {
            const angle = -(Math.max(-2, Math.min(92, currentEl)) * Math.PI) / 180;
            ctx.strokeStyle = colour.accent;
            ctx.lineWidth = 2.5;
            ctx.beginPath();
            ctx.moveTo(ox, oy);
            ctx.lineTo(ox + (size - 12) * Math.cos(angle), oy + (size - 12) * Math.sin(angle));
            ctx.stroke();
        }
        ctx.font = '600 12px "Barlow Condensed"';
        ctx.fillStyle = colour.label;
        ctx.fillText('EL', ox + 4, oy - size - 8);
        ctx.restore();
    }

    // --- interaction ---

    function eventBearing(event) {
        const rect = canvasEl.value.getBoundingClientRect();
        const x = event.clientX - rect.left;
        const y = event.clientY - rect.top;
        if (!geom || Math.hypot(x - geom.cx, y - geom.cy) > geom.disc) return null;
        const mapPixel = canvasToMapPixel(x, y);
        const point = inverse.pixelToLatLon(mapPixel.x, mapPixel.y);
        const site = props.config.site;
        return {
            x, y,
            bearing: initialBearing(site.latitude, site.longitude, point.latitude, point.longitude),
            distanceMiles: haversineDistance(site.latitude, site.longitude, point.latitude, point.longitude) / METERS_PER_MILE,
        };
    }

    function onClick(event) {
        if (!meta) return;
        const rect = canvasEl.value.getBoundingClientRect();
        const x = event.clientX - rect.left;
        const y = event.clientY - rect.top;
        for (const marker of stationMarkers) {
            if (Math.hypot(x - marker.x, y - marker.y) < 10) {
                emit('set-azimuth', marker.bearing);
                return;
            }
        }
        const at = eventBearing(event);
        if (at) emit('set-azimuth', at.bearing);
    }

    function onMove(event) {
        if (!meta) return;
        hover = eventBearing(event);
        canvasEl.value.style.cursor = hover ? 'crosshair' : 'default';
        scheduleDraw();
    }

    function onLeave() {
        hover = null;
        scheduleDraw();
    }

    let resizeObserver = null;
    let liveTimer = null;

    onMounted(async () => {
        try {
            const response = await fetch('map_meta.json');
            if (!response.ok) throw new Error();
            meta = await response.json();
            projection = makeProjection(meta);
            inverse = makeInverseProjection(meta);
            mapImage = new Image();
            mapImage.onload = scheduleDraw;
            mapImage.src = 'map.png';
        } catch {
            loadError.value = 'No map found. Run tools/generate_map.py to create map.png and map_meta.json.';
            return;
        }
        resizeObserver = new ResizeObserver(scheduleDraw);
        resizeObserver.observe(wrapEl.value);

        readPalette();
        refreshTrack();
        trackTimer = setInterval(refreshTrack, TRACK_REFRESH_MS);
        // The sub-satellite point moves several pixels a second, so keep redrawing while a
        // satellite is in focus even when no dish telemetry is arriving.
        liveTimer = setInterval(() => {
            if (props.store.focus) scheduleDraw();
        }, 1000);
        scheduleDraw();
    });

    onUnmounted(() => {
        resizeObserver?.disconnect();
        clearInterval(trackTimer);
        clearInterval(liveTimer);
    });

    watch(
        () => [props.store.azel?.az, props.store.azel?.el, props.store.commandedAzEl],
        scheduleDraw,
    );

    watch(() => props.store.focus, refreshTrack);

    watch(() => props.store.theme, () => {
        readPalette();
        scheduleDraw();
    });
</script>

<template>
    <div ref="wrapEl" class="map-wrap">
        <canvas ref="canvasEl" @click="onClick" @mousemove="onMove" @mouseleave="onLeave"></canvas>
        <p v-if="loadError" class="load-error">{{ loadError }}</p>
    </div>
</template>

<style scoped>
    .map-wrap {
        flex: 1;
        min-height: 0;
        position: relative;
    }

    canvas {
        position: absolute;
        inset: 0;
    }

    .load-error {
        position: absolute;
        inset: 40% 10% auto;
        text-align: center;
        color: var(--muted);
    }
</style>
