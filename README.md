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

The built app is committed, so on a machine with Python and no Node toolchain it is just:

```sh
cd bigdish_console
python3 serve.py                # http://127.0.0.1:8620/
```

To rebuild it after changing anything under `bigdish_console/src` (Node 20.19+ needed), and
commit the result so that stays true:

```sh
cd bigdish_console
npm ci
npm run build
```

`python3 tools/generate_map.py` regenerates the map image, needed only after changing the
radius, projection or tile style in `public/config.json`; it is the one step that needs
internet, and its output is committed too.

It talks to the dish server through `dish_client/bigdish_client.js`, the browser counterpart
to `bigdish_client.py` beside it. See [its README](./bigdish_console/README.md) for
configuration and what each feature does. A copy also lives in the club's
`w1xm/BigDishControlServer` repository, which holds the server and the protocol
specification.

## Requirements

- [bigdish-client](https://github.com/w1xm/BigDishControlServer/tree/main/client), the
  protocol client that the scripts here import as `bigdish_client`:

  ```sh
  pip install "bigdish-client @ git+https://github.com/w1xm/BigDishControlServer#subdirectory=client"
  ```

- the radio command client in [radio_client](./radio_client), for the scripts that talk to
  the Ettus radios:

  ```sh
  pip install -e ./radio_client
  ```

  This also puts `run-radio-commands` on the PATH, for running a scheduled csv of radio
  commands.

- radioconda/digital_rf
- astropy
- numpy
- scipy
- websockets
