"""Read what the photo itself knows: when, where, and how zoomed in."""
from __future__ import annotations

import io
import math
from datetime import datetime, timedelta, timezone
from typing import Optional

from PIL import Image, ImageOps

EXIF_IFD = 0x8769
GPS_IFD = 0x8825
DATETIME_ORIGINAL = 36867
OFFSET_TIME_ORIGINAL = 36881
FOCAL_35MM = 41989
FOCAL_LENGTH = 37386
FOCAL_PLANE_X_RES = 41486
FOCAL_PLANE_RES_UNIT = 41488   # 2 = inch, 3 = cm
EXIF_IMAGE_WIDTH = 40962


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


def field_width_from_sensor(focal_mm, x_res, unit, pixel_width) -> Optional[float]:
    """Canon & most DSLRs skip the 35 mm-equivalent tag, but they record how many pixels
    fit in an inch/cm of sensor. That gives the real sensor width, and with the focal
    length, the field of view: 2 * atan(sensor_width / (2 * focal))."""
    try:
        focal, x_res = _to_float(focal_mm), _to_float(x_res)
    except (TypeError, ZeroDivisionError):
        return None
    if not focal or not x_res or not pixel_width:
        return None
    mm_per_unit = {2: 25.4, 3: 10.0, 4: 1.0}.get(int(unit or 2), 25.4)
    sensor_mm = pixel_width / x_res * mm_per_unit
    if not 4 < sensor_mm < 60:  # sanity check: phone to medium format
        return None
    return math.degrees(2 * math.atan(sensor_mm / (2 * focal)))


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
    meta["field_width_deg"] = field_width_deg(sub.get(FOCAL_35MM)) or field_width_from_sensor(
        sub.get(FOCAL_LENGTH), sub.get(FOCAL_PLANE_X_RES), sub.get(FOCAL_PLANE_RES_UNIT),
        sub.get(EXIF_IMAGE_WIDTH) or img.width)
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


def prepare_upload(image: bytes, max_side: int = 2000) -> tuple[bytes, float, int, int]:
    """Rotate upright (like the browser shows it) and shrink big photos so uploads are fast.

    Returns (jpeg_bytes, factor, width, height) where factor converts solver pixel
    coordinates back to the full-size upright photo.
    """
    img = ImageOps.exif_transpose(Image.open(io.BytesIO(image))).convert("RGB")
    width, height = img.size
    factor = max(width, height) / max_side if max(width, height) > max_side else 1.0
    if factor > 1:
        img = img.resize((round(width / factor), round(height / factor)), Image.LANCZOS)
    out = io.BytesIO()
    img.save(out, "JPEG", quality=92)
    return out.getvalue(), factor, width, height
