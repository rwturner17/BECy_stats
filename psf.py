'''psf.py - Calculate resolution from distribution of cloud images'''

import matplotlib.pyplot as plt
import numpy as np
import cloud_distribution as cd
from cloud_image import CloudImage as ci
import BECphysics as bp
import bfieldsensitivity as bf
import image_align as ia
import scipy.signal
import math

# Long term we should implement this as a subclass of CloudDistribution
#class AlignedCloudDistribution(cd.CD):
#	'''Container for aligned cloud distribution'''

DEFAULT_MAX_SHIFT = 30 # unit is pixel
DEFAULT_PIXSIZE = 13.0 / 24 #PIXIS

def next_power_two(n):
    this_exp = int(math.log(n, 2))
    return 2**(this_exp + 1)
    
def get_line_densities(dist,pixsize=DEFAULT_PIXSIZE):
    '''returns the integrated line densities (lds) and the normalized lds
    dist - a cloud distribution object
    '''
    imgs = [ci(ff) for ff in dist.filelist]
    cdimgs = [im.get_od_image() / im.s_lambda for im in imgs]
    ldimgs = [bp.line_density(cdim, pixsize) for cdim in cdimgs]
    ldsnorm = [ld/np.sum(ld) for ld in ldimgs]
    
    return ldsnorm,ldimgs
    
def plt_line_densities(dist,pixsize=DEFAULT_PIXSIZE):
    '''plots normalized lds
    dist - a cloud distribution object
    '''
    ldsnorm, _ = get_line_densities(dist,pixsize)
    for ld in ldsnorm:
        plt.plot(ld)
    #plt.show()


def get_aligned_line_densities(dist, max_shift=DEFAULT_MAX_SHIFT, pixsize=DEFAULT_PIXSIZE):
    '''Produce aligned line densities from a distribution.
        Args:
            dist: a CloudDistribution
            max_shift: maximum allowed shift, in pixels.
                        Images that need to be shifted more than this will be discarded
    '''
    ldsnorm,ldimgs = get_line_densities(dist)

    aligned = []
    shifts = []
    for nn, ld in enumerate(ldimgs):
        shift = ia.optimal_shift(ldsnorm[0], ldsnorm[nn])
        if abs(shift) > max_shift:
            pass
        else:
            aligned.append(np.roll(ld, -shift))
            shifts.append(shift)
    return aligned, shifts

def get_shift_stats(dist, max_shift=DEFAULT_MAX_SHIFT, pixsize=DEFAULT_PIXSIZE):
    '''computes the mean and the standard deviation of the shifts needed for aligning
    runs in a data set. prints them. and then plots a histogram of the shifts in um
    dist - a cloud distribution object
    '''
    _, shifts = get_aligned_line_densities(dist, max_shift)
    shift_mean = np.mean(shifts)
    shift_mean_um = shift_mean * pixsize
    print 'Average shift needed: %2.1f um'%shift_mean_um
    shift_std = np.std(shifts)

    shift_um = shift_std * pixsize
    print 'Noise in lateral position: %2.1f um'%shift_um

    plt.figure()
    plt.hist(np.array(shifts)*pixsize, 10)
    plt.xlim(-20,20)
    plt.xlabel('Shifts (um)')
    plt.ylabel('Counts')
    plt.title('Histogram of shifts over %d runs'%len(shifts))
    #plt.show()

def get_ave_norm(dist, pixsize=DEFAULT_PIXSIZE, **kwargs):
    '''returns the average of image in a distribution, normalized
    dist - cloud_distribution object containing all the images
    '''
    aligned_lds, _ = np.array(align_lds(dist, **kwargs))
    avg_ld = np.mean(aligned_lds, axis=0)
    avg_norm = avg_ld / np.sum(avg_ld)
    
    return avg_norm

def get_power_spectral_density(dist, pixsize=DEFAULT_PIXSIZE, **kwargs):
    '''plots the power spectral density of the average ld of a set of runs
    dist - a cloud distribution object
    '''
    avg_norm=get_ave_norm(dist)
    window_size = next_power_two(len(avg_norm))
    avg_fft = np.fft.fftshift(np.fft.fft(avg_norm, window_size))

    psd_avg = np.abs(avg_fft)**2
    psd_norm = psd_avg / sum(psd_avg)
    faxis = np.fft.fftshift(np.fft.fftfreq(window_size, pixsize))
    
    plt.plot(0.5/faxis[window_size/2:], psd_norm[window_size/2:])
    plt.xlabel('Spatial resolution  (um)')
    plt.title('Power Spectrum of Averaged Atom Profiles')
    plt.xlim(0.2,2)
    plt.ylim(0,0.15e-4)
    plt.show()
    
    
def plt_ave_shifted_imag(dist,pixsize=DEFAULT_PIXSIZE, **kwargs):
    '''plots the average of lds in a data set, after aligning them
    dist - a cloud distribution object
    '''
    ave_norm=get_ave_norm(dist,pixsize)
    xrange=np.array(range(len(ave_norm)))*pixsize
    
    plt.plot(xrange,ave_norm)
    
    plt.xlabel('Spatial distance (um)')
    plt.ylabel('Normalized OD')
    plt.show()

def get_shifts(dist, ref_dist, max_shift=DEFAULT_MAX_SHIFT, pixsize=DEFAULT_PIXSIZE):
    '''try to return shifts between two distributions, not really working for now
    '''
    imgs = [ci(ff) for ff in dist.filelist]
    cdimgs = [im.get_od_image() / im.s_lambda for im in imgs]
    ldimgs = [bp.line_density(cdim, pixsize) for cdim in cdimgs]
    ldsnorm = [ld/np.sum(ld) for ld in ldimgs]
    ref_img = ci(ref_dist.filelist[-1])
    
    ref_cdimg = ref_img.get_od_image() / ref_img.s_lambda
    ref_ldimg = bp.line_density(ref_cdimg, pixsize)
    ref_ldnorm = ref_ldimg/np.sum(ref_ldimg)
    
    shifts = []
    for nn, ld in enumerate(ldimgs):
        shift = ia.optimal_shift(ref_ldnorm, ldsnorm[nn])
        if abs(shift) > max_shift:
            pass
        else:
            #aligned.append(np.roll(ld, -shift))
            shifts.append(shift)
    return shifts
    
    
    
#aliases
align_lds = get_aligned_line_densities
sh_stats = get_shift_stats
psd = get_power_spectral_density
plt_ave_img=plt_ave_shifted_imag
plt_lds=plt_line_densities
