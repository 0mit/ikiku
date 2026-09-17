# Part of place_ir. Licensed under AGPL-3.0.
"""Loading Iran's places, and the order that has to be respected while loading them.

The three files are a derived OpenStreetMap database (ODbL 1.0, © OpenStreetMap
contributors), written by place_graph/tools/osm_import.py. Nothing here reads a map: it
reads three CSV files and hands them to Odoo's own importer, which creates the xmlids in
the `id` column so a second run updates rows instead of doubling them.

Two things the order has to get right:
  - a place is loaded after the place it is inside, or its parent xmlid is not there yet.
    The file is written parents-first, and this loads it in one go so Odoo resolves the
    references within the batch;
  - aliases and neighbour links are loaded after the places they point at.
"""
import csv
import logging
import os

from odoo import api, models

_logger = logging.getLogger(__name__)

# Which file feeds which model, in the order they must be read.
FILES = (
    ('place.node', 'place.node.csv'),
    ('place.alias', 'place.alias.csv'),
    ('place.link', 'place.link.csv'),
)
BATCH = 5000    # rows per load() call: enough to be quick, small enough to stay in memory
MODULE = 'place_ir'


def data_path(name):
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', name)


def load_country_data(env, files=FILES):
    """Read the CSV files into the database. Safe to run again: rows are keyed by xmlid."""
    for model_name, file_name in files:
        path = data_path(file_name)
        if not os.path.exists(path):
            _logger.warning("place_ir: %s is not there; skipped.", file_name)
            continue
        with open(path, newline='', encoding='utf-8') as handle:
            reader = csv.reader(handle)
            fields = next(reader)
            rows, total = [], 0
            # The xmlids in the files are bare; this says whose they are, so a parent
            # written on line 2 is found by the child on line 3.
            model = env[model_name].with_context(tracking_disable=True, install_mode=True,
                                                 _import_current_module=MODULE)
            for row in reader:
                rows.append(row)
                if len(rows) >= BATCH:
                    total += _load(model, fields, rows, file_name)
                    rows = []
            if rows:
                total += _load(model, fields, rows, file_name)
        _logger.info("place_ir: %s -> %d rows of %s", file_name, total, model_name)


def _load(model, fields, rows, file_name):
    result = model.load(fields, rows)
    for message in result.get('messages', []):
        _logger.warning("place_ir: %s: %s", file_name, message.get('message'))
    if not result.get('ids'):
        raise ValueError("place_ir: nothing loaded from %s; the first message says why." % file_name)
    return len(result['ids'])


class PlaceNode(models.Model):
    _inherit = 'place.node'

    @api.model
    def load_country_data(self):
        """Re-read the shipped files. For staff after the data files change -- the install
        hook calls the same function, so there is one way this data ever gets in."""
        load_country_data(self.env)
        return True
