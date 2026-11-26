"""Build the star-pattern database for Matilde's Canon 1200D + EF-S 18-55 mm lens.

Field of view across the photo (APS-C sensor, 22.3 mm wide):
    18 mm -> ~64 deg     35 mm -> ~35 deg     55 mm -> ~23 deg
so we build for 20-70 deg, which covers the whole zoom range.

What happens:
1. download the Hipparcos catalogue (118,218 stars, ~51 MB) once
2. tetra3 cuts the whole sky into photo-sized patches, takes the brightest stars in each,
   makes every 4-star pattern, computes its fingerprint (edge ratios) and stores it
3. the table is saved to app/data/canon_1200d_18-55.npz, which the app loads at startup

Run from the project folder:   python scripts/build_database.py
"""
from __future__ import annotations

import argparse
import gzip
import math
import shutil
import time
import urllib.request
from pathlib import Path

import numpy as np

if not hasattr(np, "math"):  # tetra3 still calls np.math, which NumPy 2 removed
    np.math = math

import tetra3  # noqa: E402

# Same file from several places (the CDS archive in Strasbourg has had a few domain names).
MIRRORS = [
    "https://vizier.cfa.harvard.edu/ftp/cats/i/239/hip_main.dat",   # Harvard mirror of CDS
    "https://cdsarc.cds.unistra.fr/ftp/cats/I/239/hip_main.dat",
    "https://cdsarc.u-strasbg.fr/ftp/cats/I/239/hip_main.dat",
]
PROJECT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = PROJECT / "app" / "data" / "canon_1200d_18-55.npz"


def ensure_catalogue(manual: Path | None = None) -> Path:
    # tetra3 looks for the catalogue next to its own code
    target = Path(tetra3.__file__).parent / "hip_main.dat"
    if target.exists() and target.stat().st_size > 40_000_000:
        print(f"Catalogue already there: {target}")
        return target
    if manual:
        _install(manual, target)
        return target
    for url in MIRRORS:
        print(f"Trying {url} ...")
        tmp = target.with_suffix(".download")
        try:
            urllib.request.urlretrieve(url, tmp)
        except OSError as e:
            print(f"  failed: {e}")
            continue
        _install(tmp, target)
        tmp.unlink(missing_ok=True)
        return target
    raise SystemExit(
        "\nCouldn't download the catalogue from any mirror.\n"
        "Download hip_main.dat in your browser from one of:\n  " + "\n  ".join(MIRRORS[:2]) +
        "\nthen run:  python scripts/build_database.py --catalogue PATH\\TO\\hip_main.dat.gz")


def _install(source: Path, target: Path) -> None:
    """Copy (and un-gzip if needed) the catalogue to where tetra3 expects it."""
    with open(source, "rb") as f:
        gz = f.read(2) == b"\x1f\x8b"
    opener = gzip.open if gz else open
    with opener(source, "rb") as src, open(target, "wb") as dst:
        shutil.copyfileobj(src, dst)
    print(f"Catalogue ready: {target} ({target.stat().st_size / 1e6:.0f} MB)")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--min-fov", type=float, default=20, help="narrowest photo width in degrees")
    ap.add_argument("--max-fov", type=float, default=70, help="widest photo width in degrees")
    ap.add_argument("--max-mag", type=float, default=7, help="faintest stars to include")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--catalogue", type=Path, help="hip_main.dat(.gz) you downloaded yourself")
    args = ap.parse_args()

    ensure_catalogue(args.catalogue)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    print(f"Building database for {args.min_fov}-{args.max_fov} deg (this takes a few minutes) ...")
    t0 = time.time()
    t3 = tetra3.Tetra3(load_database=None)
    t3.generate_database(max_fov=args.max_fov, min_fov=args.min_fov, save_as=args.out,
                         star_catalog="hip_main", star_max_magnitude=args.max_mag)
    size_mb = args.out.with_suffix(".npz").stat().st_size / 1e6
    print(f"Saved {args.out.with_suffix('.npz')} ({size_mb:.1f} MB) in {time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()
