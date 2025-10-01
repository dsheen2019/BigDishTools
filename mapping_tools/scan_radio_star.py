#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# dsheen 2025/09/30
# perform a grid scan of a radio star and log position data and calibrator states
# this is deliberately super handholdy to make it easier to use so it can be handed to new people

import os
import sys

wdir_path = os.path.dirname(os.path.realpath(__file__))
sys.path.append(os.path.join(wdir_path, '../dish_client')) 
sys.path.append(os.path.join(wdir_path, '../radio_client')) 

import digital_rf as drf
from datetime import datetime, timezone
import time
import argparse
import csv
import time

import numpy as np
import astropy.units as u
from astropy.coordinates import SkyCoord, ICRS
from astropy.time import Time

from radio_command_client import RadioZmqClient
from bigdish_client import BigDishClient

class RadioStarScanner(object):
    def __init__(self, opt):
        """initialize radio star scanner and start radio and dish connections"""

        self.opt = opt

        self.valid_frames = ['azel', 'gal', 'radec']
        self.coordinate_names = {
            'azel': ['az', 'el'],
            'gal': ['l', 'b'],
            'radec': ['ra', 'dec']
        }

        self.loop_constant = 0.5 #seconds

    def authenticate_to_bigdish(self):

        opt = self.opt

        if opt.test == False:

            username = opt.user if opt.user is not None else input("Enter Username for BigDish:")
            password = opt.password if opt.password is not None else input(f"Enter Password for User {username}:")

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

    def startup_radio_client(self):
        """
        last step before starting scan

        startup zmq client for radio (note in theory it's OK for thor to start after this but better not to)
        
        thor command should be something like:

        thor.py /tmp/ramdisk/data -m 172.25.14.11 -d "A:0 B:0" -c RHCP,LHCP -y "RX2,RX2" -f 1415e6 -F 20e6,20e6 -g 20 -r 4e6 --clock_source 'external' --time_source 'external' -M

        """

        response = input("Please start thor.py recording in a separate screen window using the the -M option and any other desired settings. Press enter to continue")

        self.radio = RadioZmqClient(sub_port=self.opt.sub_port, pub_port=self.opt.pub_port)

        time.sleep(1.0)
        self.initialize_gpio()
        time.sleep(1.0)

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

    def get_log_path(self):
        """get path to save logs to"""

        opt = self.opt

        self.out_dir = opt.path if opt.path is not None else input("Please enter absolute path to output directory to save position and calibrator state logs:")

    def get_scan_coordinates(self):
        """get coordinates for scan"""

        opt = self.opt

        ## coordinate frame

        if opt.frame in self.valid_frames:
            self.frame = opt.frame
        else:
            invalid_frame = True
            while invalid_frame: #be nice and loop this one if user typos something
                frame = input("Please enter coordinate frame for scan ('azel', 'radec', or 'gal'):")
                if frame in self.valid_frames:
                    self.frame = frame
                    invalid_frame = False

        ##center point
        if opt.center == None:
            coord1 = float(input(f"please enter {self.coordinate_names[self.frame][0]} coordinate of scan center in decimal degrees:"))
            coord2 = float(input(f"please enter {self.coordinate_names[self.frame][1]} coordinate of scan center in decimal degrees:"))

            self.center = np.array([coord1,coord2])

        elif len(opt.center) < 2:
            coord1 = float(input(f"please enter {self.coordinate_names[self.frame][0]} coordinate of scan center in decimal degrees:"))
            coord2 = float(input(f"please enter {self.coordinate_names[self.frame][1]} coordinate of scan center in decimal degrees:"))

            self.center = np.array([coord1,coord2])

        else:
            self.center = np.array(opt.center)

        ##scan bounds
        if opt.bounds == None:
            coord1 = float(input(f"please enter {self.coordinate_names[self.frame][0]} half-width of scan in decimal degrees:"))
            coord2 = float(input(f"please enter {self.coordinate_names[self.frame][1]} half-width of scan in decimal degrees:"))

            self.bounds = np.array([coord1,coord2])

        elif len(opt.bounds) < 2:
            coord1 = float(input(f"please enter {self.coordinate_names[self.frame][0]} half-width of scan in decimal degrees:"))
            coord2 = float(input(f"please enter {self.coordinate_names[self.frame][1]} half-width of scan in decimal degrees:"))

            self.bounds = np.array([coord1,coord2])

        else:
            self.bounds = np.array(opt.bounds)

        ### step sizes
        if opt.step == None:
            coord1 = float(input(f"please enter {self.coordinate_names[self.frame][0]} step size in decimal degrees:"))
            coord2 = float(input(f"please enter {self.coordinate_names[self.frame][1]} step size in decimal degrees:"))

            self.step = np.array([coord1,coord2])

        elif len(opt.step) < 2:
            coord1 = float(input(f"please enter {self.coordinate_names[self.frame][0]} step size in decimal degrees:"))
            coord2 = float(input(f"please enter {self.coordinate_names[self.frame][1]} step size in decimal degrees:"))

            self.step = np.array([coord1,coord2])
        else:
            self.step = np.array(opt.step)

    def get_recording_parameters(self):
        """
        how long should we hold on a point? how long should we calibrate for at each point?
        """

        opt = self.opt

        #nominal integration time

        if opt.integration is not None:

            try:
                self.integration = float(opt.integration)
            except:
                self.integration = float(input("Please provide desired hold time for integration at each point in seconds:"))
        else:
            self.integration = float(input("Please provide desired hold time for integration at each point in seconds:"))

        #nominal calibration time

        if opt.calibration is not None:
            try:
                self.calibration = float(opt.calibration)
            except:
                self.calibration = float(input("Please provide desired calibration time at each point in seconds:"))
        else:
            self.calibration = float(input("Please provide desired calibration time at each point in seconds:"))


    def compute_scan_points(self):
        """
        compute the points in the scan and estimate completion time
        """

        axis_0_num_points = int(2*self.bounds[0]/self.step[0])+1
        edge_0 = (axis_0_num_points -1)/2 * self.step[0]
        axis_0_points = self.center[0] + np.linspace(-edge_0,edge_0,axis_0_num_points)
       
        axis_1_num_points = int(2*self.bounds[1]/self.step[1])+1
        edge_1 = (axis_1_num_points -1)/2 * self.step[1]
        axis_1_points = self.center[1] + np.linspace(-edge_1,edge_1,axis_1_num_points)

        scan_points = []
        #note this could be more efficient with reversing scan direction on each line but bigdish is fast so we don't really care that much. 
        #may be worth changing to make any backgrund variability easier to smooth out though by having each point as close as possible to previous
        for point1 in axis_1_points:
            for point0 in axis_0_points:
                scan_points.append([point0,point1])

        self.scan_points = np.array(scan_points)
        self.num_points = np.shape(self.scan_points)[0]
        self.limits = np.array([edge_0,edge_1])

    def confirm_scan(self):
        """estimate scan time and make sure user really wants to do it"""
        hold_time = self.calibration* 2 + self.integration
        scan_time = (hold_time + np.log10(10*max(self.step))+1) * self.num_points #point to point settling estimation is very very approximate, but just meant to be an ok guess here
        waiting = True
        while waiting:
            response = input(f"scan will contain {self.num_points} points and take approximately {(scan_time / 3600):0.2f} hours. are you sure you want to proceed? [y/n]")
            if response == 'y':
                waiting = False
            elif response == 'n':
                print("cancelling scan and exiting")
                exit()
            else:
                print("please respond 'y' or 'n' ")

        self.hold_time = hold_time

    def get_antenna_position(self):
        """query and log antenna pointing position and time
        return current posvel data for settling check"""

        posname_0 = f"{self.coordinate_names[self.frame][0]}_pos"
        posname_1 = f"{self.coordinate_names[self.frame][1]}_pos"
        velname_0 = f"{self.coordinate_names[self.frame][0]}_vel"
        velname_1 = f"{self.coordinate_names[self.frame][1]}_vel"

        posvel = self.dish.get_posvel(coords=self.frame, power=False)

        return np.array([posvel[posname_0], posvel[posname_1], posvel[velname_0], posvel[velname_1]]), posvel['time']

    def log_antenna_position(self, pos, time):
        """log antenna pointing position and time"""

        self.log_file.write(f"position,{datetime.utcfromtimestamp(time).isoformat()}Z,{pos[0]:.4f},{pos[1]:.4f},{pos[2]:.4f},{pos[3]:.4f}\r\n")

        if self.opt.verbose:
            print(f"position,{datetime.utcfromtimestamp(time).isoformat()}Z,{pos[0]:.4f},{pos[1]:.4f},{pos[2]:.4f},{pos[3]:.4f}\r\n")

    def log_calibrator_state_change(self, state, timestamp):
        """log calibrator state timing (note this is feedforward) time is utc timestamp"""
        self.log_file.write(f"calibrator_state,{datetime.utcfromtimestamp(timestamp).isoformat()}Z,{state}\r\n")

        if self.opt.verbose:
            print(f"calibrator_state,{datetime.utcfromtimestamp(timestamp).isoformat()}Z,{state}\r\n")

    def log_target(self, target, timestamp):
        """log target points antenna is commanded for"""
        self.log_file.write(f"target_point,{datetime.utcfromtimestamp(timestamp).isoformat()}Z,{self.frame},{target[0]:.3f},{target[1]:.3f}\r\n")

        if self.opt.verbose:
            print(f"target_point,{datetime.utcfromtimestamp(timestamp).isoformat()}Z,{self.frame},{target[0]:.3f},{target[1]:.3f}\r\n")


    def check_settling(self, target, position):
        """ check is antenna is sufficiently settled for us to be ok with it"""
        thresholds = np.array([0.1, 0.1, 0.1, 0.1]) #thresholds for positions and relative velocities

        target_posvel = np.array([target[0], target[1], 0, 0]) # add velocities to target position info

        error = position-target_posvel

        settled = True if np.sum(np.where(np.abs(error)<thresholds, 0, 1)) < 1 else False
        if self.opt.verbose:
            print(f"settled: {settled}, current posvel error: {error}\r\n")

        return settled

    def wait_for_integer_second(self):
        now = time.time()
        delay = int(now)-now + 1.0
        time.sleep(delay)


    def scan_radio_star(self):
        """
        ##################################################
        run scan of desired radio star/make things happen
        ##################################################
        """

        opt = self.opt

        ## initialize things and prompt user responses
        self.authenticate_to_bigdish() #do this first since if something is wrong here it's better to know immediately

        self.get_log_path()
        self.get_scan_coordinates()
        self.get_recording_parameters()

        self.compute_scan_points()
        self.confirm_scan()

        self.startup_radio_client() #do this last so we don't prompt the user to start a recording early and needlessly waste disk space

        print(f"starting scan centered at {self.frame} coordinates {self.center[0]:.3f},{self.center[0]:.3f} at {datetime.utcfromtimestamp(time.time()).isoformat()}Z\r\n")

        #create log directory if it doesn't exist yet
        os.makedirs(opt.path,exist_ok=True)
        log_file_name = f"{datetime.utcfromtimestamp(time.time()).isoformat()}Z_{self.frame}_{self.center[0]:.2f}_{self.center[0]:.2f}.log"


        with open(os.path.join(self.opt.path,log_file_name), 'w') as self.log_file:
        #self.log_file = open(os.path.join(self.opt.path,log_file_name), 'w')

            # add some info at beginning of log
            self.log_file.write(f"scan_coords,{self.frame}\r\n")
            self.log_file.write(f"scan_center,{self.center[0]:.3f},{self.center[0]:.3f}\r\n")
            self.log_file.write(f"extents,{self.limits[0]:.3f},{self.limits[1]:.3f}\r\n")
            self.log_file.write(f"steps,{self.step[0]:.3f},{self.step[1]:.3f}\r\n")
            self.log_file.write(f"num_points,{self.num_points}\r\n")
            self.log_file.write(f"integration_time,{self.integration}\r\n")
            self.log_file.write(f"cal_time,{self.calibration}\r\n")

        #setup some things for calibration
        if self.calibration >0:
            cal_states = [1,2,0]
        else: 
            cal_states = [0]

        #actually do things
        for i in range(self.num_points): #iterate over all desired pointing positions

            with open(os.path.join(self.opt.path,log_file_name), 'a') as self.log_file: #do this per point just to force it to actually write to disk regularly
                target = self.scan_points[i]
                #if opt.verbose:
                print(f"moving to point {i+1} of {self.num_points} at coordinates {target[0]:.3f}, {target[1]:.3f}\r\n")

                position_command_time = time.time() #issue this command instantly

                #start tracking target point
                if opt.test == False:
                    self.dish.track(coords=self.frame, coord1=target[0], coord2=target[1], vel1=0.0, vel2=0.0, duration=(self.hold_time + 20.0), executeat=position_command_time)

                self.log_target(target, position_command_time)

                #start running settling check
                settled = False
                self.wait_for_integer_second() #index log to a vaguely nonsilly time
                while settled == False:
                    now = time.time()
                    time.sleep(self.loop_constant - (now % self.loop_constant)) #only bother checking every half second or so
                    if opt.test == False:
                        posvel, postime = self.get_antenna_position()
                    else: #fake posvel to test rest of code
                        posvel = np.array([target[0], target[1], 0, 0])
                        postime = time.time()
                    self.log_antenna_position(posvel,postime)
                    settled = self.check_settling(target, posvel)
                    

                now = time.time()
                obs_start = int(now+0.5)+1 #guarantee radio can respond fast enough and dish has really fully settled more or less
                obs_end = obs_start + self.hold_time
                #record settling
                self.log_file.write(f"settled,{datetime.utcfromtimestamp(now).isoformat()}Z\r\n")
                print(f"settled at target position, waiting for {self.hold_time} seconds")


                #calibrator sequencing commands #timing this way is annoying 
                offset = 0
                for state in cal_states:

                    self.radio.set_command_timestamp(obs_start + offset * self.calibration)
                    self.radio.set_gpio_state(state)
                    self.radio.clear_command_time()
                    self.log_calibrator_state_change(state, obs_start)
                    offset +=1
                    time.sleep(0.1) #just don't want to overwhelm radio
                
                #run wait through the rest of the observation window
                while now < obs_end:
                    now = time.time()
                    time.sleep(self.loop_constant - (now % self.loop_constant))
                    if opt.test == False:
                        posvel, postime = self.get_antenna_position()
                    else: #fake posvel to test rest of code
                        posvel = np.array([target[0], target[1], 0, 0])
                        postime = time.time()
                    self.log_antenna_position(posvel,postime)


        print(f"scan finished at {datetime.utcfromtimestamp(time.time()).isoformat()}Z")
        print(f"returning antenna to stow position and exiting")
        self.dish.stow_pos()

##################################################
# command line things
###################################################
def evalint(s):
    """Evaluate string to an integer."""
    return int(eval(s, {}, {}))


def evalfloat(s):
    """Evaluate string to a float."""
    return float(eval(s, {}, {}))


def intstrtuple(s):
    """Get (int, string) tuple from int:str strings."""
    parts = [p.strip() for p in s.split(":", 1)]
    if len(parts) == 2:
        return int(parts[0]), parts[1]
    else:
        return None, parts[0]


def noneorstr(s):
    """Turn empty or 'none' string to None."""
    if s.lower() in ("", "none"):
        return None
    else:
        return s


def noneorfloat(s):
    """Turn empty or 'none' to None, else evaluate to float."""
    if s.lower() in ("", "none"):
        return None
    else:
        return evalfloat(s)


def noneorbool(s):
    """Turn empty or 'none' string to None, all others to boolean."""
    if s.lower() in ("", "none"):
        return None
    elif s.lower() in ("true", "t", "yes", "y", "1"):
        return True
    else:
        return False


def noneorboolorfloat(s):
    """Turn empty or 'none' to None, else evaluate to a boolean or float."""
    if s.lower() in ("", "none"):
        return None
    elif s.lower() in ("auto", "true", "t", "yes", "y"):
        return True
    elif s.lower() in ("false", "f", "no", "n"):
        return False
    else:
        return evalfloat(s)


def noneorboolorcomplex(s):
    """Turn empty or 'none' to None, else evaluate to a boolean or complex."""
    if s.lower() in ("", "none"):
        return None
    elif s.lower() in ("auto", "true", "t", "yes", "y"):
        return True
    elif s.lower() in ("false", "f", "no", "n"):
        return False
    else:
        return complex(eval(s, {}, {}))

class Extend(argparse.Action):
    """Action to split comma-separated arguments and add to a list."""

    def __init__(self, option_strings, dest, type=None, **kwargs):
        if type is not None:
            itemtype = type
        else:

            def itemtype(s):
                return s

        def split_string_and_cast(s):
            return [itemtype(a.strip()) for a in s.strip().split(",")]

        super(Extend, self).__init__(
            option_strings, dest, type=split_string_and_cast, **kwargs
        )

    def __call__(self, parser, namespace, values, option_string=None):
        cur_list = getattr(namespace, self.dest, [])
        if cur_list is None:
            cur_list = []
        cur_list.extend(values)
        setattr(namespace, self.dest, cur_list)



def parse_command_line():
    scriptname = os.path.basename(sys.argv[0])

    formatter = argparse.RawDescriptionHelpFormatter(scriptname)
    width = formatter._width

    title = "scan radio star"
    copyright = "Copyright (c) 2025 Massachusetts Institute of Technology"
    shortdesc = """Tool to automattically scan a grid in ra/dec around a radio star or specified ra/dec point and control the LNA calibrators on bigdish. saves position and caliibrator timing log to a specified directory for use in subsequent data analysis.
    If you fail to enter required parameters you will be prompted to provide them"""
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
        help="absolute path to folder to save log data.",
    )
    parser.add_argument(
        "-f",
        "--frame",
        dest="frame",
        default=None,
        help="coordinate frame for scan ('azel', 'radec', or 'gal')",
    )
    parser.add_argument(
        "-c",
        "--center",
        dest="center",
        action=Extend,
        type=evalfloat,
        help="""center point coordinates of scan """,
    )
    parser.add_argument(
        "-b",
        "--bounds",
        dest="bounds",
        action=Extend,
        type=evalfloat,
        help="""distance to scan away from center point [axis0, axis2]""",
    )
    parser.add_argument(
        "-s",
        "--step",
        dest="step",
        action=Extend,
        type=evalfloat,
        help="""step in each axis of coordinate system [axis0, axis2]""",
    )
    parser.add_argument(
        "-i",
        "--integration",
        dest="integration",
        default=None,
        help="""desired time in seconds to hold on a scan point""",
    )
    parser.add_argument(
        "-C",
        "--calibration",
        dest="calibration",
        default=None,
        help="""desired calibtrator cycle time in seconds""",
    )
    parser.add_argument(
        "-t",
        "--test",
        action="store_true",
        dest="test",
        default=False,
        help="skip radome server authentication and just make sure the program otherwise runs properly",
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

    #if options.path is None:
    #    print("Please provide an input source with the -p option!")
    #    sys.exit(1)

    #if options.verbose:
    #    print("options: {0}".format(options))

    radio_star_scanner = RadioStarScanner(options)
    radio_star_scanner.scan_radio_star()