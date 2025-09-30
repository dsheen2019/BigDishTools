#!/usr/bin/env python3

"""program to continually log the telescope position to a csv file"""

from bigdish_client import BigDishClient
import datetime
import argparse
import os
import sys
import time
import traceback
import csv
from datetime import datetime, timezone
import numpy as np

class DishLogger(object):
    def __init__(self, opt):
        """Initialize program to read command file and 
        authenticate to the antenna control server"""

        self.opt = opt

        #instantiate the control client for bigdish
        #please shut down other programs that control the dish nicely before using this


        username = opt.user if opt.user is not None else input("Enter Username:")
        password = opt.password if opt.password is not None else input("Enter Password:")

        #connect to dish control server

        self.dish = BigDishClient("172.25.15.11", 1234) 

        #authenticate

        response = self.dish.authenticate_connection(username, password)
        if response['success']:
            print(f"Authenticated Successfully as {username}\r\n")
        else:
            print(f"Authentication as {username} FAILED! \r\n {response['reason']} \r\n")
            exit()

    def generate_log(self):
        """
        Write the log file
        """

        log_file = open(self.opt.path, 'w')
        #write header
        if self.opt.power:
            log_file.write(f"UTC, az, el, az vel, el vel, az volts, el volts, az amps, el amps\r\n")
        else:
            log_file.write(f"UTC, az, el, az vel, el vel\r\n")


        next_log_time = time.time()
        while True:
            #wait until the next point in time when we should be requesting antenna position
            #note this means we'll actually be like 10ms late but whatever 
            #(also server only updates this every 50ms anyway)

            if time.time() > next_log_time:

                nowtime=time.time()
                pos = self.dish.get_posvel(coords='azel', power=self.opt.power)


                if self.opt.power:
                    log_file.write(f"{datetime.utcfromtimestamp(pos['time']).isoformat()}Z, {pos['az_pos']:.4f}, {pos['el_pos']:.4f}, {pos['az_vel']:.4f}, {pos['el_vel']:.4f}, {pos['az_voltage']}, {pos['el_voltage']}, {pos['az_current']:.4f}, {pos['el_current']:.4f}\r\n")

                    if self.opt.verbose:
                        print(f"{datetime.utcfromtimestamp(pos['time']).isoformat()}Z, {pos['az_pos']:.4f}, {pos['el_pos']:.4f}, {pos['az_vel']:.4f}, {pos['el_vel']:.4f}, {pos['az_voltage']}, {pos['el_voltage']}, {pos['az_current']:.4f}, {pos['el_current']:.4f}\r\n")

                else:
                    log_file.write(f"{datetime.utcfromtimestamp(pos['time']).isoformat()}Z, {pos['az_pos']:.4f}, {pos['el_pos']:.4f}, {pos['az_vel']:.4f}, {pos['el_vel']:.4f}\r\n")

                    if self.opt.verbose:
                        print(f"{datetime.utcfromtimestamp(pos['time']).isoformat()}Z, {pos['az_pos']:.4f}, {pos['el_pos']:.4f}, {pos['az_vel']:.4f}, {pos['el_vel']:.4f}\r\n")

                #while next_log_time < time.time():
                next_log_time = next_log_time + self.opt.log_int


def parse_command_line():
    scriptname = os.path.basename(sys.argv[0])

    formatter = argparse.RawDescriptionHelpFormatter(scriptname)
    width = formatter._width

    title = "WR66_run_pointing_file"
    copyright = "Copyright (c) 2024 Massachusetts Institute of Technology"
    shortdesc = "Tool to run timed pointing command sequences for the big dish"
    desc = "\n".join(
        (
            "*" * width,
            "*{0:^{1}}*".format(title, width - 2),
            "*{0:^{1}}*".format(copyright, width - 2),
            "*{0:^{1}}*".format("", width - 2),
            "*{0:^{1}}*".format(shortdesc, width - 2),
            "*" * width,
        )
    )

    parser = argparse.ArgumentParser(
        description=desc,
        prefix_chars="-",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "path",
        nargs="?",
        default=None,
        metavar="path to log file",
        help="Filepath/name to write antenna position log (will be written as a csv)",
    )
    parser.add_argument(
        "-i",
        "--log_interval",
        dest="log_int",
        default=1,
        type=float,
        help="Time interval at which to record antenna position",
    )
    parser.add_argument(
        "-p",
        "--include_power",
        action="store_true",
        dest="power",
        default=False,
        help="Log Voltage/Current reported by dish drives",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        dest="verbose",
        default=False,
        help="Print status messages to stdout.",
    )
    parser.add_argument(
        "-u",
        "--user",
        dest="user",
        default=None,
        help="username for radome server authentication",
    )
    parser.add_argument(
        "-k",
        "--password",
        dest="password",
        default=None,
        help="password for radome server authentication",
    )



    options = parser.parse_args()

    return options

#
# MAIN PROGRAM
#

# Setup Defaults
if __name__ == "__main__":
    """
    Needed to add main function to use outside functions outside of module.
    """

    # Parse the Command Line for configuration
    options = parse_command_line()

    if options.path is None:
        print("Please provide an output file path with the -o option!")
        sys.exit(1)

    if options.verbose:
        print("options: {0}".format(options))

    logger = DishLogger(options)
    logger.generate_log()