#!/usr/bin/env python3

"""
Copyright 07/2025

program to ingest and execute a csv file containing a 
(potentially very long duration) set of timed pointing 
commands for the telescope

file should be a csv with each line consisting of:

        UTC_Time in ISO format, coordinate system, first coordinate, second coordinate, azvel [optional], elvel [optional]

        coordinate systems may be any of the following

        azel
        gal
        radec

        coordinates are assumed to be given in decimal degrees and decimal degrees per second (shouldn't be more than 10)

        Note that galactic and radec will internally correct ONLY for earth motion and 
        not for parallax due to the earth's position relative the the coordinate system center
        (e.g. they are telescope-centric)

"""

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


class DishCommandProcessor(object):
    def __init__(self, opt):
        """Initialize program to read command file and 
        authenticate to the antenna control server"""

        self.opt = opt

        #instantiate the control client for bigdish
        #please shut down other programs that control the dish nicely before using this

        if self.opt.test == False:

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

            response = self.dish.initialize_connection(kick_others=False)

            if response['success'] == True:
                print("Successfully acquired dish control")
            else:
                print(f"Failed to get dish control. {response['reason']}\r\n")
                response = input("do you want to to forcibly kick other users? [y/n]")
                if response == 'y':
                    response = self.dish.initialize_connection(kick_others=True)
                    if response['success'] == True:
                        print("Successfully acquired dish control")
                    else:
                        print(f"Failed to get dish control. {response['reason']}\r\n")
                        exit()
                else:
                    exit()

        # initialize arrays to store command set

        self.command_times  = [] # ordered list of command execution times
        self.command_frames = [] # ordered list of command coordinate frames
        self.command_coords = [] # ordered list of arrays containing command coordinates
        self.num_commands = 0

        # a few other variables

        self.command_lead_time = 2.0 #seconds of lead time for sending commands to dish queue

    def read_command_file(self):
        """Parse contents of input command file and translate into useable array

        file should be a csv with each line consisting of:

        UTC_Time in ISO format, coordinate system, first coordinate, second coordinate, azvel [optional], elvel [optional]

        coordinate systems may be any of the following

        azel
        gal
        radec

        coordinates are assumed to be given in decimal degrees and decimal degrees per second (shouldn't be more than 10)

        Note that galactic and radec will internally correct ONLY for earth motion and 
        not for parallax due to the earth's position relative the the coordinate system center
        (e.g. they are telescope-centric)
        """

        valid_frames = ['azel', 'gal', 'radec']

        with open(self.opt.path, 'r') as file:
            commands = csv.reader(file)

            for row in commands:

                #command_time

                command_time = datetime.fromisoformat(row[0].strip())

                if len(self.command_times) > 1: # check execution order
                    if (self.command_times[-1] - command_time).total_seconds() > 0:
                        raise ValueError(f"Bad Timestep at {command_time}, check command file order\r\n")

                self.command_times.append(command_time)

                #command_frame

                command_frame = row[1].lower().strip()
                if command_frame in valid_frames:
                    self.command_frames.append(command_frame)

                else:

                    raise ValueError(f"Bad coordinate frame {row[1]} at time {command_time}\r\n")
                    
                #coordinate values
                try:
                    coords = np.array([float(row[i].strip()) for i in range(2,len(row))])
                except:
                    raise ValueError(f"Bad coordinate values at time {command_time}: cannot cast to float!\r\n")

                if command_frame == 'azel':
                    if coords[1] < -3.0:
                        raise ValueError(f"Bad elevation command: {coords[1]} < 3.0 degrees at time {command_time}\r\n")

                if coords[0] < 0.0 or coords[0] > 360.0:
                    raise ValueError(f"First coordinate out of bounds: {coords[0]} not between 0 and 360 degrees at time {command_time}\r\n")

                if np.abs(coords[1]) > 90.0:
                    raise ValueError(f"Second coordinate out of bounds: |{coords[1]}| > 90.0 degrees at time {command_time}\r\n")

                if len(coords) > 2: #if velocities are included, check to make sure they aren't wildly outside what the dish will do 
                    #note that it has limits on what it will allow anyway enforced by the motor controllers so this is more a sanity check of the file than anything else
                    if np.abs(coords[2]) > 20.0 or np.abs(coords[3]) > 20:
                        raise ValueError(f"antenna velocities beyond allowed limits at time {command_time}\r\n")

                self.command_coords.append(coords)

                if self.opt.verbose:
                    print(f"{command_time}, {command_frame}, {coords}")

                self.num_commands +=1


    def run_commands(self):
        """Process and execute pointing commands"""

        self.read_command_file()

        # run commands

        if self.opt.test:
            print('Command file is OK!')
            exit()

        while self.num_commands > 0:

            command_time = self.command_times.pop(0)
            command_frame = self.command_frames.pop(0)
            command_coords = self.command_coords.pop(0)

            self.num_commands -=1

            if self.num_commands >=1:
                inter_command_time = (self.command_times[0] - command_time).total_seconds()
            else:
                inter_command_time = 25 #end your file by stowing the antenna yourself if you want to avoid truncating the last observation

            wait_time = command_time.timestamp() - time.time() - self.command_lead_time
            #print(f'wait time = {wait_time}')

            if wait_time > 0:
                if self.opt.verbose:
                    print(f"sleeping for {wait_time} seconds")
                time.sleep(wait_time)

            if len(command_coords) > 2:
                self.dish.track(coords=command_frame, coord1=command_coords[0], coord2=command_coords[1], vel1=command_coords[2], vel2=command_coords[3], duration=inter_command_time+1, executeat=command_time.timestamp())
            else:
                self.dish.track(coords=command_frame, coord1=command_coords[0], coord2=command_coords[1], vel1=0.0, vel2=0.0, duration=inter_command_time+1, executeat=command_time.timestamp())

            # if command_frame == 'azel':
            #     self.dish.goto_posvel_azel(executeat=command_time.timestamp(), az_pos=command_coords[0], el_pos=command_coords[1], az_vel=0.0, el_vel=0.0)

            # #elif command_frame == 'azelvel':
            # #    self.dish.goto_posvel_azel_timed(time=command_time.timestamp(), az_pos=command_coords[0], el_pos=command_coords[1], az_vel=command_coords[2], el_vel=command_coords[3])

            # elif command_frame == 'radec':
            #     self.dish.track_radec(executeat=command_time.timestamp(), ra_pos=command_coords[0], dec_pos=command_coords[1], duration=inter_command_time+1)

            # else: #if command_frame == 'gal':
            #     self.dish.track_gal(executeat=command_time.timestamp(), l_pos=command_coords[0], b_pos=command_coords[1], duration=inter_command_time+1)

            if self.opt.verbose:
                if len(command_coords) > 2:
                    print(f" sent {command_frame} command: {command_coords[0]}, {command_coords[1]}, {command_coords[2]}, {command_coords[3]}")
                else:
                    print(f" sent {command_frame} command: {command_coords[0]}, {command_coords[1]}")

        print('done')
        sys.exit(1)




def parse_command_line():
    scriptname = os.path.basename(sys.argv[0])

    formatter = argparse.RawDescriptionHelpFormatter(scriptname)
    width = formatter._width

    title = "WR66_run_pointing_file"
    copyright = "Copyright (c) 2025 Massachusetts Institute of Technology"
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
        metavar="path_to_pointing_file",
        help="Path to csv file with antenna commands.",
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
        "-t",
        "--test",
        action="store_true",
        dest="test",
        default=False,
        help="skip radome server authentication and just check that file is valid",
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
        print("Please provide an input source with the -p option!")
        sys.exit(1)

    if options.verbose:
        print("options: {0}".format(options))

    dish_control = DishCommandProcessor(options)
    dish_control.run_commands()
