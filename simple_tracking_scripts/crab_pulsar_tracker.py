#!/usr/bin/env python3

###############################################
#
# maintains track of crab pulsar while running
#
###############################################

from bigdish_client import BigDishClient
import astropy.units as u
from astropy.coordinates import SkyCoord, ICRS
from astropy.time import Time

#crab pulsar J2000 coordinates

ra = 83.633125*u.degree #decimal degrees
dec = 22.0145*u.degree #decimal degrees

#crab pulsar proper motion

rav = -11.34*u.mas/u.year  #-11.34 milliarcseconds/year
decv = 2.65*u.mas/u.year   #2.65 milliarcseconds/year 

#position loop time (practically speeking this mostly just sets amount of time for dish to stop tracking if the program dies)
loop_cadence = 5*u.s


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
    print(f"Authentication as {username} FAILED! \r\n {response['reason']} \r\n")
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


#compute position correction for current date. Only bother to do this once
#even for the crab pulsar which is moving rather fast this seems not to matter much, less that 1/10000 beamwidth

print(f"Target position in J2000: Right Ascension = {ra}, Declination = {dec}")
print(f"Target proper motion: Right Ascension = {rav}, Declination = {decv}")

coords_J2000 = SkyCoord(ra=ra, dec=dec, pm_ra_cosdec=rav, pm_dec=decv, frame='icrs', obstime=Time('2000-01-01 12:00:00.0'))
coords_NOW = coords_J2000.apply_space_motion(new_obstime=Time.now())

coords_ra = coords_NOW.ra.degree
coords_dec = coords_NOW.dec.degree

print(f"Target Current Position: Right Ascension = {coords_ra}, Declination = {coords_dec}")

############################
#tracking loop
############################

last_loop_time = Time.now()-loop_cadence

while True:
    if (Time.now() - last_loop_time).to(u.s) >= loop_cadence:

        dish.track_radec(ra_pos=coords_ra, dec_pos=coords_dec, duration=(loop_cadence.to(u.s).value+0.1)) #add 0.1s duration to ensure a hair of overlap between commands

        pos = dish.get_posvel(coords='radec', power=False)

        ra_pos = pos['ra_pos']
        dec_pos = pos['dec_pos']
        ra_error = pos['ra_pos'] - coords_ra
        dec_error = pos['dec_pos'] - coords_dec

        print(f"Current Position: RA = {ra_pos}, RA ERROR = {ra_error}, DEC = {dec_pos}, DEC ERROR = {dec_error}")

        last_loop_time = Time.now()

