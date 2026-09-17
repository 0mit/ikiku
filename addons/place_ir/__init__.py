# Part of place_ir. Licensed under AGPL-3.0.
from . import models

from .models.place_data import load_country_data


def post_init_hook(env):
    """Load Iran's places once, on install. Not as manifest data: Odoo re-reads a data file
    on every update, and re-reading a hundred thousand rows to change one line of code is a
    quarter of an hour nobody asked for. `place.node.load_country_data()` does it again when
    the files change."""
    load_country_data(env)
