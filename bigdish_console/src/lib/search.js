// Looking up things to point at: satellites from CelesTrak, astronomical sources from SIMBAD.
//
// Both go through the console's own /search endpoint rather than being called from the page.
// CelesTrak sends no CORS header so it could not be called directly anyway, and routing both
// through one place keeps the caching, the rate limiting and the awkwardness of each catalogue
// in serve.py, where it can be fixed once.
//
// What comes back here is already normalised into something the picker can list and the target
// list can accept.

const DISPLAY_LIMIT = 40;

export async function searchCatalogue(catalogue, text) {
    const response = await fetch(
        `/search?catalogue=${catalogue}&q=${encodeURIComponent(text)}`);
    if (!response.ok) {
        // serve.py reports search failures as {"error": ...}; anything else that arrives is
        // not fit to show, so it is reduced to the status
        const body = await response.text();
        let detail = "";
        try {
            detail = JSON.parse(body).error ?? "";
        } catch { /* not json: say nothing rather than paste a web page into the box */ }
        throw new Error(detail || `Search failed (HTTP ${response.status}).`);
    }
    const body = await response.json();
    const results = catalogue === "satellite" ? satellites(body) : skyObjects(body);
    return { results: results.slice(0, DISPLAY_LIMIT), total: results.length };
}

// CelesTrak answers with OMM records. The elements are kept with the result so that adding a
// target does not need a second request, though tracking one will refetch them anyway.
function satellites(records) {
    if (!Array.isArray(records)) return [];
    return records
        .filter((record) => Number.isFinite(record.MEAN_MOTION))
        .map((record) => ({
            key: `sat:${record.NORAD_CAT_ID}`,
            name: record.OBJECT_NAME ?? `Catalog ${record.NORAD_CAT_ID}`,
            detail: `catalog ${record.NORAD_CAT_ID}`
                + (record.OBJECT_ID ? ` · ${record.OBJECT_ID}` : "")
                + (record.EPOCH ? ` · elements from ${record.EPOCH.slice(0, 16).replace("T", " ")}` : ""),
            target: {
                name: record.OBJECT_NAME ?? `Catalog ${record.NORAD_CAT_ID}`,
                category: "Satellites (this session)",
                kind: "strobe",
                catnr: record.NORAD_CAT_ID,
                spec: { type: "satellite", omm: record },
                temporary: true,
            },
        }));
}

// SIMBAD answers with what the resolver made of the query first, then alternatives from the
// identifier tables.
function skyObjects(records) {
    if (!Array.isArray(records)) return [];
    return records.map((record) => ({
        key: `sky:${record.id}`,
        name: record.id,
        detail: [
            record.otype,
            `ra ${record.ra.toFixed(4)}°`,
            `dec ${record.dec >= 0 ? "+" : ""}${record.dec.toFixed(4)}°`,
            record.source === "resolved" ? "best match" : null,
        ].filter(Boolean).join(" · "),
        target: {
            name: record.id,
            category: "Sky objects (this session)",
            kind: "track",
            frame: "radec",
            coord1: record.ra,
            coord2: record.dec,
            temporary: true,
        },
    }));
}
