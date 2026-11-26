"""End-to-end tests for the local ESA tetra3 solver, using simulated sky photos."""
import io
import time

import pytest
from fastapi.testclient import TestClient

pytest.importorskip("tetra3")

from app import main, solver  # noqa: E402
from app.simulate import render_sky  # noqa: E402


@pytest.fixture(scope="module")
def local():
    s = solver.LocalSolver()
    return s


def orion(local, rotate=0):
    img = render_sky(local.t3.star_table, ra_deg=83.8, dec_deg=-1.0, fov_deg=25)
    return img.rotate(rotate, fillcolor=(12, 12, 12)) if rotate else img


def test_finds_orion(local):
    sol = local.solve(orion(local), fov_deg=25)
    assert abs(sol["ra"] - 83.8) < 0.2 and abs(sol["dec"] + 1.0) < 0.2
    names = [o["names"][0] for o in sol["objects"]]
    assert {"Rigel", "Bellatrix", "Alnilam"} <= set(names)
    assert all(o["constellation"] for o in sol["objects"])


def test_tilted_camera_without_hint(local):
    # The fingerprint trick: tilt doesn't matter, and it measures the tilt for us.
    sol = local.solve(orion(local, rotate=37), fov_deg=None)
    assert abs(sol["ra"] - 83.8) < 0.3 and abs(sol["roll"] - 37) < 1


def test_empty_sky_returns_none(local):
    from PIL import Image
    assert local.solve(Image.new("RGB", (800, 600), (10, 10, 20)), fov_deg=25) is None


def test_api_uses_tetra3_first(monkeypatch, local):
    monkeypatch.setattr(solver, "get_local_solver", lambda: local)
    buf = io.BytesIO()
    orion(local).save(buf, "JPEG", quality=95)
    client = TestClient(main.app)
    job_id = client.post("/api/solve", files={"file": ("orion.jpg", buf.getvalue(), "image/jpeg")}).json()["id"]
    for _ in range(200):
        job = client.get(f"/api/solve/{job_id}").json()
        if job["status"] in ("done", "failed"):
            break
        time.sleep(0.05)
    assert job["status"] == "done", job
    assert job["result"]["solver"].startswith("tetra3 (ESA)")
    assert "Rigel" in [o["names"][0] for o in job["result"]["objects"]]
