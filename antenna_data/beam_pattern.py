#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# dsheen 2025/10/16
# Tool for getting an expected band beam response for a given offset angle of the antenna relative to a source
# This has heritage to my temperature modelling code, which is why there are some unused cartesian arrays in this
# I've left that in to make it easier to incorporate back into a streamlined version of that code at some point

#updated with some improvements from sams code and rsc-sim 2026/01/21

import os
import sys

wdir_path = os.getcwd()#os.path.dirname(os.path.realpath(__file__))
sys.path.append(os.path.join(wdir_path, '../radio_client')) 
sys.path.append(os.path.join(wdir_path, '..')) 
#sys.path.append(os.path.join(wdir_path, '../antenna_data')) 


import numpy as np
import scipy as sp
from matplotlib import pyplot as plt
from astropy.io import fits
import numpy as np
import json
import astropy.units as u
import astropy.constants as const
u.imperial.enable()

from coord_frames import ground_to_beam_coord_vectorized, beam_to_ground_coord_vectorized


class BeamPattern(object):
    def __init__(
        self, 
        pattern_file_path=None,
        frequency=1420.0,
        phi_rotation=0.0,
        ):
        """
        Initialize beam pattern response generator object and pull in pattern data

        pattern_file_path: path top a ticra .cut formatted beam pattern
        frequency: desired frequency in MHz to analyze (must be present in file)
        phi_rotation: phi corresponding to a horizontal cut through the beam pattern
        """
        

        if pattern_file_path is not None:
            self.pattern_file = pattern_file_path
        else:
            self.pattern_file = "Real_feed_long_spars_and_feed_frame_dense.cut"
            #self.pattern_file = 'Real_feed_long_spars_and_feed_frame.cut'

        #get pattern
        self.frequency = frequency*u.MHz

        self.pattern_data, self.thetas, self.phis, self.thetastep, self.phistep = self.get_total_directivity_pattern([self.frequency])

        #flag if theta is 360 degree or 180 (eg, does phi need to be wrapped)
        self.theta_360 = True if np.min(self.thetas) < 0.0 else False

        #instantiate interpolators
        self.create_linear_interpolator()
        #self.norm_pattern_data = self.get_normalized_directivity(self.pattern_data)
        #self.create_normalized_linear_interpolator()
        



    def import_ticra_beam(self, freqs, progress=False):
        with open(self.pattern_file) as fh:
            #print(fh.readline())
            #print(fh.readline())
            farfield = fh.read()
            
            
            phicuts = farfield.split('Field data in cuts\n')
            num_phicuts_per_freq = int((len(phicuts)-1)/len(freqs))
            
            #data indices to be used later
            
            FF_indices = {'Freq':0, 'Phi':1, 'Theta':2, 'E_co':3, 'E_cx':4}
            data = []
            
            section_counter=0
            
            for section in phicuts:
                if not section.strip(): continue #skip dead section at start of file that I get somehow
                #section header is of form
                # -0.1800000000E+03  0.2000000000E-01       18001  0.0000000000E+00    3    1    2
                #where the above is thetastart, thetastep, numthetapoints,phi, otherdata
                lines = section.split('\n') #split by line
                #get headerdata
                thetastart,thetastep,thetacount,phi,ICOMP,ICON,NCOMP = lines[0].split()
                
                thetastart = float(thetastart)
                thetastep = float(thetastep)
                thetacount = float(thetacount)
                phi = float(phi)

                frequency = freqs[int(section_counter/num_phicuts_per_freq)]
                
                if progress: print(f"phicut {section_counter} frequency {frequency}")
                
                theta=thetastart+thetastep #because for some reason there is an off-by-one for thetastart
                
                #cutdata = np.asarray(lines[2::],dtype=np.float64)
                
                for line in lines[2::]:
                    if not line: continue
                    linedata = np.array(line.split(),dtype=np.float64)
                    Eco = linedata[0] + 1j * linedata[1]
                    Ecx = linedata[2] + 1j * linedata[3]
                    data.append(np.array([frequency, phi, theta, Eco, Ecx]))
                    theta +=thetastep
                    
                section_counter+=1
                
        return np.swapaxes(data,0,1), FF_indices

    def get_total_directivity_pattern(self, freqs):
        
        #get total directiveity from the pattern

        Bigdish_Fields, FF_indices = self.import_ticra_beam(freqs)

        Frequencies = np.real(Bigdish_Fields[FF_indices["Freq"]])
        Theta = np.real(Bigdish_Fields[FF_indices["Theta"]])
        Phi = np.real(Bigdish_Fields[FF_indices["Phi"]])
        
        Copolar_Directivity = np.power(np.abs(Bigdish_Fields[FF_indices["E_co"]]),2)
        Crosspolar_Directivity = np.power(np.abs(Bigdish_Fields[FF_indices["E_cx"]]),2)
        Total_Directivity = Copolar_Directivity+Crosspolar_Directivity

        self.directivity = 10*np.log10(np.max(Total_Directivity))
        print("total directivity = ", self.directivity)

        phistep = 180/len(np.unique(Phi))
        print(f'phistep = {phistep}')
        thetastep = 360/len(np.unique(Theta))
        print(f'thetastep = {thetastep}')
        
        #format array as (theta,phi,x,y,z,datapoint,datapoint_linear)

        patterndata = np.zeros([len(Total_Directivity),9],dtype=np.float32)

        #for i in range(len(Phi)):
        patterndata[:,0] = Theta
        patterndata[:,1] = Phi
        patterndata[:,5] = 10*np.log10(Total_Directivity) #patterns[:,1+i]
        patterndata[:,6] = Total_Directivity
        patterndata[:,7] = Copolar_Directivity
        patterndata[:,8] = Crosspolar_Directivity

        for i in range(len(Total_Directivity)):
            #do initial transforms to cartesian coords to make math easy
            patterndata[i,2] = np.sin(np.deg2rad(patterndata[i,0]))*np.cos(np.deg2rad(patterndata[i,1])) #X
            patterndata[i,3] = np.sin(np.deg2rad(patterndata[i,0]))*np.sin(np.deg2rad(patterndata[i,1])) #Y
            patterndata[i,4] = np.cos(np.deg2rad(patterndata[i,0])) #Z

            #and make all the datapoints available as linear values
            #patterndata[i,6] = 10**(patterndata[i,5]/10)
        #swap this into a format that's faster to operate on
        return patterndata.reshape(len(np.unique(Theta)),len(np.unique(Phi)),9, order='F'), np.unique(Theta), np.unique(Phi), thetastep, phistep
        
    def create_linear_interpolator(self):
        """
        create a non-normalized linear interpolator to be used for beam pattern modelling
        translated to cartesian centered on boresight to avoid rollover issues
        """
        linear_total_directivity = self.pattern_data[:,:,6].reshape(-1,1)
        
        theta_axis = self.pattern_data[:,:,0].reshape(-1,1) #self.thetas
        phi_axis = self.pattern_data[:,:,1].reshape(-1,1) #self.phis
        
        x_axis = theta_axis * np.cos(np.deg2rad(phi_axis))
        y_axis = theta_axis * np.sin(np.deg2rad(phi_axis))
        
        self.interp_pattern = sp.interpolate.LinearNDInterpolator(np.array([x_axis,y_axis]).swapaxes(0,1).reshape(-1,2), linear_total_directivity, fill_value=0.0)

    def get_linear_total_directivities(self, thetas, phis, normalized=False):
        """
        return the approx directivities of an array of points in theta/phi space

        thetas: array of theta values. should be between 0 and 180, 
        phis: array of phi values: should be between 0 and 360

        normalized: whether or not to return the normalized directivity value
        """

        #get coordinate axes

        x = thetas * np.cos(np.deg2rad(phis))
        y = thetas * np.sin(np.deg2rad(phis))

        #get directivity pattern
        if normalized:
            return np.squeeze(self.interp_pattern(x, y)) / self.directivity
        else:
            return np.squeeze(self.interp_pattern(x, y))


    def cartesian_angle_to_theta_phi(self, x_deg, y_deg):
        """
        Convenience tool to convert a cartesian angle in the 
        u/v axes to a polar angle about boresight so we can 
        input them to get the antenna response

        x: array of angles along horizontal axis
        y: array of angles along vertical axis
        """

        points = np.array([x_deg,y_deg]).swapaxes(0,1)
        thetas = np.sqrt(np.sum(np.power(points,2),axis=1))
        phis = (np.arctan2(y_deg, x_deg) * 180 /np.pi)%360

        return thetas, phis


    def az_el_to_theta_phi(self, az_pt, el_pt, az_ant, el_ant):
        """ 
        vectorized conversion between az/el coords 
        and coordinates in the beam pattern model
        with the beam pointed at different angles 

        az_pt: azimuth angle of interest
        el_pt: elevation angle of interest
        az_ant: antenna azimuth position
        el_ant: antenna elevation position

        returns theta/phis to index into antenna beam pattern
        """

        caz_pt = 360 - az_pt # convert to counter azimuth angle
        dec_pt = 90 - el_pt  # convert to declination angle

        caz_ant = 360 - az_ant
        dec_ant = 90 - el_ant

        theta, phi = ground_to_beam_coord_vectorized(np.radians(dec_pt), np.radians(caz_pt), np.radians(dec_ant), np.radians(caz_ant))
        phi = (np.degrees(phi) - 90) % 360 #subtract 90 to convert to horizontal 0 degree reference orientation
        theta = np.degrees(theta)

        return theta, phi

    def get_linear_antenna_gain(self, az_pt, el_pt, az_ant, el_ant):
        """ 
        vectorized function to return antenna gain at aa given angle
        givven the pointing position of the antenna

        az_pt: azimuth angle of interest
        el_pt: elevation angle of interest
        az_ant: antenna azimuth position
        el_ant: antenna elevation position

        returns theta/phis to index into antenna beam pattern
        """

        thetas, phis = self.az_el_to_theta_phi(az_pt, el_pt, az_ant, el_ant)
        gains = self.get_linear_total_directivities(thetas, phis)
        return np.squeeze(gains)





