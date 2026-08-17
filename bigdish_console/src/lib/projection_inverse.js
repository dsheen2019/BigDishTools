// Inverse mapping (map image pixel -> lat/lon) for the projections in projection.js.
// Kept beside makeProjection; used by the map view to turn clicks into bearings.

import { greatCircleDestination } from "./projection.js";

const EARTH_RADIUS_M = 6378137.0;
const deg = (r) => (r * 180) / Math.PI;

export function makeInverseProjection(meta) {
    if (meta.projection === "azimuthal_equidistant") {
        const center = meta.image_size_px / 2;
        return {
            pixelToLatLon(x, y) {
                const east = (x - center) * meta.meters_per_pixel;
                const north = (center - y) * meta.meters_per_pixel;
                return greatCircleDestination(
                    meta.center_latitude,
                    meta.center_longitude,
                    deg(Math.atan2(east, north)),
                    Math.hypot(east, north),
                );
            },
        };
    }
    if (meta.projection === "webmercator") {
        const size = meta.image_size_px;
        const spanX = meta.merc_x_max - meta.merc_x_min;
        const spanY = meta.merc_y_max - meta.merc_y_min;
        return {
            pixelToLatLon(x, y) {
                const mercX = meta.merc_x_min + (x / size) * spanX;
                const mercY = meta.merc_y_max - (y / size) * spanY;
                return {
                    latitude: deg(Math.atan(Math.sinh(mercY / EARTH_RADIUS_M))),
                    longitude: deg(mercX / EARTH_RADIUS_M),
                };
            },
        };
    }
    throw new Error(`Unsupported map projection "${meta.projection}".`);
}
