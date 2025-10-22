#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# dsheen 2025/10/16
# Tool for getting an expected band beam response for a given offset angle of the antenna relative to a source
# This has heritage to my temperature modelling code, which is why there are some unused cartesian arrays in this
# I've left that in to make it easier to incorporate back into a streamlined version of that code at some point

import os
import sys

wdir_path = os.path.dirname(os.path.realpath(__file__))
sys.path.append(os.path.join(wdir_path, '../dish_client')) 
sys.path.append(os.path.join(wdir_path, '../radio_client')) 
#sys.path.append(os.path.join(wdir_path, '../antenna_data')) 


import numpy as np
import scipy as sp
from scipy.stats import linregress
from matplotlib import pyplot as plt
from astropy.io import fits
import numpy as np
import json
import astropy.units as u
import astropy.constants as const
u.imperial.enable()

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
        self.norm_pattern_data = self.get_normalized_directivity(self.pattern_data)

        #flag if theta is 360 degree or 180 (eg, does phi need to be wrapped)
        self.theta_360 = True if np.min(self.thetas) < 0.0 else False




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

        directivity = 10*np.log10(np.max(Total_Directivity))
        print("total directivity = ", directivity)

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

    def get_normalized_directivity(self, pattern):
        #normalize peak directivity to unity
        patterndata = pattern.reshape(np.shape(pattern)[0]*np.shape(pattern)[1],9, order='F')
        directivity = np.max(patterndata[:,6])
        log_directivity = np.max(patterndata[:,5])
        patterndata[:,5] = patterndata[:,5] - log_directivity
        patterndata[:,6] = patterndata[:,6]/directivity
        patterndata[:,7] = patterndata[:,7]/directivity
        patterndata[:,8] = patterndata[:,8]/directivity
        
        return patterndata.reshape(np.shape(pattern), order='F')


    def get_linear_total_directivities(self, thetas, phis, normalized=True):
        """
        return the approx directivities of an array of points in theta/phi space

        thetas: array of theta values. should be between 0 and 180, 
        phis: array of phi values: should be between 0 and 360

        normalized: whether or not to return the normalized directivity value
        """

        #force coordinate systems to be compatible by switching thru cartesian and polar

        #get directivity pattern
        if normalized:
            linear_total_directivity = self.norm_pattern_data[:,:,6]
        else:
            linear_total_directivity = self.pattern_data[:,:,6]

        #get coordinate axes
        theta_axis = self.thetas
        phi_axis = self.phis
        #tack on a repeat values at the end to make life easier when interpolating
        #note this really should only ever matter for phi

        #create xy scaled coords

        x_axis = theta_axis * np.cos(np.deg2rad(phi_axis))
        y_axis = theta_axis * np.sin(np.deg2rad(phi_axis))

        x = thetas * np.cos(np.deg2rad(phis))
        y = thetas * np.sin(np.deg2rad(phis))



        #interpolate between points as necessary

        #interp_pattern = sp.interpolate.RegularGridInterpolator((theta_axis,phi_axis), linear_total_directivity, method="linear")
        #in this form if it's out of bounds it's probably more or less zero
        interp_pattern = sp.interpolate.LinearNDInterpolator(list(zip(x_axis,y_axis)), linear_total_directivity, bounds_error=False, fill_value=0.0)

        #return interp_pattern((thetavals, phivals))
        return interp_pattern((x, y))

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






