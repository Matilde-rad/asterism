import io
import time
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from PIL import Image

from app import main, photo, sky
from app.nova import NovaClient


def jpeg_bytes(w=64, h=48, exif=None) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (20, 20, 60)).save(buf, "JPEG", exif=exif or Image.Exif())
    return buf.getvalue()


# --- photo metadata ----------------------------------------------------------
def test_taken_at_uses_offset():
    t = photo.parse_taken_at("2026:11:28 22:30:00", "+01:00")
    assert t == datetime(2026, 11, 28, 21, 30, tzinfo=timezone.utc)


def test_taken_at_fallback_offset():
    t = photo.parse_taken_at("2026:11:28 22:30:00", None, fallback_offset_hours=0)
    assert t.hour == 22


def test_dms_west_is_negative():
    assert round(photo.dms_to_deg((9, 13, 12), "W"), 3) == -9.22


def test_field_width_for_24mm():
    assert 72 < photo.field_width_deg(24) < 75


def test_read_meta_with_exif():
    exif = Image.Exif()
    exif[0x010F] = "TestCam"  # real photos always have a camera make; Pillow needs one to write sub-IFDs
    sub = exif.get_ifd(photo.EXIF_IFD)
    sub[photo.DATETIME_ORIGINAL] = "2026:11:28 22:30:00"
    sub[photo.FOCAL_35MM] = 24
    meta = photo.read_photo_meta(jpeg_bytes(exif=exif))
    assert meta["width"] == 64 and meta["taken_at"] is not None and meta["field_width_deg"]


# --- sky geometry --------------------------------------------------------------
def test_polaris_altitude_matches_latitude():
    # Polaris sits almost exactly above the north pole, so its height ≈ your latitude.
    f = sky.facing(37.95, 89.26, datetime(2026, 11, 28, 22, tzinfo=timezone.utc), 39.42, -9.22)
    assert f["compass"] == "N" and abs(f["altitude_deg"] - 39.4) < 1.5


def test_compass_points():
    assert sky.compass_point(0) == "N" and sky.compass_point(225) == "SW" and sky.compass_point(350) == "N"


# --- API end to end with a fake solver ---------------------------------------------
class FakeNova(NovaClient):
    def __init__(self):
        self.uploaded_hints = None

    def upload(self, image, filename, hints=None):
        self.uploaded_hints = hints
        return 1

    def wait_for_job(self, subid, timeout=600, on_status=lambda s: None):
        on_status("solving")
        return 42

    def calibration(self, job_id):
        return {"ra": 83.8, "dec": -5.4, "radius": 12.0, "orientation": 15.0}

    def annotations(self, job_id):
        return [{"type": "bright", "names": ["Betelgeuse"], "pixelx": 10, "pixely": 12, "radius": 0},
                {"type": "hd", "names": ["HD 39801"], "pixelx": 10, "pixely": 12, "radius": 0}]


def test_solve_flow(monkeypatch):
    monkeypatch.setattr(main, "make_client", lambda: FakeNova())
    client = TestClient(main.app)
    r = client.post("/api/solve", files={"file": ("sky.jpg", jpeg_bytes(), "image/jpeg")},
                    data={"lat": "39.42", "lon": "-9.22"})
    job_id = r.json()["id"]
    for _ in range(50):
        job = client.get(f"/api/solve/{job_id}").json()
        if job["status"] in ("done", "failed"):
            break
        time.sleep(0.05)
    assert job["status"] == "done", job
    res = job["result"]
    assert res["center"]["ra_deg"] == 83.8
    assert res["objects"][0]["names"] == ["Betelgeuse"]
    assert res["location"] == {"lat": 39.42, "lon": -9.22}
    assert res["facing"] is None  # no timestamp in this photo


def test_missing_key_gives_clear_error(monkeypatch):
    monkeypatch.delenv("ASTROMETRY_API_KEY", raising=False)
    client = TestClient(main.app)
    job_id = client.post("/api/solve", files={"file": ("s.jpg", jpeg_bytes(), "image/jpeg")}).json()["id"]
    for _ in range(50):
        job = client.get(f"/api/solve/{job_id}").json()
        if job["status"] == "failed":
            break
        time.sleep(0.05)
    assert "ASTROMETRY_API_KEY" in job["error"]


def test_homepage_served():
    assert "Asterism" in TestClient(main.app).get("/").text
