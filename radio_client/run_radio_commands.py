#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# import a sheduled list of radio control commands and execute them


import os
import sys
import digital_rf as drf
from datetime import datetime, timezone
import time
import argparse
import csv
import time

from radio_command_client import RadioZmqClient

class RadioCommandManager(object):
    def __init__(self, opt):
        """instantiate everything we need to command the 
        radio and read in the observation command files"""

        self.opt = opt

        #startup zmq client

        self.radio = RadioZmqClient(sub_port=self.opt.sub_port, pub_port=self.opt.pub_port)

        # initialize arrays to store command set

        self.command_times  = [] # ordered list of command execution times
        self.command_values = [] # ordered list of commands and inputs
        self.num_commands = 0

        # a few other variables

        self.command_lead_time = 2.0 #seconds of lead time for sending commands to radio queue

        time.sleep(1.0)
        self.initialize_gpio()

    def initialize_gpio(self):
        """ 
        Hard Code initial setup of radio GPIO config for bigdish/westford experiment
        sleep periods in the below are because for some reason the radio misses commands 
        if these are run too fast and doesn't fully configure its outputs conrrectly
        """

        self.radio.set_gpio_attr( 'FP0A', 'CTRL', 0x000, 0b11)
        time.sleep(0.1)
        self.radio.set_gpio_attr( 'FP0A', 'DDR', 0xFFF, 0b11)
        time.sleep(0.1)
        self.radio.set_gpio_attr('FP0A', 'OUT', 0, 3)


    def read_command_file(self):
        """Parse contents of input command file and translate into useable array

        right now only support set_gpio_state command with line in the form

        utc time, "set_gpio_state", state

        where state is integer 0 through 3 defining the binary state of the gpio pins. 

        0 = Both off
        1 = rhcp calibrator on
        2 = lhcp calibrator on
        3 = both calibrators on

        """

        with open(self.opt.path, 'r') as file:
            commands = csv.reader(file)

            for row in commands:

                #command_time

                command_time = datetime.fromisoformat(row[0].strip())

                if len(self.command_times) > 1: # check execution order
                    if (self.command_times[-1] - command_time).total_seconds() > 0:
                        raise ValueError(f"Bad Timestep at {command_time}, check command file order\r\n")

                self.command_times.append(command_time)

                if row[1].strip() == "set_gpio_state":
                    self.command_values.append([row[1].strip(), int(row[2].strip())])
                else:
                    print(f"command '{row[1].strip()}' not recognized")

                self.num_commands += 1

    def execute_commands(self):

        """Handle radio command sequencing"""

        self.read_command_file()

        # run commands

        #at start set previous command time to zero so checks are handled correctly.

        last_command_time = 0

        while self.num_commands > 0:

            command_time = self.command_times.pop(0)
            command_values = self.command_values.pop(0)

            self.num_commands -=1

            if command_time != last_command_time:
                #clear last command time before doing more things
                self.radio.clear_command_time()

                wait_time = command_time.timestamp() - time.time() - self.command_lead_time
                if wait_time > 0:
                    if self.opt.verbose:
                        print(f"sleeping for {wait_time} seconds")
                    time.sleep(wait_time)

                #set command only once if we have multiple commands to be executed simultaneously

                self.radio.set_command_timestamp(command_time.timestamp())

                last_command_time = command_time

                if self.opt.verbose:
                    print(f"{command_time}, {command_values[0]}, {command_values[1]}")

            if command_values[0] == "set_gpio_state":
                self.radio.set_gpio_state(int(command_values[1])) #set gpio state on radio as commanded

        if self.num_commands ==0:
            self.radio.clear_command_time() #don't leave radio expecting more commands when closing
            print("done")
            exit()

def parse_command_line():
    scriptname = os.path.basename(sys.argv[0])

    formatter = argparse.RawDescriptionHelpFormatter(scriptname)
    width = formatter._width

    title = "run radio commands"
    copyright = "Copyright (c) 2024 Massachusetts Institute of Technology"
    shortdesc = "Tool to run radio commands for calibration/etc based on csv file of execution times"
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
        help="Path to csv file with antenna commands.",
    )
    parser.add_argument(
        "-zo",
        "--zmq_out",
        dest="pub_port",
        default=5563,
        help="""port number for zmq sub to recieve control messages for the usrp
                (default: 5563)""",
    )
    parser.add_argument(
        "-zi",
        "--zmq_in",
        dest="sub_port",
        default=5562,
        help="""port number for zmq sub to recieve messages from the usrp
                (default: 5562)""",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        dest="verbose",
        default=False,
        help="Print status messages to stdout.",
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
        print("Please provide an input source with the -p option!")
        sys.exit(1)

    if options.verbose:
        print("options: {0}".format(options))

    radio_control = RadioCommandManager(options)
    time.sleep(1.0)

    radio_control.execute_commands()