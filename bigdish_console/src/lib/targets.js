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
                    // spec.omm is filled in by fetchElements just before tracking starts
                    spec: { type: "satellite", omm: null },
                };
            default:
                throw new Error(`Unknown target type "${entry.type}" in config.json.`);
        }
    });
}

// Fetch orbital elements through the local /omm endpoint (vite dev proxy or serve.py),
// caching in localStorage so repeated sessions don't hammer CelesTrak.
//
// OMM is what CelesTrak serves now; the two-line format it supersedes is deprecated, and
// cannot represent catalog numbers past five digits. satellite.js reads the JSON form
// directly, so nothing is parsed here beyond checking it is what it claims to be.
export async function fetchElements(catnr, maxAgeHours) {
    const cacheKey = `omm:${catnr}`;
    const cached = localStorage.getItem(cacheKey);
    if (cached) {
        const { fetched, omm } = JSON.parse(cached);
        if (Date.now() - fetched < maxAgeHours * 3600 * 1000) {
            return omm;
        }
    }

    const response = await fetch(`/omm?catnr=${encodeURIComponent(catnr)}`);
    if (!response.ok) {
        throw new Error(
            `Element fetch for catalog number ${catnr} failed (HTTP ${response.status}).`);
    }
    const elements = await response.json();
    const omm = Array.isArray(elements) ? elements[0] : elements;
    if (!omm || !Number.isFinite(omm.MEAN_MOTION)) {
        throw new Error(`CelesTrak returned no usable elements for catalog number ${catnr}.`);
    }
    localStorage.setItem(cacheKey, JSON.stringify({ fetched: Date.now(), omm }));
    return omm;
}
