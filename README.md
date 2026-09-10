# BigDishTools
Tools for observations using bigdish and for modeling antenna performance

Note: for now this is a work in progress and still needs extensive cleanup and documentation. 

Most of the tools here were written by dsheen either as demo files, or for observaation modelling. 
Particularly, the mapping tools folder provides some basic scripts for using the dish to scan 
astronomical targets and the analysis examples folder includes notebooks with basic processing 
flows. Antenna pattern models are included in the antenna_data folder and can be used to model 
the expected beam response to astronomical targets, or to off-axis rfi sources. That folder also 
includes scripts to import the patterns and rotate it in spherical coordinates.

## Control console

`bigdish_console/` is a browser interface for driving the dish by hand. it also provides a UI 
interface for some of the other scripts here to support easy tracking of satellites or running 
pre-planned pointing files. This code was largely AI generated and has not been sufficently 
scrutinized to be safe to expose on a server. It ONLY binds to localhost and is meant to be run 
locally. It also utilizes a user editable config for setting up certain features. Please do not 
atttempt to set it up as an outward facing service. 

The built app is committed the rthe repo and can be run as:

```sh
cd bigdish_console
python3 serve.py                # http://127.0.0.1:8620/
```

It talks to the dish server through `dish_client/bigdish_client.js`, the browser counterpart
to `bigdish_client.py` beside it. See [its README](./bigdish_console/README.md) for
configuration and what each feature does. A copy also lives in the club's
`w1xm/BigDishControlServer` repository, which holds the server and the protocol
specification.

## Requirements

- [bigdish-client](https://github.mit.edu/w1xm/BigDishControlServer/tree/main/client), the
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
