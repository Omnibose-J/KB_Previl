"""Read-only query layer for the UI.

All scoring happens in ``service.precompute``. This package only reads indexed
SQLite tables and never exposes the model score: users see the survival rate
observed for each grade on held-out data.

Layering, outermost last — no module imports one below it:

    base      error contract, the read-only connection, value coercions
    context   batch enrichment for a set of cells (neighbours, party, sales, concepts)
    cells     one cell: select, polygon, detail payload
    meta      city-wide tables: districts, survival benchmarks, grade x area
    search    entry points that take user input and return cells
    changes   what moved between two scoring runs
"""
from pipeline.grid import neighbors
from service import alerts

from . import base
from .base import (
    ApiInputError,
    DatabaseUnavailableError,
    MAX_GRID_CELLS,
    ResourceNotFoundError,
    ViewportTooLargeError,
)
from .cells import NOT_EVALUATED_DETAIL, RESOLUTION, location_names
from .changes import grid_changes
from .context import PARTY_PRECISION, REST_EATERY
from .meta import _grade_area, areas, meta
from .search import at_point, grid_detail, grids, recommend

__all__ = [
    "ApiInputError",
    "DatabaseUnavailableError",
    "MAX_GRID_CELLS",
    "NOT_EVALUATED_DETAIL",
    "PARTY_PRECISION",
    "RESOLUTION",
    "REST_EATERY",
    "ResourceNotFoundError",
    "ViewportTooLargeError",
    "_grade_area",
    "alerts",
    "base",
    "areas",
    "at_point",
    "grid_changes",
    "grid_detail",
    "grids",
    "location_names",
    "meta",
    "neighbors",
    "recommend",
]
