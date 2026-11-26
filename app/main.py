"""Asterism: upload a night-sky photo, get its stars named.

POST /api/solve        -> start a solve, returns {"id": ...}
GET  /api/solve/{id}   -> poll status / result
GET  /                 -> the web page
"""
from __future__ import annotations

import os
import threading
import uuid
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.staticfiles import StaticFiles

from . import photo, sky
from .nova import NovaClient, NovaError

MAX_BYTES = 25 * 1024 * 1024
STATIC = Path(__file__).parent / "static"

app = FastAPI(title="Asterism")
_jobs: dict[str, dict] = {}
_lock = threading.Lock()


def make_client() -> NovaClient:
    return NovaClient(os.environ.get("ASTROMETRY_API_KEY", ""),
                      os.environ.get("NOVA_URL", "https://nova.astrometry.net"))


def _update(job_id: str, **fields) -> None:
    with _lock:
        _jobs[job_id].update(fields)


def run_solve(job_id: str, image: bytes, filename: str, offset_hours: float,
              lat: Optional[float], lon: Optional[float]) -> None:
    try:
        meta = photo.read_photo_meta(image, offset_hours)
        lat = lat if lat is not None else meta["lat"]
        lon = lon if lon is not None else meta["lon"]
        client = make_client()
        _update(job_id, status="uploading")
        subid = client.upload(image, filename, photo.scale_hints(meta["field_width_deg"]))
        nova_job = client.wait_for_job(subid, on_status=lambda s: _update(job_id, status=s))
        cal = client.calibration(nova_job)
        objects = [
            {"names": a.get("names", []), "type": a.get("type"), "x": a.get("pixelx"),
             "y": a.get("pixely"), "radius": a.get("radius")}
            for a in client.annotations(nova_job)
        ]
        result = {
            "image": {"width": meta["width"], "height": meta["height"]},
            "center": {"ra_deg": cal.get("ra"), "dec_deg": cal.get("dec")},
            "field_radius_deg": cal.get("radius"),
            "orientation_deg": cal.get("orientation"),
            "taken_at": meta["taken_at"].isoformat() if meta["taken_at"] else None,
            "location": {"lat": lat, "lon": lon} if lat is not None and lon is not None else None,
            "facing": None,
            "objects": objects,
        }
        if meta["taken_at"] and result["location"]:
            result["facing"] = sky.facing(cal["ra"], cal["dec"], meta["taken_at"], lat, lon)
        _update(job_id, status="done", result=result)
    except NovaError as e:
        _update(job_id, status="failed", error=str(e))
    except Exception as e:  # keep the web page informative instead of hanging
        _update(job_id, status="failed", error=f"Unexpected error: {e}")


@app.post("/api/solve")
async def start_solve(file: UploadFile = File(...), utc_offset_hours: float = Form(0.0),
                      lat: Optional[float] = Form(None), lon: Optional[float] = Form(None)):
    image = await file.read()
    if not image:
        raise HTTPException(400, "Empty file")
    if len(image) > MAX_BYTES:
        raise HTTPException(413, "Photo is larger than 25 MB")
    job_id = uuid.uuid4().hex[:12]
    with _lock:
        _jobs[job_id] = {"status": "received"}
    threading.Thread(target=run_solve, daemon=True,
                     args=(job_id, image, file.filename, utc_offset_hours, lat, lon)).start()
    return {"id": job_id}


@app.get("/api/solve/{job_id}")
def get_solve(job_id: str):
    with _lock:
        job = _jobs.get(job_id)
        if job is None:
            raise HTTPException(404, "Unknown job")
        return dict(job)


@app.get("/healthz")
def health():
    return {"ok": True}


app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
