"""Sky simulator: draw a fake camera photo of any part of the sky from a star catalogue.

Used by the tests (and handy for experiments): point a virtual camera at, say, Orion,
render the stars it would see, then check the solver finds Orion again.

Geometry (gnomonic projection, like a real lens without distortion):
  - b = direction the camera points at, e = east, n = north (unit vectors)
  - a star in direction v lands at  xi = (v.e)/(v.b),  eta = (v.n)/(v.b)  on the image plane
  - pixels: x = W/2 - f*xi,  y = H/2 - f*eta,  with f = (W/2) / tan(FOV/2)
    (east is on the left when you look up at the sky, north is up)
"""
from __future__ import annotations

import numpy as np
from PIL import Image, ImageFilter


def render_sky(star_table: np.ndarray, ra_deg: float, dec_deg: float, fov_deg: float,
               width: int = 1500, height: int = 1000, max_mag: float = 5.5) -> Image.Image:
    """star_table rows: [ra_rad, dec_rad, x, y, z, magnitude] (tetra3's format)."""
    a0, d0 = np.radians(ra_deg), np.radians(dec_deg)
    b = np.array([np.cos(d0) * np.cos(a0), np.cos(d0) * np.sin(a0), np.sin(d0)])
    e = np.array([-np.sin(a0), np.cos(a0), 0.0])
    n = np.cross(b, e)
    f = (width / 2) / np.tan(np.radians(fov_deg) / 2)

    vecs, mags = star_table[:, 2:5], star_table[:, 5]
    keep = (vecs @ b > 0.2) & (mags <= max_mag)
    v, m = vecs[keep], mags[keep]
    xi, eta = (v @ e) / (v @ b), (v @ n) / (v @ b)
    xs, ys = width / 2 - f * xi, height / 2 - f * eta

    sky = np.full((height, width), 12.0)
    yy, xx = np.mgrid[-4:5, -4:5]
    for x, y, mag in zip(xs, ys, m):
        if 4 <= x < width - 4 and 4 <= y < height - 4:
            peak = min(255.0, 2200 * 10 ** (-0.4 * mag))   # brighter star = bigger number
            spot = peak * np.exp(-(xx ** 2 + yy ** 2) / (2 * 1.3 ** 2))
            xi0, yi0 = int(round(x)), int(round(y))
            sky[yi0 - 4:yi0 + 5, xi0 - 4:xi0 + 5] += spot
    rng = np.random.default_rng(0)
    sky += rng.normal(0, 2.0, sky.shape)  # a little sensor noise
    img = Image.fromarray(np.clip(sky, 0, 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(0.5))
    return img.convert("RGB")
