"""Local plate solving with tetra3, ESA's open-source star-tracker algorithm.

How it works (see README for the full walk-through):
1. find the stars in the photo (bright blobs -> pixel positions, brightest first)
2. take 4 stars, measure the 6 distances between them, divide by the longest
   -> a "fingerprint" that doesn't change when you tilt or zoom the camera
3. look the fingerprint up in a database built from the Hipparcos star catalogue
4. check the guess: predict where other stars should be and see if they're there

Star names: Hipparcos number -> name, from Skyfield's named-star list (MIT licence).
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Optional

import astropy.units as u
from astropy.coordinates import SkyCoord, get_constellation
from PIL import Image

DATA = Path(__file__).parent / "data"
NAMES_FILE = DATA / "star_names.json"
CANON_DB = DATA / "canon_1200d_18-55.npz"  # built by scripts/build_database.py


class LocalSolver:
    def __init__(self, database: Optional[str] = None):
        import math

        import numpy as np
        if not hasattr(np, "math"):  # tetra3 still calls np.math, which NumPy 2 removed
            np.math = math
        from tetra3 import Tetra3  # heavy import, only when actually used

        # A path to a custom database (e.g. our Canon one), or tetra3's built-in 10-30 degree one.
        self.t3 = Tetra3(load_database=Path(database) if database else "default_database")
        props = self.t3.database_properties
        self.min_fov = float(props["min_fov"])
        self.max_fov = float(props["max_fov"])
        self.names = {int(k): v for k, v in json.loads(NAMES_FILE.read_text("utf-8")).items()}

    def covers(self, fov_deg: Optional[float]) -> bool:
        """Is this photo's width inside the range the database was built for?"""
        return fov_deg is None or self.min_fov * 0.85 <= fov_deg <= self.max_fov * 1.15

    def solve(self, image: Image.Image, fov_deg: Optional[float] = None) -> Optional[dict]:
        kwargs = {"return_matches": True, "solve_timeout": 20_000}
        if fov_deg:
            kwargs.update(fov_estimate=fov_deg, fov_max_error=max(1.0, fov_deg * 0.12))
        # Wide lenses bend the edges of the picture (barrel distortion): let tetra3 search for it.
        kwargs["distortion"] = (-0.15, 0.0) if (fov_deg or 0) > 35 else 0
        gray = image.convert("L")
        sol = {}
        # Pass 1: normal sharp stars. Pass 2: out-of-focus photos, where stars are big soft discs
        # (tetra3 ignores blobs bigger than 100 pixels by default).
        for blob_settings in ({}, {"max_area": 1500, "min_area": 20}):
            sol = self.t3.solve_from_image(gray, **kwargs, **blob_settings)
            if sol.get("RA") is not None:
                break
        if sol.get("RA") is None:
            return None

        cat_ids = [int(c) for c in sol.get("matched_catID", [])]
        stars = sol.get("matched_stars", [])
        constellations = []
        if len(stars):
            coords = SkyCoord(ra=[s[0] for s in stars] * u.deg, dec=[s[1] for s in stars] * u.deg)
            # (astropy's table spells it "Ophiucus")
            constellations = [str(c).replace("Ophiucus", "Ophiuchus") for c in get_constellation(coords)]

        objects = []
        for i, ((y, x), hip) in enumerate(zip(sol.get("matched_centroids", []), cat_ids)):
            name = self.names.get(hip)
            objects.append({
                "names": [name, f"HIP {hip}"] if name else [f"HIP {hip}"],
                "type": "bright" if name else "hip",
                "x": float(x), "y": float(y), "radius": 0,
                "mag": round(float(stars[i][2]), 2) if i < len(stars) else None,
                "constellation": str(constellations[i]) if i < len(constellations) else None,
            })
        objects.sort(key=lambda o: (o["type"] != "bright", o["mag"] if o["mag"] is not None else 99))
        return {
            "ra": float(sol["RA"]), "dec": float(sol["Dec"]), "roll": _tidy_angle(sol["Roll"]),
            "fov": float(sol["FOV"]), "matches": int(sol["Matches"]),
            "false_positive_prob": float(sol["Prob"]), "solve_ms": float(sol["T_solve"]),
            "objects": objects,
        }


def _tidy_angle(deg) -> float:
    a = float(deg) % 360
    return 0.0 if a > 359.95 else round(a, 1)


_solver: Optional[LocalSolver] = None
_solver_lock = threading.Lock()
_solver_failed = False


def get_local_solver() -> Optional[LocalSolver]:
    """Load the database once (it takes a few seconds) and reuse it for every photo."""
    global _solver, _solver_failed
    if os.environ.get("LOCAL_SOLVER", "on").lower() == "off" or _solver_failed:
        return None
    with _solver_lock:
        if _solver is None:
            try:
                db = os.environ.get("TETRA3_DATABASE") or (str(CANON_DB) if CANON_DB.exists() else None)
                _solver = LocalSolver(db)
            except Exception:  # missing tetra3 / database: fall back to astrometry.net
                _solver_failed = True
                return None
        return _solver
