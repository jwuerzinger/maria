import os

from maria.array import Array
from maria.pointing import Pointing
from maria.site import Site

from . import utils
from .atmosphere import AtmosphereMixin
from .base import BaseSimulation, parse_sim_kwargs
from .cmb import CMBMixin
from .noise import NoiseMixin
from .sky import MapMixin

here, this_filename = os.path.split(__file__)

master_params = utils.io.read_yaml(f"{here}/configs/params.yml")


class Simulation(BaseSimulation, AtmosphereMixin, CMBMixin, MapMixin, NoiseMixin):
    """A simulation! This is what users should touch, primarily."""

    def __init__(
        self,
        array: str or Array = "default",
        pointing: str or Pointing = "default",
        site: str or Site = "default",
        verbose: bool = True,
        **kwargs,
    ):
        self.parsed_sim_kwargs = parse_sim_kwargs(kwargs, master_params, strict=True)

        super().__init__(
            array,
            pointing,
            site,
            verbose=verbose,
            **self.parsed_sim_kwargs["array"],
            **self.parsed_sim_kwargs["pointing"],
            **self.parsed_sim_kwargs["site"],
        )

        self.params = {}
        for sub_type, sub_master_params in master_params.items():
            self.params[sub_type] = {}
            for k, v in sub_master_params.items():
                self.params[sub_type][k] = kwargs.get(k, v)
                setattr(self, k, kwargs.get(k, v))

        self._initialize_atmosphere()
        self._initialize_map()

    def _run(self, units="K_RJ"):
        # number of bands are lost here
        self._simulate_noise()

        if self.atmosphere_model:
            self._simulate_atmospheric_emission()

        if self.map_file:
            self._sample_maps()

        if hasattr(self, "cmb_sim"):
            self.cmb_sim._run()
            self.data += self.cmb_sim.data
