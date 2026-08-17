#!/usr/bin/env python3
'''
Generate the static map image used by the console's map view.

Downloads map tiles covering a configurable radius around the dish site and writes:

    public/map.png       -- the map image
    public/map_meta.json -- projection parameters the UI needs to convert lat/lon <-> pixel

Two output projections are available, chosen by "projection" in the map section of
public/config.json:

    azimuthal_equidistant (default)
        A polar chart about the dish: pixel radius is exactly proportional to ground
        distance and pixel angle is true bearing, so the console's range rings are honest
        and its azimuth needles are straight lines out of the center. The mercator tiles
        are resampled into this projection here. Pixels beyond the radius are transparent.

    webmercator
        The stitched tiles as downloaded. Simpler, but azimuth rays curve across the image
        and the disc edge is only exactly the configured radius due east and west (at 42
        degrees north it falls ~1.5% short at the top and ~3% long at the bottom).

Reads the site location, radius, projection, and tile style from public/config.json. Run
it once at setup and again after changing any of those; the app itself never fetches tiles
at runtime, so it works fully offline afterwards.

Usage:  python3 generate_map.py
'''

import io
import json
import math
import time
import urllib.request
from pathlib import Path

import numpy as np
from PIL import Image

EARTH_RADIUS_M = 6378137.0
METERS_PER_MILE = 1609.344
TILE_SIZE = 256
WORLD_HALF_M = math.pi * EARTH_RADIUS_M
MAX_ZOOM = 12
# The azimuthal-equidistant warp is rendered this many times oversampled in each axis and
# then reduced with LANCZOS, which anti-aliases both the geometry and the downscale.
AEQD_OVERSAMPLE = 2
USER_AGENT = "BigDishConsole-map-generator/0.1 (amateur radio telescope UI; run once at setup)"


def mercator_xy(lat_deg, lon_deg):
    '''Project lat/lon (degrees) to web mercator meters.'''
    x = EARTH_RADIUS_M * math.radians(lon_deg)
    y = EARTH_RADIUS_M * math.asinh(math.tan(math.radians(lat_deg)))
    return x, y


def great_circle_destination(lat_deg, lon_deg, bearing_deg, distance_m):
    '''Point reached by following a great circle from (lat, lon) at an initial bearing.

    Mirrors greatCircleDestination() in src/lib/projection.js on the same spherical earth,
    so the console's pixel <-> bearing math agrees exactly with the image we produce.
    '''
    delta = distance_m / EARTH_RADIUS_M
    theta = math.radians(bearing_deg)
    p1 = math.radians(lat_deg)
    p2 = math.asin(math.sin(p1) * math.cos(delta)
                   + math.cos(p1) * math.sin(delta) * math.cos(theta))
    l2 = math.radians(lon_deg) + math.atan2(
        math.sin(theta) * math.sin(delta) * math.cos(p1),
        math.cos(delta) - math.sin(p1) * math.sin(p2))
    return math.degrees(p2), math.degrees(l2)


def disc_mercator_bounds(lat, lon, radius_m):
    '''Mercator bounding box of the ground disc of the given radius around the site.

    Every extreme of longitude and of mercator y over the disc lies on its boundary
    circle, so walking the boundary at one-degree steps is enough (the error from the
    chord between samples is a few tens of meters).
    '''
    xs, ys = [], []
    for bearing in range(360):
        point = great_circle_destination(lat, lon, bearing, radius_m)
        x, y = mercator_xy(*point)
        xs.append(x)
        ys.append(y)
    return min(xs), min(ys), max(xs), max(ys)


def choose_zoom(lat, radius_m, image_size):
    '''Coarsest tile zoom whose native resolution still meets the output resolution.

    The output has 2 * radius_m of ground across image_size pixels. Mercator compresses
    ground distance by cos(lat), so matching that resolution needs
    (2 * radius_m / cos(lat)) / image_size mercator meters per pixel or finer. Picking the
    coarsest such zoom means we only ever downsample the tiles.
    '''
    target_merc_per_px = 2.0 * (radius_m / math.cos(math.radians(lat))) / image_size
    base_merc_per_px = 2.0 * WORLD_HALF_M / TILE_SIZE
    zoom = math.ceil(math.log2(base_merc_per_px / target_merc_per_px))
    return max(0, min(zoom, MAX_ZOOM))


def mosaic_layout(bounds, zoom, margin_px=0):
    '''Whole tiles covering a mercator bounding box, as (tile_x_min, tile_y_min, columns,
    rows, merc_per_px). The mosaic's top-left world pixel is tile_x_min * TILE_SIZE, so

        mosaic_x = (merc_x + WORLD_HALF_M) / merc_per_px - tile_x_min * TILE_SIZE

    converts mercator meters into a pixel coordinate inside the stitched image.
    '''
    merc_per_px = 2.0 * WORLD_HALF_M / (TILE_SIZE * 2 ** zoom)
    x_min, y_min, x_max, y_max = bounds
    margin_m = margin_px * merc_per_px
    px_min = (x_min - margin_m + WORLD_HALF_M) / merc_per_px
    px_max = (x_max + margin_m + WORLD_HALF_M) / merc_per_px
    py_min = (WORLD_HALF_M - (y_max + margin_m)) / merc_per_px
    py_max = (WORLD_HALF_M - (y_min - margin_m)) / merc_per_px

    tile_x_min, tile_x_max = int(px_min // TILE_SIZE), int(px_max // TILE_SIZE)
    tile_y_min, tile_y_max = int(py_min // TILE_SIZE), int(py_max // TILE_SIZE)
    return (tile_x_min, tile_y_min,
            tile_x_max - tile_x_min + 1, tile_y_max - tile_y_min + 1, merc_per_px)


def fetch_mosaic(bounds, zoom, url_template, margin_px=0):
    '''Download and stitch the tiles covering a mercator bounding box.

    Returns (image, origin_px, origin_py, merc_per_px) -- see mosaic_layout() for how
    those relate mercator meters to pixels in the returned image.
    '''
    tile_x_min, tile_y_min, columns, rows, merc_per_px = mosaic_layout(bounds, zoom, margin_px)
    print(f"zoom {zoom}, {columns * rows} tiles ({columns}x{rows}), "
          f"{merc_per_px:.1f} mercator m/px native")

    mosaic = Image.new("RGB", (columns * TILE_SIZE, rows * TILE_SIZE))
    fetched = 0
    for ty in range(tile_y_min, tile_y_min + rows):
        for tx in range(tile_x_min, tile_x_min + columns):
            url = (url_template.replace("{z}", str(zoom))
                   .replace("{x}", str(tx)).replace("{y}", str(ty)))
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=30) as response:
                tile = Image.open(io.BytesIO(response.read())).convert("RGB")
            mosaic.paste(tile, ((tx - tile_x_min) * TILE_SIZE, (ty - tile_y_min) * TILE_SIZE))
            fetched += 1
            print(f"\r{fetched}/{columns * rows} tiles", end="", flush=True)
            time.sleep(0.1)  # be polite to the tile server
    print()
    return mosaic, tile_x_min * TILE_SIZE, tile_y_min * TILE_SIZE, merc_per_px


def bilinear_sample(src, xs, ys):
    '''Bilinear lookup into an (h, w, 3) uint8 image at fractional coordinates.

    xs/ys may have any matching shape; the result is that shape with a trailing axis of 3.
    Coordinates outside the image are clamped to its edge, which only ever happens right
    at the rim of the disc, where the output is transparent anyway.
    '''
    height, width = src.shape[:2]
    x0 = np.clip(np.floor(xs), 0, width - 2).astype(np.int64)
    y0 = np.clip(np.floor(ys), 0, height - 2).astype(np.int64)
    fx = np.clip(xs - x0, 0.0, 1.0)[..., None]
    fy = np.clip(ys - y0, 0.0, 1.0)[..., None]

    p00 = src[y0, x0].astype(np.float32)
    p10 = src[y0, x0 + 1].astype(np.float32)
    p01 = src[y0 + 1, x0].astype(np.float32)
    p11 = src[y0 + 1, x0 + 1].astype(np.float32)
    top = p00 + (p10 - p00) * fx
    bottom = p01 + (p11 - p01) * fx
    return np.clip(top + (bottom - top) * fy + 0.5, 0, 255).astype(np.uint8)


def warp_to_aeqd(mosaic, origin_px, origin_py, merc_per_px, lat, lon, radius_m, image_size):
    '''Resample a mercator mosaic into an azimuthal-equidistant image about the site.

    For every output pixel we take its offset from the center in meters, read off the
    bearing and ground range that offset represents, walk the great circle to the point it
    names, and sample the mosaic there. Pixels beyond radius_m keep the color of the rim
    but are fully transparent, so reducing the oversampled render leaves a clean edge
    instead of a dark fringe.
    '''
    render = image_size * AEQD_OVERSAMPLE
    meters_per_px = 2.0 * radius_m / render
    src = np.asarray(mosaic)
    out = np.empty((render, render, 4), dtype=np.uint8)

    p1 = math.radians(lat)
    l1 = math.radians(lon)
    dx = (np.arange(render) + 0.5 - render / 2.0) * meters_per_px

    rows_per_chunk = max(1, 4_000_000 // render)
    for start in range(0, render, rows_per_chunk):
        stop = min(start + rows_per_chunk, render)
        dy = (render / 2.0 - (np.arange(start, stop) + 0.5)) * meters_per_px
        east, north = np.meshgrid(dx, dy)

        ground = np.hypot(east, north)
        theta = np.arctan2(east, north)  # bearing, radians clockwise from north
        delta = np.minimum(ground, radius_m) / EARTH_RADIUS_M

        lat2 = np.arcsin(np.clip(math.sin(p1) * np.cos(delta)
                                 + math.cos(p1) * np.sin(delta) * np.cos(theta), -1.0, 1.0))
        lon2 = l1 + np.arctan2(np.sin(theta) * np.sin(delta) * math.cos(p1),
                               np.cos(delta) - math.sin(p1) * np.sin(lat2))

        sx = (EARTH_RADIUS_M * lon2 + WORLD_HALF_M) / merc_per_px - origin_px
        sy = (WORLD_HALF_M - EARTH_RADIUS_M * np.arcsinh(np.tan(lat2))) / merc_per_px - origin_py

        out[start:stop, :, :3] = bilinear_sample(src, sx, sy)
        out[start:stop, :, 3] = np.where(ground <= radius_m, 255, 0)
        print(f"\rwarping {stop}/{render} rows", end="", flush=True)
    print()
    return Image.fromarray(out, "RGBA").resize((image_size, image_size), Image.LANCZOS)


def main():
    public_dir = Path(__file__).resolve().parent.parent / "public"
    config = json.loads((public_dir / "config.json").read_text())

    site = config["site"]
    map_config = config["map"]
    lat = site["latitude"]
    lon = site["longitude"]
    radius_miles = map_config["radius_miles"]
    radius_m = radius_miles * METERS_PER_MILE
    image_size = map_config["image_size_px"]
    projection = map_config.get("projection", "azimuthal_equidistant")

    zoom = choose_zoom(lat, radius_m, image_size)
    center_x, center_y = mercator_xy(lat, lon)

    if projection == "azimuthal_equidistant":
        # Two pixels of margin so bilinear sampling at the rim stays inside the mosaic.
        mosaic, origin_px, origin_py, merc_per_px = fetch_mosaic(
            disc_mercator_bounds(lat, lon, radius_m), zoom, map_config["tile_url"], margin_px=2)
        final = warp_to_aeqd(mosaic, origin_px, origin_py, merc_per_px,
                             lat, lon, radius_m, image_size)
        meta = {
            "projection": "azimuthal_equidistant",
            "center_latitude": lat,
            "center_longitude": lon,
            "radius_miles": radius_miles,
            "image_size_px": image_size,
            # Ground meters per pixel, exact in every direction. The inscribed circle of
            # the image is the radius_miles ring; outside it the image is transparent.
            "meters_per_pixel": 2.0 * radius_m / image_size,
        }
    elif projection == "webmercator":
        # A true ground distance of radius_m at the site latitude spans radius_m / cos(lat)
        # in mercator units, because mercator stretches distances by 1/cos(lat).
        half_width_merc = radius_m / math.cos(math.radians(lat))
        bounds = (center_x - half_width_merc, center_y - half_width_merc,
                  center_x + half_width_merc, center_y + half_width_merc)
        mosaic, origin_px, origin_py, merc_per_px = fetch_mosaic(
            bounds, zoom, map_config["tile_url"])
        crop_box = (round((bounds[0] + WORLD_HALF_M) / merc_per_px - origin_px),
                    round((WORLD_HALF_M - bounds[3]) / merc_per_px - origin_py),
                    round((bounds[2] + WORLD_HALF_M) / merc_per_px - origin_px),
                    round((WORLD_HALF_M - bounds[1]) / merc_per_px - origin_py))
        final = mosaic.crop(crop_box).resize((image_size, image_size), Image.LANCZOS)
        meta = {
            "projection": "webmercator",
            "center_latitude": lat,
            "center_longitude": lon,
            "radius_miles": radius_miles,
            "image_size_px": image_size,
            # Mercator meters covered by the image; the UI derives its lat/lon <-> pixel
            # transform from these.
            "merc_x_min": bounds[0],
            "merc_x_max": bounds[2],
            "merc_y_min": bounds[1],
            "merc_y_max": bounds[3],
        }
    else:
        raise SystemExit(f'Unknown map projection "{projection}" in config.json.')

    final.save(public_dir / "map.png")
    meta["attribution"] = map_config["attribution"]
    meta["generated_unix"] = time.time()
    (public_dir / "map_meta.json").write_text(json.dumps(meta, indent=4) + "\n")
    print(f"wrote map.png ({image_size}x{image_size}, {projection}) and map_meta.json")


if __name__ == "__main__":
    main()
