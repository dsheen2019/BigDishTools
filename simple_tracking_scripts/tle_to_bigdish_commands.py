#!/usr/bin/env python3
# -*- coding: utf-8 -*-

#program to take a single TLE and pass start and stop times and generate a command file for bigdish to track it

from skyfield.api import load, wgs84, EarthSatellite
from pathlib import Path
from urllib.request import urlopen
from sgp4 import omm
from sgp4.api import Satrec
from datetime import datetime, timedelta
from operator import itemgetter
import pandas as pd
import numpy as np
import re
import numpy as np
import os
import argparse
import sys

class TLE_converter(object):
    def __init__(self, opt):
        """set up tool to generate sets of target 
        coordinates and times for westford and bigdish"""

        self.opt = opt

        # time scale
        self.ts = ts = load.timescale()

        #start and end times in timescale

        self.start_time = datetime.fromisoformat(opt.start_time)
        self.end_time = datetime.fromisoformat(opt.end_time)
        self.interval =timedelta(seconds=self.opt.interval)

        self.time_format = '%Y-%m-%dT%H:%M:%S.%f'

        #set up dictionary with antenna params

        antennas ={
            "bigdish" : 
                {
                "slew_time" : 30,
                "min_elevation" : 0.0,
                "max_elevation" : 87.0,
                "coords_wgs84" : 
                    {
                    "lat" : 42.360236,
                    "lon" : -71.089478,
                    "el" : 97.0,
                    },
                },
            }

        #add full coordinate objects after instantiating dict (this just feels neater that the other way I might do it)
        for antenna in antennas:
            coords = antennas[antenna]["coords_wgs84"]
            antennas[antenna]['coord_obj'] = wgs84.latlon(coords["lat"], coords["lon"], coords["el"])

        self.antennas = antennas

    def import_tles(self):

        #import satellites
        filepath = self.opt.tle_path
        sats = {}
        with open(filepath, 'r') as f:
            lines = f.readlines()
            for i in range(0, len(lines), 3):
                name = lines[i].strip()
                tle1 = lines[i+1].strip()
                tle2 = lines[i+2].strip()
                sat = Satrec.twoline2rv(tle1, tle2)
                e = EarthSatellite.from_satrec(sat, self.ts)
                e.name = name
                sats[name] = e

        return sats

    def generate_track(self, telescope, sat, start, end, interval):

        #do what we need to make times work

        ts=self.ts
        times = pd.date_range(start,end,freq=interval)

        diff_sat = sat - telescope["coord_obj"]

        #get satellite track

        track = []
        for time in times:
            alt, az, distance = diff_sat.at(ts.from_datetime(time)).altaz()
            next_alt, next_az, next_distance = diff_sat.at(ts.from_datetime(time + interval)).altaz()

            az_vel = (next_az.degrees - az.degrees) / self.opt.interval #note this is deliberately dividing by the unconverted float seconds
            if az_vel < -180.0: #catch large numbers caused by zero crossings
                az_vel = (next_az.degrees - az.degrees + 360.0) / self.opt.interval
            elif az_vel > 180.0: 
                az_vel = (next_az.degrees - az.degrees - 360.0) / self.opt.interval

            el_vel = (next_alt.degrees - alt.degrees) / self.opt.interval #note this is deliberately dividing by the unconverted float seconds
            if el_vel < -180.0: #catch large numbers caused by zero crossings
                el_vel = (next_alt.degrees - alt.degrees + 360.0) / self.opt.interval
            elif el_vel > 180.0: 
                el_vel = (next_alt.degrees - alt.degrees - 360.0) / self.opt.interval

            track.append([time, az.degrees, alt.degrees, az_vel, el_vel])

        track[-1][3] = 0 #zero out the velocities at the end of the pass
        track[-1][4] = 0 #zero out the velocities at the end of the pass

        return track

    def write_command_file(self, track):

        antenna_cmd_filename = f"{self.opt.out_file}"
        antenna_file = open(antenna_cmd_filename, "w") #open command files  we are writing to.

        #move the antenna to start in advance and have it sitting there at the start
        antenna_file.write(f"{(track[0][0]-timedelta(seconds=30)).strftime('%Y-%m-%dT%H:%M:%SZ')}, azel, {track[0][1]:0.3f}, {track[0][2]:0.3f}, 0.000, 0.000\r\n")

        # write antenna slew commands for the main track

        for line in track:
            antenna_file.write(f"{line[0].strftime('%Y-%m-%dT%H:%M:%SZ')}, azel, {line[1]:0.3f}, {line[2]:0.3f}, {line[3]:0.3f}, {line[4]:0.3f}\r\n")
            

    def convert_tle_to_commands(self):

        sats = self.import_tles()

        track = self.generate_track(self.antennas['bigdish'], sats[self.opt.sat_name], self.start_time, self.end_time, self.interval)

        self.write_command_file(track)




def parse_command_line():
    scriptname = os.path.basename(sys.argv[0])

    formatter = argparse.RawDescriptionHelpFormatter(scriptname)
    width = formatter._width

    title = "Bigdish satellite tracking command generator"
    copyright = "Copyright (c) 2025 Massachusetts Institute of Technology"
    shortdesc = "Generate vector command file for bigdish to track a satellite based on a tle"
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
        "tle_path",
        nargs="?",
        default=None,
        metavar="tle_path",
        help="path to source file with satellite tles",
    )
    parser.add_argument(
        "-n",
        "--sat",
        dest="sat_name",
        type=str,
        help="""Name of satellite in TLE file to track""",
    )
    parser.add_argument(
        "-s",
        "--start",
        dest="start_time",
        type=str,
        help="""Start of tracking commands as UTC Time in ISO Format (e.g. 2025-06-24T00:25:43Z)""",
    )
    parser.add_argument(
        "-e",
        "--end",
        dest="end_time",
        type=str,
        help="""End of track as UTC Time in ISO Format (e.g. 2025-06-24T00:25:43Z)""",
    )
    parser.add_argument(
        "-i",
        "--interval",
        dest="interval",
        type=float,
        default=1.0,
        help="""command interval for tracking commands""",
    )
    parser.add_argument(
        "-o",
        "--out",
        dest="out_file",
        type=str,
        help="""Where should I put the output file?""",
    )

    options = parser.parse_args()

    return options


# Setup Defaults
if __name__ == "__main__":
    """
    Needed to add main function to use outside functions outside of module.
    """

    # Parse the Command Line for configuration
    options = parse_command_line()
    if options.tle_path is None:
        print("Please provide an input file")
        sys.exit(1)
    if options.sat_name is None:
        print("Please provide name of satellite to track")
        sys.exit(1)
    if options.start_time is None:
        print("Please provide start time with the -s flag")
        sys.exit(1)
    if options.end_time is None:
        print("Please provide end time with the -e flag")
        sys.exit(1)


    converter = TLE_converter(options)
    converter.convert_tle_to_commands()