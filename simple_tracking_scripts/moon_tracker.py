#!/usr/bin/env python3

###############################################
#
# maintains track of moon while running
#
###############################################

from bigdish_client import BigDishClient
import astropy.units as u
from astropy.coordinates import SkyCoord, EarthLocation, ICRS, AltAz, get_body
from astropy.time import Time

#bigdish coordinates

latitude = 42.360236
longitude = -71.089694
altitude = 100


location = EarthLocation.from_geodetic(lat=latitude * u.deg,
            lon=longitude * u.deg,
            height=altitude * u.m,
        )

#position loop time (practically speeking this mostly just sets amount of time for dish to stop tracking if the program dies)
loop_cadence = 5*u.s
command_cadence = 0.05*u.s


#instantiate the control client for bigdish
#please shut down other programs that control the dish nicely before using this

username = input("Enter Username:")
password = input("Enter Password:")

#connect to control server

dish = BigDishClient("172.25.15.11", 1234) 

#authenticate

response = dish.authenticate_connection(username, password)
if response['success']:
    print(f"Authenticated Successfully as {username}\r\n")
else:
    print(f"Authentication as {username} FAILED! \r\n {response["reason"]} \r\n")
    exit()

response = dish.initialize_connection(kick_others=False)

if response['success'] == True:
    print("Successfully acquired dish control")
else:
    print(f"Failed to get dish control. {response['reason']}\r\n")
    response = input("do you want to to forcibly kick other users? [y/n]")
    if response == 'y':
        response = dish.initialize_connection(kick_others=True)
        if response['success'] == True:
            print("Successfully acquired dish control")
        else:
            print(f"Failed to get dish control. {response['reason']}\r\n")
            exit()
    else:
        exit()


############################
#tracking loop
############################

last_compute_loop_time = Time.now()-loop_cadence
last_command_loop_time = Time.now()-command_cadence

while True:
    if (Time.now() - last_compute_loop_time).to(u.s) >= loop_cadence:

        last_compute_loop_time = Time.now()

        #compute moon coordinates and track
        t0 = Time(Time.now(), format = "unix")

        current_frame = AltAz(obstime=t0, location=location)
        current_coords = get_body(time=t0, body="Moon",location=location).transform_to(current_frame)
        future_frame = AltAz(obstime=t0+1*u.s, location=location)
        future_coords = get_body(time=t0+1*u.s, body="Moon",location=location).transform_to(future_frame)

        moon_az = current_coords.az.degree
        moon_el = current_coords.alt.degree
        moon_az_vel = future_coords.az.degree - current_coords.az.degree
        moon_el_vel = future_coords.alt.degree - current_coords.alt.degree

        print(f'Moon at Azel ({moon_az}, {moon_el}) degrees, moving at velocity ({moon_az_vel}, {moon_el_vel}) degrees per second')

        #dish.goto_posvel_azel(moon_az,moon_el,moon_az_vel,moon_el_vel)

        pos = dish.get_posvel(coords='azel', power=False)

        az_pos = pos['az_pos']
        el_pos = pos['el_pos']
        az_error = az_pos - moon_az
        el_error = el_pos - moon_el

        print(f"Current Position: Az = {az_pos}, Az ERROR = {az_error}, El = {el_pos}, El ERROR = {el_error}")

    elif (Time.now() - last_command_loop_time).to(u.s) >= command_cadence:
        last_command_loop_time = Time.now()

        elapsed_time = (Time.now() - last_compute_loop_time).to(u.s).value

        moon_az_current = moon_az + moon_az_vel*elapsed_time
        moon_elcurrent = moon_el + moon_el_vel*elapsed_time

        dish.goto_posvel_azel(moon_az_current,moon_elcurrent,moon_az_vel,moon_el_vel)

