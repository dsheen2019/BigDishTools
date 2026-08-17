# Radio Command Client library

## Installing

```sh
pip install -e ./radio_client
```

Then `from radio_command_client import RadioZmqClient` works from any directory, with no
need to put this folder on `sys.path`, and the command runner is on the PATH as
`run-radio-commands`, so a scheduled command file can be run from wherever it lives:

```sh
run-radio-commands path/to/commands.csv
```
 Only pyzmq is declared as a dependency: `pmt` and
`digital_rf` come from GNU Radio and are part of the radioconda environment these tools run
in, rather than being installable from PyPI.

these are designed to be used with thor.py from haystack's digital rf library. thor must be run with the -M option for the control client to be able to connect. e.g. the command should be something like

thor.py /tmp/ramdisk/data -m 172.25.14.11 -d "A:0 B:0" -c RHCP,LHCP -y "RX2,RX2" -f 1415e6 -F 20e6,20e6 -g 20 -r 33.333e6 --clock_source 'external' --time_source 'external' -M


the radio command client will allow passing commands to control the radio calibrator and gpio. run_radio_commands.py operates on a csv file to execute preplanned timed operations.