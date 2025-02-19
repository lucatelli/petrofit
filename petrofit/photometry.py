import warnings

import numpy as np

from astropy.nddata import Cutout2D
from astropy.stats import sigma_clipped_stats, sigma_clip
from astropy.utils.exceptions import AstropyWarning

from matplotlib import pyplot as plt

from photutils import  EllipticalAnnulus, EllipticalAperture

from .segmentation import masked_segm_image
from .modeling.fitting import fit_background, model_to_image
from .segmentation import get_source_elong,  get_source_theta, get_source_position

__all__ = [
    'plot_apertures', 'flux_to_abmag', 'order_cat', 'radial_elliptical_aperture',
    'radial_elliptical_annulus', 'calculate_photometic_density', 'make_radius_list',
    'photometry_step', 'source_photometry'
]


def plot_apertures(image=None, apertures=[], vmin=None, vmax=None, color='white', lw=1.5):
    """
    Plot apertures on image

    Parameters
    ----------
    image : numpy.ndarray
        2D image array.

    apertures : list
        List of photutils Apertures.

    vmin, vmax : float
        vmax and vmin values for plot.

    color : string
        Matplotlib color for the apertures, default=White.

    lw : float
        Line width of aperture outline.
    """
    if image is not None:
        plt.imshow(image, cmap='Greys_r', vmin=vmin, vmax=vmax)

    for aperture in apertures:
        aperture.plot(axes=plt.gca(), color=color, lw=lw)

    if image or apertures:
        plt.title('Apertures')


def flux_to_abmag(flux, header):
    """Convert HST flux to AB Mag"""
    if not type(flux) in [int, float]:
        flux = np.array(flux)
        flux[np.where(flux <= 0)] = np.nan
    elif flux <= 0:
        return np.nan

    PHOTFLAM = header['PHOTFLAM']
    PHOTZPT = header['PHOTZPT']
    PHOTPLAM = header['PHOTPLAM']

    STMAG_ZPT = (-2.5 * np.log10(PHOTFLAM)) + PHOTZPT
    ABMAG_ZPT = STMAG_ZPT - (5. * np.log10(PHOTPLAM)) + 18.692

    return -2.5 * np.log10(flux) + ABMAG_ZPT


def order_cat(cat, key='area', reverse=True):
    """
    Sort a catalog by largest area and return the argsort

    Parameters
    ----------
    cat : `SourceCatalog` instance
        A `SourceCatalog` instance containing the properties of each source.

    key : string
        Key to sort.

    reverse : bool
        Reverse sorting order. Default is `True` to place largest values on top.

    Returns
    -------
    output : list
        A list of catalog indices ordered by largest area.
    """
    table = cat.to_table()[key]
    order_all = table.argsort()
    if reverse:
        return list(reversed(order_all))
    return order_all


def radial_elliptical_aperture(position, r, elong=1., theta=0.):
    """
    Helper function given a radius, elongation and theta,
    will make an elliptical aperture.

    Parameters
    ----------
    position : tuple
        (x, y) coords for center of aperture.

    r : int or float
        Semi-major radius of the aperture.

    elong : float
        Elongation.

    theta : float
        Orientation in rad.

    Returns
    -------
    EllipticalAperture
    """
    a, b = r, r / elong
    return EllipticalAperture(position, a, b, theta=theta)


def radial_elliptical_annulus(position, r, dr, elong=1., theta=0.):
    """
    Helper function given a radius, elongation and theta,
    will make an elliptical aperture.

    Parameters
    ----------
    position : tuple
        (x, y) coords for center of aperture

    r : int or float
        Semi-major radius of the inner ring

    dr : int or float
        Thickness of annulus (outer ring = r + dr).

    elong : float
        Elongation.

    theta : float
        Orientation in rad.

    Returns
    -------
    EllipticalAnnulus
    """

    a_in, b_in = r, r / elong
    a_out, b_out = r + dr, (r + dr) / elong

    return EllipticalAnnulus(position, a_in, a_out, b_out, theta=theta)


def calculate_photometic_density(r_list, flux_list, elong=1., theta=0.):
    """Compute value between radii"""
    density = []

    last_flux = 0
    last_area = 0
    for r, flux in zip(r_list, flux_list):
        aperture = radial_elliptical_aperture((0, 0), r, elong=elong, theta=theta)
        area = aperture.area
        density.append((flux - last_flux) / (area - last_area))
        last_area, last_flux = area, flux

    return np.array(density)


def make_radius_list(max_pix, n, log=False):
    """Make an array of radii of size n up to max_pix"""
    if log:
        return  np.logspace(0, np.log10(max_pix), num=n, endpoint=True, base=10.0, dtype=float, axis=0)
    else:
        return np.array([x * max_pix / n for x in range(1, n + 1)])


def photometry_step(position, r_list, image, error=None, mask=None, elong=1., theta=0.,
                    plot=False, vmin=0, vmax=None, method='exact'):
    """
    Core photometry function.  Given a position, a list of radii and the shape
    of apertures, calculate the photometry of the target in the image.

    Parameters
    ----------
    position : tuple
        (x, y) position in pixels.

    r_list : list
        A list of radii for apertures.

    image : 2D array
        Image to preform photometry on.

    error : 2D array
        Error map of the image.

    mask : 2D array
        Boolean array with True meaning that pixel is unmasked.

    elong : float
        Elongation.

    theta : float
        Orientation in rad.

    plot : bool
        Plot the target and apertures.

    vmin : int
        Min value for plot.

    vmax : int
        Max value for plot.

    method : {'exact', 'center', 'subpixel'}, optional
            The method used to determine the overlap of the aperture on
            the pixel grid.  Not all options are available for all
            aperture types.  Note that the more precise methods are
            generally slower.  The following methods are available:

                * ``'exact'`` (default):
                  The the exact fractional overlap of the aperture and
                  each pixel is calculated.  The returned mask will
                  contain values between 0 and 1.

                * ``'center'``:
                  A pixel is considered to be entirely in or out of the
                  aperture depending on whether its center is in or out
                  of the aperture.  The returned mask will contain
                  values only of 0 (out) and 1 (in).

                * ``'subpixel'``
                  A pixel is divided into subpixels (see the
                  ``subpixels`` keyword), each of which are considered
                  to be entirely in or out of the aperture depending on
                  whether its center is in or out of the aperture.  If
                  ``subpixels=1``, this method is equivalent to
                  ``'center'``.  The returned mask will contain values
                  between 0 and 1.

    Returns
    -------
    photometry, aperture_area, error
        Returns photometry, aperture area (unmasked pixels) and error at each radius.
    """

    flux_arr = []
    error_arr = []
    area_arr = []

    if plot:
        ax = plt.gca()
        plt.imshow(image, vmin=vmin, vmax=image.max() * 0.3 if vmax is None else vmax)
        ax.set_title("Image and Aperture Radii")
        ax.set_xlabel("Pixels")
        ax.set_ylabel("Pixels")

    mask = ~mask if mask is not None else None
    for i, r in enumerate(r_list):
        aperture = radial_elliptical_aperture(position, r, elong=elong, theta=theta)

        photometric_value, photometric_err = aperture.do_photometry(data=image, error=error, mask=mask, method=method)
        aperture_area, aperture_area_err = aperture.do_photometry(data=np.ones_like(image), error=None,
                                                                  mask=mask, method=method)

        aperture_area = float(np.round(aperture_area, 6))
        photometric_value = float(np.round(photometric_value, 6))
        photometric_err = float(np.round(photometric_err, 6)) if photometric_err.size > 0 else np.nan

        if np.isnan(photometric_value):
            raise Exception("Nan photometric_value")

        if plot:
            aperture.plot(plt.gca(), color='w', alpha=0.2)


        flux_arr.append(photometric_value)
        area_arr.append(aperture_area)
        error_arr.append(photometric_err)

    return np.array(flux_arr), np.array(area_arr), np.array(error_arr)


def source_photometry(source, image, segm_deblend, r_list, error=None,
                      cutout_size=None,position2=None,
                      bkg_sub=False, sigma=3.0, sigma_type='clip',
                      method='exact', mask_background=False,
                      plot=False, vmin=0, vmax=None, ):
    """
    Aperture photometry on a PhotUtils `SourceProperties`.

    Parameters
    ----------
    source : `photutils.segmentation.SourceProperties`
        `SourceProperties` (an entry in a `SourceCatalog`)

    image : 2D array
        Image to preform photometry on.

    segm_deblend : `SegmentationImage`
        Segmentation map of the image.

    r_list : list
        List of aperture radii.

    error : 2D array
        Error image (optional).

    cutout_size : int
        Size of cutout.

    bkg_sub : bool
        If the code should subtract the background using the `sigma` provided.

    sigma : float
        The sigma value used to determine noise pixels. Once the pixels above this value are masked,
        a 2D plane is fit to determine the background. The 2D plane model is then converted into an image and
        subtracted from the cutout of the target source. see the `sigma_type` on how this value will be used.

    sigma_type : {'clip', 'bound'}, optional
        The meaning of the provided sigma.
            * ``'clip'`` (default):
                Uses `astropy.stats.sigma_clipping.sigma_clip` to clip at the provided `sigma` std value.
                Note that `sigma` in this case is the number of stds above the mean.

            * ``'bound'``:
                After computing the mean of the image, clip at `mean - sigma` and `mean + sigma`.
                Note that `sigma` in this case is a value and not the number of stds above the mean.


    method : {'exact', 'center', 'subpixel'}, optional
        The method used to determine the overlap of the aperture on
        the pixel grid.  Not all options are available for all
        aperture types.  Note that the more precise methods are
        generally slower.  The following methods are available:

            * ``'exact'`` (default):
              The the exact fractional overlap of the aperture and
              each pixel is calculated.  The returned mask will
              contain values between 0 and 1.

            * ``'center'``:
              A pixel is considered to be entirely in or out of the
              aperture depending on whether its center is in or out
              of the aperture.  The returned mask will contain
              values only of 0 (out) and 1 (in).

            * ``'subpixel'``
              A pixel is divided into subpixels (see the
              ``subpixels`` keyword), each of which are considered
              to be entirely in or out of the aperture depending on
              whether its center is in or out of the aperture.  If
              ``subpixels=1``, this method is equivalent to
              ``'center'``.  The returned mask will contain values
              between 0 and 1.

    mask_background : bool
        Should background pixels, that are not part of any source in the segmentation map, be included?
        If False, only pixels inside the source's segmentation are unmasked.

    plot : bool
        Show plot of cutout and apertures.

    vmin : int
        Min value for plot.

    vmax : int
        Max value for plot.


    Returns
    -------

    flux_arr, area_arr, error_arr : (numpy.array, numpy.array, numpy.array)
        Tuple of arrays:

            * `flux_arr`: Photometric sum in aperture.

            * `area_arr`: Exact area of aperture.

            * `error_arr`: if error map is provided, error of measurements.
    """

    # Get source geometry
    # -------------------
    position = get_source_position(source)
    elong = get_source_elong(source)
    theta = get_source_theta(source)

    if cutout_size is None:
        cutout_size = np.ceil(max(r_list) * 3)

    cutout_size = int(cutout_size)
    if cutout_size % 2 == 1:
        cutout_size += 1

    # Error cutout
    # ------------
    masked_err = None
    if error is not None:
        masked_err = Cutout2D(error, position, cutout_size, mode='partial', fill_value=np.nan).data

    # Image Cutout
    # ------------
    full_masked_image = masked_segm_image(source, image, segm_deblend, fill=np.nan, mask_background=mask_background).data
    masked_nan_image = Cutout2D(full_masked_image, position, cutout_size, mode='partial', fill_value=np.nan)
    masked_image = masked_nan_image.data

    # Cutout for Stats
    # ----------------
    # This cutout has all sources masked
    stats_cutout_size = cutout_size  # max(source.bbox.ixmax - source.bbox.ixmin, source.bbox.iymax - source.bbox.iymin) * 2
    full_bg_image = masked_segm_image(0, image, segm_deblend, fill=np.nan, mask_background=False).data
    masked_stats_image = Cutout2D(full_bg_image, position, stats_cutout_size, mode='partial', fill_value=np.nan).data

    # Subtract Mean Plane
    # -------------------
    if bkg_sub:
        if len(np.where(~np.isnan(masked_stats_image))[0]) > 10:
            with warnings.catch_warnings():

                warnings.simplefilter('ignore', AstropyWarning)
                if sigma_type.lower() == 'clip':
                    fit_bg_image = masked_stats_image
                    fit_bg_image = sigma_clip(fit_bg_image, sigma)

                elif sigma_type.lower() == 'bound':
                    mean, median, std = sigma_clipped_stats(masked_stats_image, sigma=3,
                                                            mask=np.isnan(masked_stats_image.data))

                    fit_bg_image = masked_stats_image
                    fit_bg_image[np.where(fit_bg_image > mean + sigma)] = np.nan
                    fit_bg_image[np.where(fit_bg_image < mean - sigma)] = np.nan
                else:
                    raise ("background image masking sigma type not understood, try 'clip' or 'bound'")

                fitted_model, _ = fit_background(fit_bg_image, sigma=None)

                masked_image -= model_to_image(fitted_model, cutout_size)
                if sigma_type.lower() == 'bound':
                    masked_image = np.clip(masked_image, - sigma, np.inf)

        elif plot:
            print("bkg_sub: Not enough datapoints, did not subtract.")

    # Make mask
    # ---------
    mask = np.ones_like(masked_image)
    mask[np.where(np.isnan(masked_image))] = 0
    mask = mask.astype(bool)

    if position2 is None:
        position2 = np.array(masked_image.data.shape) / 2.
    else:
        position2 = position2

    if plot:
        print(source.label)
        fig, ax = plt.subplots(1, 2, figsize=[12, 4])

    if plot:
        plt.sca(ax[0])

    flux_arr, area_arr, error_arr = photometry_step(position=position2,
                                                    r_list=r_list,
                                                    image=masked_image,
                                                    error=masked_err,
                                                    mask=mask,
                                                    elong=elong, theta=theta,
                                                    plot=plot,
                                                    vmin=vmin, vmax=vmax,
                                                    method=method)

    if plot:
        plt.sca(ax[1])
        plt.plot(r_list, flux_arr/np.max(flux_arr), c='black', linewidth=3)
        # for r in r_list:
        #     plt.axvline(r, alpha=0.5, c='r')
        plt.title("Curve of Growth")
        plt.xlabel("Radius in Pixels")
        plt.ylabel("Fractional Flux Enclosed")
        plt.show()

        r = max(r_list)
        fig, ax = plt.subplots(1, 1, figsize=[10, 3])
        plt.plot(masked_image[:, int(position2[0])], c='black', linewidth=3)
        plt.axhline(0, c='black')
        # plt.axhline(noise_sigma, c='b')
        plt.axvline(position2[0], linestyle='--')
        plt.axvline(position2[0] + r, alpha=0.5, c='r')
        plt.axvline(position2[0] - r, alpha=0.5, c='r')
        plt.xlabel("Slice Along Y [pix]")
        plt.ylabel("Flux")

        fig, ax = plt.subplots(1, 1, figsize=[10, 3])

        plt.plot(masked_image[int(position2[1]), :], c='black', linewidth=3)
        plt.axhline(0, c='black')
        # plt.axhline(noise_sigma, c='b')
        plt.axvline(position2[0], linestyle='--')
        plt.axvline(position2[0] + r, alpha=0.5, c='r')
        plt.axvline(position2[0] - r, alpha=0.5, c='r')
        plt.xlabel("Slice Along X [pix]")
        plt.ylabel("Flux")

    return flux_arr, area_arr, error_arr


object_photometry = source_photometry  # Legacy
