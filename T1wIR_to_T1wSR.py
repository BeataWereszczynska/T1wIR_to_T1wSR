# -*- coding: utf-8 -*-
"""
Calculating T1-weighted (saturation recovery) MRI images for theoretical values of TR 
from a set of T1-weighted (inversion recovery) experimental MRI images
(for Agilent SEMS-IR .fid data).


@author: Beata Wereszczyńska
"""

# .......... User defined parameters ........................................................

path = 'sems_20190407_07.fid'      # .fid folder location [str]
T_wish = [100, 500, 1000, 7000]    # list of TR values (ms) for theoretical MRI images


glob_var = 0           # save the new images in a python global variable? [int]
                       # 0 - run without saving anything as a global variable
                       # 1 - run with saving the new images in a global variable
                       # 2 - run with saving the new images and the maps in global variables

# .......... End of user defined parameters .................................................


import nmrglue as ng
import numpy as np
import matplotlib.pyplot as plt
from scipy.optimize import curve_fit
import os
import shutil
import warnings
import joblib
from joblib.externals.loky import get_reusable_executor


def get_images(number_of_images, echoes):
    
    # dividing the data into k-spaces
    kspaces = np.empty((number_of_images, int(echoes.shape[0]/number_of_images), 
                        echoes.shape[1]), dtype=np.complex_)
    
    for kspace_no in range(0,number_of_images):
        
        kspaces[kspace_no] = echoes[kspace_no : echoes.shape[0] : number_of_images, :]        
    
    # calculating images from k-spaces
    images = np.empty(kspaces.shape)
    
    for kspace_no in range(0,number_of_images):
        ft = np.fft.fft2(kspaces[kspace_no])
        ft = np.fft.fftshift(ft)              # fixing problem with corner being center of the image
        ft = np.transpose(np.flip(ft, (1,0))) # matching geometry with VnmrJ-calculated image (still a bit shifted)
        images[kspace_no] = abs(ft)
        
    return images

def reorder_forT1IR(images, nI, number_of_images):
    shape = images.shape
    images = np.reshape(images, (nI, int(number_of_images/nI), shape[1], shape[2]))
    images = np.transpose(images, (1, 0, 2, 3))
    images = np.reshape(images, shape)
    return images

def T1_IR_function(x, T1, Mo, C, a):             # y = SI, x = TI, a = approx. 2
    x = np.array(x)
    y = abs(Mo * (1 - a* np.exp(-x/T1)) + C)
    return y

def T1_SR_function(x, T1, Mo, C, a):             # y = SI, x = TR
    x = np.array(x)
    y = Mo * (1 - np.exp(-x/T1)) + C
    return y

def calculate_maps(images, T_train, function):
    
    T_maps = []
    Momaps = []
    Cmaps = []
    nE_nI = len(T_train)
    

    for i in range(int(images.shape[0]/nE_nI)):
    
        a = nE_nI*i
        b = nE_nI*(i+1)
        
        slice1 = images[a:b]
        
        T_list = []
        Molist = []
        Clist = []
        
        for k in range(0,slice1.shape[1]):
                        
            def task(j):
                points = slice1[:, k, j]
                
                
                bounds = ([0.001, points.max()*0.9, -(points.max()/100+1), 1.85],
                          [7000, 2*points.max()+1, points.max()/100+1, 2.05])
                
                try:
                    parameters = curve_fit(function, T_train, points, 
                                           bounds=bounds, maxfev = 1000)[0]
                except RuntimeError:
                   
                    parameters = [0.000001,points.max(),0,2]
                   
                    
                return parameters
            
            with joblib.parallel_backend(backend="loky"):
                result = joblib.Parallel(n_jobs=-1)(joblib.delayed(task)(j) for j in range(0,slice1.shape[2]))
                
            result = np.array(result)
            T_list.append(result[:, 0])
            Molist.append(result[:, 1])
            Clist.append(result[:, 2])
        
        T_maps.append(np.reshape(np.array(T_list), (slice1.shape[1],slice1.shape[2])))
        Momaps.append(np.reshape(np.array(Molist), (slice1.shape[1],slice1.shape[2])))
        Cmaps.append(np.reshape(np.array(Clist), (slice1.shape[1],slice1.shape[2])))
                
    get_reusable_executor().shutdown() # close joblib processes
    
    return T_maps, Momaps, Cmaps


def theoret_MRI(function, T_wish, T_maps, Momaps, Cmaps):
    
        
    TheoretImgs = []
    out_folder = 'Theoretical_MRI'
    shutil.rmtree(out_folder, ignore_errors=True)  # removing residual output folder with content
    os.makedirs(out_folder)                        # creating new output folder
    
    
    for i in range(len(T_wish)):
        
        for j in range(len(Momaps)):
                       
            SI_image = function(T_wish[i], T_maps[j], Momaps[j], Cmaps[j], 2)
            
                
            TheoretImgs.append(SI_image)
            
            SI_image *= 255.0/SI_image.max()
            plt.imsave(fname=f'Theoretical_MRI/slice_{j+1}_TR_{T_wish[i]}ms.png', 
                       arr=SI_image, cmap='gray')
    
    return TheoretImgs



def main(path, T_wish, glob_var):
    
    # deleting global variables - already have them as local
    del globals()['path']
    del globals()['T_wish']
    del globals()['glob_var']
    
    # k-space data import with supressed nmrglue warnings
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        params, echoes = ng.agilent.read(dir=path)
        
    del path

    # calculations
    if params['procpar']['layout']['values'][0] == 'sems' and params['procpar']['ir']['values'][0] == 'y':
        
        print('(1/3) Recognised T1-weighted (SEMS-IR) images.')
        
        # parameters of use    
        TI_train = np.array([eval(i) for i in (params['procpar']['ti']['values'])])*1000
        number_of_images = params['ntraces'] * len(TI_train)
        del params
        
        print('(2/3) Calculations in progress - please have patience...')
        
        # calculating images from the data
        images = get_images(number_of_images, echoes)
        del echoes
        
        #reordering the images
        images = reorder_forT1IR(images, len(TI_train), number_of_images)
        del number_of_images
        
        # calculating parametric maps
        T1maps, Momaps, Cmaps = calculate_maps(images, TI_train, T1_IR_function)
        del TI_train, images
        
        # calculating and saving theoretical images
        TheoretImgs = theoret_MRI(T1_SR_function, T_wish, T1maps, Momaps, Cmaps)
        print('(3/3) New image(s) saved.')
        
        if glob_var == 1:
            return TheoretImgs
        
        elif glob_var == 2:
            return TheoretImgs, T1maps, Momaps
        
    
        
    # message: unsupported data
    else:
        print('Error: not SEMS-IR data.')
    
    
if __name__ == "__main__":
    
    if glob_var == 1:
        TheoretImgs = main(path, T_wish, glob_var)
    
    elif glob_var == 2:
        TheoretImgs, T_maps, Momaps = main(path, T_wish, glob_var)
        
    else:
        main(path, T_wish, glob_var)
