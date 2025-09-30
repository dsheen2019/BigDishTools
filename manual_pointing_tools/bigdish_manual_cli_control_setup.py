#!/usr/bin/env python3

#######################################################################
#
# runs through basic client commands to make sure they seem to be happy
# and we can authenticate to the dish
#
#######################################################################

from bigdish_client import BigDishClient
#import astropy.units as u
#from astropy.coordinates import SkyCoord, ICRS
#from astropy.time import Time
import time
import datetime
import numpy as np


#instantiate the control client for bigdish
#please shut down other programs that control the dish nicely before using this

print("Authenticate to Dish Control Server \r\n")


username = input("Enter Username:")
password = input("Enter Password:")

#connect to control server

dish = BigDishClient("172.25.15.11", 1234) 

#authenticate to control server

response = dish.authenticate_connection(username, password)
if response['success']:
    print(f"Authenticated Successfully as {username}\r\n")
else:
    print(f"Authentication as {username} FAILED! \r\n {response['reason']} \r\n")
    exit()


print("Check for active users \r\n")

response = dish.get_active_users()

for user in response['users']:
    print(f'{user['account']} in state {user['state']}, last active at {datetime.datetime.fromtimestamp(user['last_active'])} UTC \r\n')

#ask if user wants to kick INITIALIZED users and take control of dish

response = input("Do you want to control the dish? existing INITIALIZED users will lose dish control. [yes/no] \r\n")

if response == 'yes':
    response = dish.initialize_connection(kick_others=True)
    if response['success'] == True:
        print('Sucessfully Initialized antenna control')
else:
    exit()

settled = True

while True:

    if settled:

        print('please enter desired azimuth and elevation coordinates at which to point antenna')
        az_target = float(input('azimuth?'  ))
        el_target = float(input('elevation?'  ))

        print(f'slewing antenna to {az_target},{el_target}')
        dish.goto_posvel_azel(az_target,el_target,0,0)
        settled=False
        time.sleep(0.05)
    else:
        pos = dish.get_posvel(coords='azel', power=False)

        az_pos = pos['az_pos']
        el_pos = pos['el_pos']
        az_error = (az_target - pos['az_pos'])
        el_error = (el_target - pos['el_pos'])

        print(f"Current Position: Az = {az_pos}, Az ERROR = {az_error}, El = {el_pos}, El ERROR = {el_error}")

        if (np.abs(az_error) < 0.1) & (np.abs(el_error) < 0.1):
            print(f"Converged at target: {az_pos}, {el_pos}")
            settled = True

        else:
            dish.goto_posvel_azel(az_target,el_target,0,0)

        time.sleep(0.05)

