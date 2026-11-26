"""Tiny client for the astrometry.net (nova) web API.

Flow: login -> upload image -> wait for a job -> wait for the job to finish
-> read calibration (where the photo points) and annotations (named objects).
"""
from __future__ import annotations

import json
import time
from typing import Callable, Optional

import requests


class NovaError(RuntimeError):
    pass


class NovaClient:
    def __init__(self, api_key: str, base_url: str = "https://nova.astrometry.net",
                 http: Optional[requests.Session] = None, poll_seconds: float = 5.0):
        if not api_key:
            raise NovaError("Missing ASTROMETRY_API_KEY (see .env.example)")
        self.api_key = api_key
        self.base = base_url.rstrip("/")
        self.http = http or requests.Session()
        self.poll_seconds = poll_seconds
        self.session_key: Optional[str] = None

    # --- low level -------------------------------------------------------
    def _post(self, path: str, payload: dict, files: Optional[dict] = None) -> dict:
        data = {"request-json": json.dumps(payload)}
        r = self.http.post(f"{self.base}/api/{path}", data=data, files=files, timeout=60)
        r.raise_for_status()
        body = r.json()
        if body.get("status") == "error":
            raise NovaError(body.get("errormessage", f"nova error on {path}"))
        return body

    def _get(self, path: str) -> dict:
        r = self.http.get(f"{self.base}/api/{path}", timeout=30)
        r.raise_for_status()
        return r.json()

    # --- API steps -------------------------------------------------------
    def login(self) -> str:
        body = self._post("login", {"apikey": self.api_key})
        self.session_key = body["session"]
        return self.session_key

    def upload(self, image: bytes, filename: str, hints: Optional[dict] = None) -> int:
        if not self.session_key:
            self.login()
        payload = {
            "session": self.session_key,
            "publicly_visible": "n",
            "allow_commercial_use": "n",
            "allow_modifications": "n",
        }
        payload.update(hints or {})
        files = {"file": (filename or "photo.jpg", image, "application/octet-stream")}
        return int(self._post("upload", payload, files=files)["subid"])

    def wait_for_job(self, subid: int, timeout: float = 600,
                     on_status: Callable[[str], None] = lambda s: None) -> int:
        """Wait until the submission gets a job id, then until that job finishes."""
        deadline = time.monotonic() + timeout
        job_id = None
        on_status("queued")
        while job_id is None:
            sub = self._get(f"submissions/{subid}")
            jobs = [j for j in sub.get("jobs", []) if j]
            if jobs:
                job_id = jobs[0]
                break
            self._sleep_or_timeout(deadline)
        on_status("solving")
        while True:
            status = self._get(f"jobs/{job_id}").get("status")
            if status == "success":
                return job_id
            if status == "failure":
                raise NovaError("Could not solve this photo (not enough sharp stars?)")
            self._sleep_or_timeout(deadline)

    def calibration(self, job_id: int) -> dict:
        return self._get(f"jobs/{job_id}/calibration/")

    def annotations(self, job_id: int) -> list[dict]:
        return self._get(f"jobs/{job_id}/annotations/").get("annotations", [])

    def _sleep_or_timeout(self, deadline: float) -> None:
        if time.monotonic() > deadline:
            raise NovaError("Timed out waiting for the solver")
        time.sleep(self.poll_seconds)
