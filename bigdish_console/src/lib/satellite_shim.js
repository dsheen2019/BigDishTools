// satellite.js v7's root entry re-exports its WASM build, which uses top-level await and
// node-only imports and breaks the worker bundle. We only need the classic pure-JS SGP4,
// so re-export exactly those pieces from the package's internal modules (relative paths
// bypass the package "exports" map, which only exposes the root).
export { twoline2satrec } from "../../node_modules/satellite.js/dist/io.js";
export { propagate, gstime } from "../../node_modules/satellite.js/dist/propagation.js";
export {
    degreesToRadians,
    radiansToDegrees,
    eciToEcf,
    ecfToLookAngles,
} from "../../node_modules/satellite.js/dist/transforms.js";
