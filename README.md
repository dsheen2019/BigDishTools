# BigDishTools
Tools for observations using bigdish and for modeling antenna performance

Note: for now this is a work in progress and still needs extensive cleanup and documentation. 

## Control console

`bigdish_console/` is a browser interface for driving the dish by hand: a regional map with
the dish azimuth drawn over it as a polar chart, a star chart, manual pointing in az/el,
ra/dec or galactic coordinates, a target list (calibrator sources, solar-system bodies,
ground stations, satellites), pointing offsets in four frames, and a rise-to-set sky path
drawn over both charts for the selected target. It runs on the operator's own machine and
binds to loopback only.

```sh
cd bigdish_console
npm install
python3 tools/generate_map.py   # once: downloads the map tiles, needs internet
npm run build
python3 serve.py                # http://127.0.0.1:8620/
```

It talks to the dish server through `dish_client/bigdish_client.js`, the browser counterpart
to `bigdish_client.py` beside it. See [its README](./bigdish_console/README.md) for
configuration and what each feature does. A copy also lives in the club's
`w1xm/BigDishControlServer` repository, which holds the server and the protocol
specification.

## Requirements

- astropy
- numpy
- scipy
- digital rf
- websockets
- xarrays and Dask (for ITU models) 
