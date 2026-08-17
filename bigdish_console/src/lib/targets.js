// The target catalog: turns config.json "targets" entries into a uniform description the
// UI can list in one dropdown and act on with one code path per kind.
//
// Kinds:
//   "track"  -- fixed radec/gal coordinates; handed to the server's own track command.
//   "goto"   -- fixed az/el (ground stations: great-circle bearing at the horizon);
//               a single goto_posvel. Stations also become map markers.
//   "strobe" -- anything that moves in az/el (solar-system bodies, satellites); driven
//               client-side by the strobe worker, which recomputes az/el continuously.
//
// Adding a new target type means producing one of these three kinds here and, for
// "strobe", teaching the worker how to compute it.

import { haversineDistance, initialBearing, METERS_PER_MILE } from "./projection.js";

export function buildTargets(config) {
    const site = config.site;
    return config.targets.map((entry) => {
        switch (entry.type) {
            case "fixed":
                if (entry.frame === "azel") {
                    return {
                        name: entry.name,
                        category: "Fixed",
                        kind: "goto",
                        frame: "azel",
                        coord1: entry.coord1,
                        coord2: entry.coord2,
                    };
                }
                return {
                    name: entry.name,
                    category: "Sky objects",
                    kind: "track",
                    frame: entry.frame,
                    coord1: entry.coord1,
                    coord2: entry.coord2,
                };
            case "station": {
                const bearing = initialBearing(
                    site.latitude, site.longitude, entry.latitude, entry.longitude,
                );
                const distance = haversineDistance(
                    site.latitude, site.longitude, entry.latitude, entry.longitude,
                );
                return {
                    name: entry.name,
                    category: "Stations",
                    kind: "goto",
                    frame: "azel",
                    coord1: bearing,
                    coord2: 0.0,
                    latitude: entry.latitude,
                    longitude: entry.longitude,
                    distance_miles: distance / METERS_PER_MILE,
                };
            }
            case "body":
                return {
                    name: entry.name,
                    category: "Solar system",
                    kind: "strobe",
                    spec: { type: "body", body: entry.body },
                };
            case "satellite":
                return {
                    name: entry.name,
                    category: "Satellites",
                    kind: "strobe",
                    catnr: entry.catnr,
                    // spec.tle is filled in by fetchTLE just before tracking starts
                    spec: { type: "satellite", tle: null },
                };
            default:
                throw new Error(`Unknown target type "${entry.type}" in config.json.`);
        }
    });
}

// Fetch a TLE through the local /tle endpoint (vite dev proxy or serve.py), caching in
// localStorage so repeated sessions don't hammer CelesTrak.
export async function fetchTLE(catnr, maxAgeHours) {
    const cacheKey = `tle:${catnr}`;
    const cached = localStorage.getItem(cacheKey);
    if (cached) {
        const { fetched, lines } = JSON.parse(cached);
        if (Date.now() - fetched < maxAgeHours * 3600 * 1000) {
            return lines;
        }
    }

    const response = await fetch(`/tle?catnr=${encodeURIComponent(catnr)}`);
    if (!response.ok) {
        throw new Error(`TLE fetch for catalog number ${catnr} failed (HTTP ${response.status}).`);
    }
    const text = (await response.text()).trim();
    const rows = text.split("\n").map((line) => line.trim()).filter((line) => line !== "");
    const lines = rows.filter((line) => /^[12] /.test(line));
    if (lines.length < 2) {
        throw new Error(`CelesTrak returned no TLE for catalog number ${catnr}: "${text.slice(0, 80)}"`);
    }
    localStorage.setItem(cacheKey, JSON.stringify({ fetched: Date.now(), lines }));
    return lines;
}
