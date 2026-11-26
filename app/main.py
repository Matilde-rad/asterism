"""Asterism: upload a night-sky photo, get its stars named.

POST /api/solve        -> start a solve, returns {"id": ...}
GET  /api/solve/{id}   -> poll status / result
GET  /                 -> the web page
"""
from __future__ import annotations

import io
import os
import threading
import uuid
from pathlib import Path
from typing import Optional

import requests
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.staticfiles import StaticFiles
from PIL import Image

from . import photo, sky, solver
from .nova import NovaClient, NovaError

MAX_BYTES = 25 * 1024 * 1024
STATIC = Path(__file__).parent / "static"

app = FastAPI(title="Asterism")


@app.on_event("startup")
def warm_up_solver() -> None:
    # Loading the star database takes a moment: do it in the background at startup.
    threading.Thread(target=solver.get_local_solver, daemon=True).start()
_jobs: dict[str, dict] = {}
_lock = threading.Lock()


def make_client() -> NovaClient:
    return NovaClient(os.environ.get("ASTROMETRY_API_KEY", ""),
                      os.environ.get("NOVA_URL", "https://nova.astrometry.net"))


def _update(job_id: str, **fields) -> None:
    with _lock:
        _jobs[job_id].update(fields)


def _scaled(v, factor):
    return None if v is None else v * factor


def solve_locally(upload: bytes, fov: Optional[float]) -> Optional[dict]:
    """Try ESA's tetra3 first: runs right here, no internet needed."""
    local = solver.get_local_solver()
    if local is None or not local.covers(fov):
        return None
    sol = local.solve(Image.open(io.BytesIO(upload)), fov)
    if sol is None:
        return None
    return {"ra": sol["ra"], "dec": sol["dec"], "field_width_deg": sol["fov"],
            "orientation_deg": sol["roll"], "objects": sol["objects"],
            "solver": f"tetra3 (ESA) · {sol['matches']} stars matched in {sol['solve_ms']:.0f} ms"}


def solve_with_astrometry(upload: bytes, fov: Optional[float], job_id: str) -> dict:
    """Backup: send the photo to astrometry.net (needs ASTROMETRY_API_KEY)."""
    client = make_client()
    _update(job_id, status="uploading")
    subid = client.upload(upload, "photo.jpg", photo.scale_hints(fov))
    nova_job = client.wait_for_job(subid, on_status=lambda s: _update(job_id, status=s))
    cal = client.calibration(nova_job)
    objects = [{"names": a.get("names", []), "type": a.get("type"), "x": a.get("pixelx"),
                "y": a.get("pixely"), "radius": a.get("radius")}
               for a in client.annotations(nova_job)]
    return {"ra": cal.get("ra"), "dec": cal.get("dec"),
            "field_width_deg": (cal["radius"] * 2 / 1.2) if cal.get("radius") else None,
            "orientation_deg": cal.get("orientation"), "objects": objects,
            "solver": "astrometry.net"}


def run_solve(job_id: str, image: bytes, filename: str, offset_hours: float,
              lat: Optional[float], lon: Optional[float]) -> None:
    try:
        meta = photo.read_photo_meta(image, offset_hours)
        lat = lat if lat is not None else meta["lat"]
        lon = lon if lon is not None else meta["lon"]
        upload, factor, width, height = photo.prepare_upload(image)
        fov = meta["field_width_deg"]

        _update(job_id, status="matching")
        solved = solve_locally(upload, fov)
        if solved is None:
            if not os.environ.get("ASTROMETRY_API_KEY"):
                raise NovaError("Couldn't match the stars in this photo. Try one with more sharp "
                                "stars, or set ASTROMETRY_API_KEY to use astrometry.net as backup.")
            solved = solve_with_astrometry(upload, fov, job_id)

        for o in solved["objects"]:  # back to full-size photo pixels
            o["x"], o["y"], o["radius"] = (_scaled(o.get(k), factor) for k in ("x", "y", "radius"))
        result = {
            "image": {"width": width, "height": height},
            "center": {"ra_deg": solved["ra"], "dec_deg": solved["dec"]},
            "field_width_deg": solved["field_width_deg"],
            "orientation_deg": solved["orientation_deg"],
            "solver": solved["solver"],
            "taken_at": meta["taken_at"].isoformat() if meta["taken_at"] else None,
            "location": {"lat": lat, "lon": lon} if lat is not None and lon is not None else None,
            "facing": None,
            "objects": solved["objects"],
        }
        if meta["taken_at"] and result["location"]:
            result["facing"] = sky.facing(solved["ra"], solved["dec"], meta["taken_at"], lat, lon)
        _update(job_id, status="done", result=result)
    except NovaError as e:
        _update(job_id, status="failed", error=str(e))
    except requests.RequestException:
        _update(job_id, status="failed",
                error="astrometry.net isn't responding right now (it's a free, busy service). "
                      "Try again in a few minutes.")
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
