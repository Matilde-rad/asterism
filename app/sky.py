"""Turn 'where in the sky' (RA/Dec) into 'where you were pointing' (compass + height)."""
from __future__ import annotations

from datetime import datetime

import astropy.units as u
from astropy.coordinates import AltAz, EarthLocation, SkyCoord
from astropy.time import Time
from astropy.utils import iers

# Don't download Earth-rotation tables at runtime; the built-in ones are plenty for this.
iers.conf.auto_download = False
iers.conf.iers_degraded_accuracy = "warn"

COMPASS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]


def compass_point(az_deg: float) -> str:
    return COMPASS[int(((az_deg % 360) + 22.5) // 45) % 8]


def facing(ra_deg: float, dec_deg: float, when_utc: datetime, lat: float, lon: float) -> dict:
    where = EarthLocation(lat=lat * u.deg, lon=lon * u.deg)
    frame = AltAz(obstime=Time(when_utc), location=where)
    altaz = SkyCoord(ra=ra_deg * u.deg, dec=dec_deg * u.deg).transform_to(frame)
    az = float(altaz.az.deg)
    return {"altitude_deg": round(float(altaz.alt.deg), 1), "azimuth_deg": round(az, 1),
            "compass": compass_point(az)}
