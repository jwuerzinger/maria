import healpy as hp
import numpy as np
import pandas as pd

from maria.constants import T_CMB
from maria.utils.functions import planck_spectrum

from ..utils.io import fetch_cache

CMB_SPECTRUM_SOURCE_URL = (
    "https://github.com/thomaswmorris/maria-data/raw/master/cmb/spectra/"
    "COM_PowerSpect_CMB-base-plikHM-TTTEEE-lowl-lowE-lensing-minimum-theory_R3.01.txt"
)
CMB_SPECTRUM_CACHE_PATH = "/tmp/maria/cmb/spectrum.txt"
CMB_SPECTRUM_CACHE_MAX_AGE = 30 * 86400  # one month

CMB_MAP_SOURCE_URL = (
    "https://irsa.ipac.caltech.edu/data/Planck/release_3/all-sky-maps/maps/component-maps/cmb/"
    "COM_CMB_IQU-143-fgsub-sevem_2048_R3.00_full.fits"
)
CMB_MAP_CACHE_PATH = "/tmp/maria/cmb/planck/map.fits"
CMB_MAP_CACHE_MAX_AGE = 30 * 86400  # one month


class CMB:
    def __init__(self, data, fields):
        if len(data) != len(fields):
            raise ValueError("Data and labels must have the same shape!")

        self.maps = {}
        for i, (field, M) in enumerate(zip(fields, data)):
            self.maps[field] = M

        self.nside = int(np.sqrt(len(M) / 12))

    def __getattr__(self, attr):
        if attr in self.maps:
            return self.maps[attr]
        raise AttributeError(f"No attribute named '{attr}'.")

    @property
    def fields(self):
        return list(self.maps.keys())

    def plot(self, field=None, units="uK"):
        field = field or self.fields[0]
        m = self.maps[field]
        vmin, vmax = 1e6 * np.quantile(m[~np.isnan(m)], q=[0.001, 0.999])
        hp.visufunc.mollview(
            1e6 * m, min=vmin, max=vmax, cmap="cmb", unit=r"uK$_{CMB}$"
        )


def generate_cmb(nside=2048, seed=123):
    """
    Taken from https://www.zonca.dev/posts/2020-09-30-planck-spectra-healpy.html
    """

    np.random.seed(seed)

    fetch_cache(
        source_url=CMB_SPECTRUM_SOURCE_URL,
        cache_path=CMB_SPECTRUM_CACHE_PATH,
        CACHE_MAX_AGE=CMB_SPECTRUM_CACHE_MAX_AGE,
    )

    cl = pd.read_csv(CMB_SPECTRUM_CACHE_PATH, delim_whitespace=True, index_col=0)
    lmax = cl.index[-1]

    # convert to uK and convert spectrum
    cl = 1e-12 * cl.divide(cl.index * (cl.index + 1) / (2 * np.pi), axis="index")
    cl = cl.reindex(np.arange(0, lmax + 1))
    cl = cl.fillna(0)

    alm = hp.synalm((cl.TT, cl.EE, cl.BB, cl.TE), lmax=lmax, new=True)

    data = hp.alm2map(alm, nside=nside, lmax=lmax)

    cmb = CMB(data=data, fields=["T", "Q", "U"])

    return cmb


def get_cmb():
    fetch_cache(
        source_url=CMB_MAP_SOURCE_URL,
        cache_path=CMB_MAP_CACHE_PATH,
        CACHE_MAX_AGE=CMB_MAP_CACHE_MAX_AGE,
    )

    field_dtypes = {
        "T": np.float32,
        "Q": np.float32,
        "U": np.float32,
        "T_mask": bool,
        "P_mask": bool,
    }

    maps = {
        field: hp.fitsfunc.read_map(CMB_MAP_CACHE_PATH, field=i).astype(dtype)
        for i, (field, dtype) in enumerate(field_dtypes.items())
    }

    maps["T"] = np.where(maps["T_MASK"], maps["T"], np.nan)
    maps["Q"] = np.where(maps["P_MASK"], maps["Q"], np.nan)
    maps["U"] = np.where(maps["P_MASK"], maps["U"], np.nan)

    return CMB(data=[maps["T"], maps["Q"], maps["U"]], fields=["T", "Q", "U"])


class CMBMixin:
    def _initialize_cmb(self, source):
        if source == "generate":
            if self.verbose:
                print("Generating CMB realization...")
            self.cmb = generate_cmb()

        elif source == "map":
            if self.verbose:
                print("Loading CMB...")
            self.cmb = get_cmb()

    def _simulate_cmb_emission(self):
        pixel_index = hp.ang2pix(
            nside=self.cmb.nside, phi=self.coords.l, theta=np.pi / 2 - self.coords.b
        ).compute()
        cmb_temperatures = self.cmb.T[pixel_index]

        test_nu = np.linspace(1e9, 1e12, 1024)

        cmb_temperature_samples_K = T_CMB + np.linspace(
            self.cmb.T.min(), self.cmb.T.max(), 64
        )
        cmb_brightness = planck_spectrum(test_nu, cmb_temperature_samples_K[:, None])

        self.data["cmb"] = np.zeros((self.instrument.dets.n, self.plan.n_time))

        for band in self.instrument.bands:
            band_mask = self.instrument.dets.band_name == band.name

            band_cmb_power_samples_W = np.trapz(
                y=cmb_brightness * band.passband(1e-9 * test_nu), x=test_nu
            )

            self.data["cmb"][band_mask] = np.interp(
                T_CMB + cmb_temperatures[band_mask],
                cmb_temperature_samples_K,
                band_cmb_power_samples_W,
            )