'''cloud_image provides methods for extracting data from the .mat files
generated by our ImagingGUI'''

import scipy
import scipy.io
import re
from scipy.optimize import curve_fit
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import os
from math import sqrt
from scipy.ndimage import rotate, filters
from fit_functions import *
import BECphysics as bp
from BECphysics import C, H, LAMBDA_RB

DEBUG_FLAG = False

FILE_RE = re.compile(r'.(\d{6})\.mat')

DEFAULT_IMAGE_TIME = 10e-6 #sec
DEFAULT_I_SAT = 30.54 # W/m**2, for pi light 

def image_subtract(im1, im2):
    ''' return the absolute value of im1 - im2'''
    return np.where(im1 > im2, im1 - im2, im2 - im1)

class FitError(Exception):
    '''A rather generic error to raise if the gaussian fit fails'''
    def __init__(self, statement="Fit Error"):
        self.statement = statement

class CloudImage(object):
    '''CloudImage represents the information contained in a .mat file
    generated by our ImagingGUI'''
    def __init__(self, filename):
        self.mat_file = {}
        self.filename = filename
        self.load_mat_file()
        
        self.image_angle_corr = 1 #this is not really implemented yet.

    def load_mat_file(self):
        '''Load a .mat file'''
        scipy.io.loadmat(self.filename, mdict=self.mat_file,
                            squeeze_me=True, struct_as_record=False)

        self.image_array = self.mat_file['rawImage']
        self.run_data_files = self.mat_file['runData']
        self.hfig_main = self.mat_file['hfig_main']

        self.cont_par_name = self.run_data_files.ContParName
        self.curr_cont_par = self.run_data_files.CurrContPar
        self.curr_tof = self.run_data_files.CurrTOF*1e-3

        self.atom_image = scipy.array(self.image_array[:, :, 0])
        #scipy.array is called to make a copy, not a reference
        self.light_image = scipy.array(self.image_array[:, :, 1])
        self.dark_image = scipy.array(self.image_array[:, :, 2])

        self.magnification = self.hfig_main.calculation.M
        self.pixel_size = self.hfig_main.calculation.pixSize
        self.image_rotation = self.hfig_main.display.imageRotation
        self.c1 = self.hfig_main.calculation.c1 # what is this?
        self.s_lambda = self.hfig_main.calculation.s_lambda # atomic cross section
        self.A = self.hfig_main.calculation.A # real space pixel area

        if 3.0e-6<self.pixel_size<4.0e-6:
            #dragonfly
            self.cameratype = 'dragonfly'
            self.quantum_efficiency = 0.20
        elif 12.0e-6<self.pixel_size<14.0e-6:
                #pixis
            self.cameratype = 'pixis'
            self.quantum_efficiency = 1.03
        else:
            self.cameratype = 'unknown'
            self.quantum_efficiency = None

        self.trunc_win_x = self.hfig_main.calculation.truncWinX
        self.trunc_win_y = self.hfig_main.calculation.truncWinY
        self.trunc_x_lim = (self.trunc_win_x[0], self.trunc_win_x[-1])
        self.trunc_y_lim = (self.trunc_win_y[0], self.trunc_win_y[-1])
        
        if self.image_rotation != 0:
            self.atom_image = rotate(self.atom_image, self.image_rotation)
            self.light_image = rotate(self.light_image, self.image_rotation)
            self.dark_image = rotate(self.dark_image, self.image_rotation)
        
        self.atom_image_trunc = \
        self.atom_image[self.trunc_y_lim[0]:self.trunc_y_lim[1],
                        self.trunc_x_lim[0]:self.trunc_x_lim[1]]
        self.light_image_trunc = \
        self.light_image[self.trunc_y_lim[0]:self.trunc_y_lim[1],
                        self.trunc_x_lim[0]:self.trunc_x_lim[1]]
        self.dark_image_trunc = \
        self.dark_image[self.trunc_y_lim[0]:self.trunc_y_lim[1],
                        self.trunc_x_lim[0]:self.trunc_x_lim[1]]

        self.fluc_win_x = self.hfig_main.calculation.flucWinX
        self.fluc_win_y = self.hfig_main.calculation.flucWinY
        
        self.set_fluc_corr(self.fluc_win_x[0], self.fluc_win_x[-1], self.fluc_win_y[0], self.fluc_win_y[-1])
        return

    def set_fluc_corr(self, x1, x2, y1, y2):
        '''Calculate fluctuation correction given a fluctuation window'''
        int_atom = np.mean(np.mean(self.atom_image[y1:y2,
                                              x1:x2]))
        int_light = np.mean(np.mean(self.light_image[y1:y2,
                                              x1:x2]))
        self.fluc_cor = int_atom / int_light
        self.fluc_cor_corner = (x1, y1)
        self.fluc_cor_width = x2 - x1
        self.fluc_cor_height = y2 - y1

    def truncate_image(self, x1, x2, y1, y2):
        '''Crop OD image within given coordinates'''
        self.atom_image_trunc = self.atom_image[y1:y2, x1:x2]
        self.light_image_trunc = self.light_image[y1:y2, x1:x2]
        self.dark_image_trunc = self.dark_image[y1:y2, x1:x2]

    def get_variables_file(self):
        '''returns the variables file?'''
        sub_block_data = self.run_data_files.AllFiles
        sub_blocks = {}
        for i in xrange(scipy.shape(sub_block_data)[0]):
            sub_blocks[sub_block_data[i][0]] = sub_block_data[i][1]
        return sub_blocks['Variables.m']

    def get_variables_values(self):
        '''returns a dictionary mapping variable names to values'''
        variables = self.run_data_files.vars
        variables_dict = {}
        for variable in variables:
            try:
                variables_dict[variable.name] = variable.value
            except AttributeError:
                print("Warning: vars data structure is not formatted correctly, internal variables not available")
                return
        return variables_dict

    def get_od_image(self
            , fluc_cor_switch=True
            , trunc_switch=True
            , abs_od=True
            , intensity_correction_switch=False
            ):
        '''return the optical density image'''
        if trunc_switch:
            a_img = self.atom_image_trunc
            d_img = self.dark_image_trunc
            l_img = self.light_image_trunc
        else:
            a_img = self.atom_image
            d_img = self.dark_image
            l_img = self.light_image
        if fluc_cor_switch:
            od_image = -np.log((a_img
                            - d_img).astype(float)
                            /(self.fluc_cor * l_img
                            - d_img).astype(float))
        else:
            od_image = -np.log((a_img
                            - d_img).astype(float)
                            /(l_img
                            - d_img).astype(float))
        if abs_od:
            od_image = np.abs(od_image)
        od_image[np.isnan(od_image)] = 0
        od_image[np.isinf(od_image)] = od_image[~np.isinf(od_image)].max()
        return od_image

    def get_cd_image(self, axis=1, linear_bias_switch=False, INTCORR=True, **kwargs):
        '''return the column density, with offset removed'''
        if INTCORR:
            od_image = self.optical_depth()
        else:
            od_image = self.get_od_image(abs_od=False, **kwargs)
        imgcut = np.sum(od_image, axis)
	offset = 0 #at least with PIXIS, offset causes trouble
        #try:
        #    if linear_bias_switch:
        #        coefs = fit_gaussian_1d(imgcut)
        #        offset = coefs[3] / od_image.shape[1]
        #    else:
        #        coefs = fit_gaussian_1d_noline(imgcut)
        #        offset = coefs[3] / od_image.shape[1]
        #except RuntimeError:
        #    offset = np.mean(imgcut) / od_image.shape[1]
        #    raise FitError('atom_number')

        return (od_image - offset) / self.s_lambda

    def get_gerbier_field(self, filter_on = False, **kwargs):
        '''return the magnetic field reconstructed using the gerbier equation, with mu=0'''
        try:
            column_density = self.get_cd_image(**kwargs)
        except FitError:
            print('FYI, gaussian fit failed')
        if filter_on:
            sigma=24.0/13.0 #pixels per micron
            column_density = filters.gaussian_filter(column_density,sigma)
        line_density = bp.line_density(column_density
                , pixel_size = self.pixel_size)
        gerbier_field = bp.field_array(line_density)
        return gerbier_field
        
    def get_vert_image(self):
        '''return the sum of the three images, appropriate for persistent features, especially useful in vertical imaging to see the sample'''
        vert_image = self.atom_image + self.dark_image + self.light_image
        return vert_image

    def atom_number(self, axis=1, offset_switch=True,
                                fluc_cor_switch=True,
                                debug_flag=False,
                                linear_bias_switch=True):
        '''return the atom number'''
        od_image = self.get_od_image(fluc_cor_switch)
        imgcut = np.sum(od_image, axis)
        try:
            if linear_bias_switch:
               coefs = fit_gaussian_1d(imgcut)
            else:
                coefs = fit_gaussian_1d_noline(imgcut)
        except:
            raise FitError('atom_number')

        offset = coefs[3]
        if offset_switch:
            if linear_bias_switch:
                slope = coefs[4]
                atom_number = self.A/self.s_lambda*(np.sum(od_image)
                                                - 0.5*slope*len(imgcut)**2
                                                - offset*len(imgcut))
            else:
                atom_number = self.A/self.s_lambda*(np.sum(od_image)
                                                - offset*len(imgcut))
        else:
            atom_number = self.A/self.s_lambda*(np.sum(od_image))

        if debug_flag:
            plt.plot(imgcut)
            params = [range(len(imgcut))]
            params.extend(coefs)
            plt.plot(gaussian_1d(*params))
            plt.show()
        return atom_number

    def get_density_1d(self, image):
        '''returns image scaled to OD'''
        return self.A/self.s_lambda * image

    def get_cont_param(self):
        '''get the value of the control parameter'''
        if self.cont_par_name == 'VOID':
            return 'void'
        else:
            cont_param = \
            self.get_variables_values('Variables.m')[self.cont_par_name]
            return cont_param[self.curr_cont_par]

    def get_param_definition(self, param_name):
        '''get the value of a parameter'''
        return self.get_variables_values()[param_name]

    def position(self, axis=0, fluc_cor_switch=True,
                            linear_bias_switch=True,
                            debug_flag=False):
        '''returns the position of the center of the cloud.
        axis 0 is X, axis 1 is Z'''
        image = self.get_od_image(fluc_cor_switch)
        imgcut = np.sum(image, axis)
        try:
            if linear_bias_switch:
                coefs = fit_gaussian_1d(imgcut)
            else:
                coefs = fit_gaussian_1d_noline(imgcut)
        except:
            raise FitError('position')

        if debug_flag:
            plt.plot(imgcut)
            params = [range(len(imgcut))]
            params.extend(coefs)
            plt.plot(gaussian_1d(*params))
            plt.show()

        return(self.distconv(coefs_x[1], axis))

    def width(self, axis=0):
        '''return width of integrated cloud OD. axis 0 is X, axis 1 is Z'''
        image = self.get_od_image()
        imgcut = np.sum(image, axis)
        coefs = fit_gaussian_1d(imgcut)
        return coefs[2]*self.pixel_size / self.magnification

    def light_counts(self):
        '''return total counts in light image, for intensity fluctuation'''
        return np.sum((self.light_image - self.dark_image).astype(float))

    def get_chi_squared_1d(self, axis=0):
        '''return goodness of fit for 1D gaussian'''
        img_1d = np.sum(self.get_od_image(), axis)
        coef = fit_gaussian_1d(img_1d)
        x = np.arange(img_1d.size)
        fit = gaussian_1d(x, coef[0], coef[1], coef[2], coef[3], coef[4])
        error = img_1d-fit
        background_1d = np.sum(self.dark_image_trunc, axis)
        variance = np.std(background_1d)**2
        chisquare = np.sum((error)**2)/(variance*(img_1d.size-4))
        return chisquare

    def get_gaussian_fit_params(self,
                                fluc_cor_switch=False,
                                linear_bias_switch=True,
                                debug_flag=False,
                                offset_switch=True,
                                custom_fit_switch = False,
                                use_first_window = False,
                                pixel_units = False,
                                fit_axis=1):
        '''This calculates the common parameters extracted
        from a gaussian fit all at once, returning them in a dictionary.
        The parameters are: Atom Number, X position, Z position,
                            X Width, Z Width, light_counts

        This is a separate method so that the fit only needs to be done once.
        This is probably suboptimal.'''
        od_image = self.get_od_image(fluc_cor_switch)
        imgcut_x = np.sum(od_image, 0)
        imgcut_z = np.sum(od_image, 1)

        # Get fits in both axes
        try:
            if linear_bias_switch:
                coefs_x = fit_gaussian_1d(imgcut_x)
                slope_x = coefs_x[4]
            else:
                coefs_x = fit_gaussian_1d_noline(imgcut_x)
                slope_x = 0
        except:
            coefs_x = [0, 0, 0] # KLUDGE!!!
            print 'Fit Error in X'

        try:
            if linear_bias_switch:
                coefs_z = fit_gaussian_1d(imgcut_z)
                slope_z = coefs_z[4]
            else:
                coefs_z = fit_gaussian_1d_noline(imgcut_z)
                slope_z = 0
        except:
            coefs_z = [0,0,0]
            print 'Fit Error in Z'
        
        # Using a switch to choose which axis gives offset
        if fit_axis==1:
            try:
                offset = coefs_z[3]
                slope = slope_z
            except IndexError, UnboundLocalError:
                print 'there was a fit error'
                offset = 0
                slope = 0
            axis_len = len(imgcut_z)
        elif fit_axis==0:
            offset = coefs_x[3]
            slope = slope_x
            axis_len = len(imgcut_x)
            
        # Calculate atom number
        if offset_switch:
            atom_number = self.A/self.s_lambda*(np.sum(od_image) 
                                - 0.5*slope*axis_len**2
                                - offset*axis_len)
        else:
            atom_number = self.A/self.s_lambda*(np.sum(od_image))

        # Display debug window
        if debug_flag:
            print self.filename
            print 'M: %2.2f'%self.magnification
            print 'Number: %2.2e'%atom_number
            full_od_img = self.get_od_image(fluc_cor_switch, trunc_switch=False)
            fig = plt.figure()
            ax1 = fig.add_subplot(131)
            ax1.plot(imgcut_z)
            params = [range(len(imgcut_z))]
            params.extend(coefs_z)
            if linear_bias_switch:
                ax1.plot(gaussian_1d(*params))
            else:
                try:
                    ax1.plot(gaussian_1d_noline(*params))
                except TypeError:
                    print 'Fit error, you get no plot'
            ax2 = fig.add_subplot(132)
            ax2.imshow(full_od_img)
            roi_width = self.trunc_win_x[-1] - self.trunc_win_x[0]
            roi_height = self.trunc_win_y[-1] - self.trunc_win_y[0]
            ROI_box = mpatches.Rectangle((self.trunc_win_x[0],self.trunc_win_y[0]), roi_width, roi_height, fill=False, color='g', linewidth=2.5)
            fluc_box = mpatches.Rectangle(self.fluc_cor_corner, self.fluc_cor_width, self.fluc_cor_height, fill=False, color='m', linewidth=2.5)
            ax2.add_patch(ROI_box)
            ax2.add_patch(fluc_box)
            ax3 = fig.add_subplot(133)
            ax3.imshow(od_image)
            plt.show()
            print "Fitting window: (%d, %d) to (%d, %d)"%(self.trunc_win_x[0], self.trunc_win_y[0], self.trunc_win_x[-1], self.trunc_win_y[-1])
            print "Fluctuation window: (%d, %d) to (%d, %d)"%(self.fluc_win_x[0], self.fluc_win_y[0], self.fluc_win_x[-1], self.fluc_win_y[-1])
        # Calculate and return cloud properties in desired units
        if not pixel_units:
            return {'atom_number': atom_number,
                    'position_x':(self.distconv(coefs_x[1], axis=0)
                                    if coefs_x[1] is not None else None),
                    'position_z': (self.distconv(coefs_z[1], axis=1)
                                    if coefs_z[1] is not None else None),
                    'width_x':(coefs_x[2]*self.pixel_size*self.image_angle_corr
                                            / self.magnification
                                    if coefs_x[2] is not None else None),
                    'width_z': (coefs_z[2]*self.pixel_size / self.magnification
                                    if coefs_z[2] is not None else None),
                    'light_counts': np.sum((self.light_image - self.dark_image)
                                                    .astype(float)),
                    'timestamp': self.timestamp}
        else:
            return {'atom_number': atom_number,
                'position_x':(coefs_x[1]+self.trunc_win_x[0]
                                if coefs_x[1] is not None else None),
                'position_z': (coefs_z[1]
                                if coefs_z[1] is not None else None),
                'width_x':(coefs_x[2] if coefs_x[2] is not None else None),
                'width_z': (coefs_z[2] if coefs_z[2] is not None else None),
                'light_counts': np.sum((self.light_image - self.dark_image)
                                                .astype(float)),
                'timestamp': self.timestamp}

    def timestamp(self):
        '''return timestamp, extracted from filename'''
        thisfilename = os.path.basename(self.filename)
        return FILE_RE.search(thisfilename).group(1) #so crude!

    def distconv(self, pixnum, axis=0):
        '''Convert pixel number to physical distance from frame corner'''
        if axis == 0:
            return (((pixnum + self.trunc_win_x[0]) * self.pixel_size
                * self.image_angle_corr) / self.magnification)
        elif axis == 1:
            return ((pixnum + self.trunc_win_y[0])
                        * self.pixel_size) / self.magnification

    def lengthconv(self, length, axis):
        '''Convert length in pixels to physical length'''
        if axis == 0:
            return ((length * self.pixel_size
                * self.image_angle_corr) / self.magnification)
        elif axis == 1:
            return (length * self.pixel_size) / self.magnification


    def counts2intensity(self, rawimage):
        result = (rawimage / self.quantum_efficiency)*(H*C/LAMBDA_RB) / ((self.pixel_size / self.magnification)**2) / self.get_image_time()
        if self.cameratype == 'dragonfly':
            result /= 16
        return result
    
    def counts2saturation(self
		    , rawimage
                    , saturation_intensity=DEFAULT_I_SAT
                    ):
        return self.counts2intensity(rawimage)/saturation_intensity

    def get_image_time(self):
        if self.cont_par_name == 'ExposeTime':
            return self.curr_cont_par
        else:
            try:
                this_image_time = self.get_variables_values()['ExposeTime']
            except:
                this_image_time = DEFAULT_IMAGE_TIME
            return this_image_time

    def optical_depth(self
		    , linear_bias_switch=False
        , saturation_intensity=DEFAULT_I_SAT):
        optical_density = self.get_od_image(abs_od=False)
	imgcut = np.sum(optical_density, axis=0)
        try:
            if linear_bias_switch:
                coefs = fit_gaussian_1d(imgcut)
                offset = coefs[3] / optical_density.shape[1]
            else:
                coefs = fit_gaussian_1d_noline(imgcut)
                offset = coefs[3] / optical_density.shape[1]
        except RuntimeError:
            offset = np.mean(imgcut) / optical_density.shape[1]
            #raise FitError('atom_number')

        intensity_term = self.intensity_change() / saturation_intensity
        return optical_density - offset + intensity_term

    def intensity_change(self):
        return self.counts2intensity(self.light_image_trunc) - self.counts2intensity(self.atom_image_trunc)
    
    def saturation(self):
        return np.mean(self.counts2saturation(image_subtract(self.light_image_trunc, self.dark_image_trunc)))
    
    def int_corr_atom_number(self):
        return np.sum(self.optical_depth()) / self.s_lambda * (self.pixel_size / self.magnification)**2
    
    def optdens_number(self, axis):
        return self.atom_number(axis=axis)
    
    def int_term_number(self
            , saturation_intensity=DEFAULT_I_SAT):
        int_term = self.intensity_change() / saturation_intensity
        return np.sum(int_term) / self.s_lambda * (self.pixel_size / self.magnification)**2
