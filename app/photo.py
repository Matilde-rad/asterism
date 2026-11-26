"""Read what the photo itself knows: when, where, and how zoomed in."""
from __future__ import annotations

import io
import math
from datetime import datetime, timedelta, timezone
from typing import Optional

from PIL import Image

EXIF_IFD = 0x8769
GPS_IFD = 0x8825
DATETIME_ORIGINAL = 36867
OFFSET_TIME_ORIGINAL = 36881
FOCAL_35MM = 41989


def _to_float(v) -> float:
    try:
        return float(v)
    except TypeError:  # (num, den) tuples on some cameras
        return v[0] / v[1]


def dms_to_deg(dms, ref: str) -> float:
    d, m, s = (_to_float(x) for x in dms)
    deg = d + m / 60 + s / 3600
    return -deg if ref in ("S", "W") else deg


def parse_taken_at(raw: Optional[str], offset: Optional[str],
                   fallback_offset_hours: float = 0.0) -> Optional[datetime]:
    """EXIF stores local time without a zone; OffsetTimeOriginal (e.g. '+01:00') fixes that."""
    if not raw:
        return None
    local = datetime.strptime(raw.strip(), "%Y:%m:%d %H:%M:%S")
    if offset:
        sign = -1 if offset.startswith("-") else 1
        hh, mm = offset.lstrip("+-").split(":")
        delta = timedelta(hours=int(hh), minutes=int(mm)) * sign
    else:
        delta = timedelta(hours=fallback_offset_hours)
    return (local - delta).replace(tzinfo=timezone.utc)


def field_width_deg(focal_35mm: Optional[float]) -> Optional[float]:
    """Horizontal field of view for a 35 mm-equivalent focal length (36 mm wide sensor)."""
    if not focal_35mm:
        return None
    return math.degrees(2 * math.atan(36 / (2 * focal_35mm)))


def read_photo_meta(image: bytes, fallback_offset_hours: float = 0.0) -> dict:
    img = Image.open(io.BytesIO(image))
    meta = {"width": img.width, "height": img.height, "taken_at": None,
            "lat": None, "lon": None, "field_width_deg": None}
    exif = img.getexif()
    if not exif:
        return meta
    sub = exif.get_ifd(EXIF_IFD)
    meta["taken_at"] = parse_taken_at(sub.get(DATETIME_ORIGINAL), sub.get(OFFSET_TIME_ORIGINAL),
                                      fallback_offset_hours)
    meta["field_width_deg"] = field_width_deg(sub.get(FOCAL_35MM))
    gps = exif.get_ifd(GPS_IFD)
    if gps.get(2) and gps.get(4):
        meta["lat"] = dms_to_deg(gps[2], gps.get(1, "N"))
        meta["lon"] = dms_to_deg(gps[4], gps.get(3, "E"))
    return meta


def scale_hints(field_deg: Optional[float]) -> dict:
    """Tell the solver roughly how wide the photo is, which makes solving much faster."""
    if not field_deg:
        return {}
    return {"scale_units": "degwidth", "scale_type": "ul",
            "scale_lower": round(field_deg * 0.7, 2), "scale_upper": round(field_deg * 1.3, 2)}
