# Radio Command Client library

these are designed to be used with thor.py from haystack's digital rf library. thor must be run with the -M option for the control client to be able to connect. e.g. the command should be something like

thor.py /tmp/ramdisk/data -m 172.25.14.11 -d "A:0 B:0" -c RHCP,LHCP -y "RX2,RX2" -f 1415e6 -F 20e6,20e6 -g 20 -r 33.333e6 --clock_source 'external' --time_source 'external' -M


the radio command client will allow passing commands to control the radio calibrator and gpio. run_radio_commands.py operates on a csv file to execute preplanned timed operations.