import json
import os
import subprocess
import time
from pathlib import Path

import pytest
import requests

ROOT = Path(__file__).resolve().parents[1]
BASE_URL = os.environ.get("TEST_SERVER_URL", "http://127.0.0.1:8000")
COMPANY = "Integration Test"

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module", autouse=True)
def require_docker():
    if os.environ.get("RUN_DOCKER_TESTS") != "1":
        pytest.skip("set RUN_DOCKER_TESTS=1 to run integration tests")

    result = subprocess.run(
        ["docker", "compose", "ps", "--status", "running", "--services"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    running = set(result.stdout.split())

    if not {"db", "web", "worker"} <= running:
        pytest.skip("docker compose stack is not running")

    ffmpeg = subprocess.run(
        ["docker", "compose", "exec", "-T", "worker", "ffmpeg", "-version"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert ffmpeg.returncode == 0, ffmpeg.stderr


def test_upload_process_and_serve(tmp_path):
    video = ROOT / "video" / "Company1.webm"
    assert video.is_file(), f"нет тестового видео: {video}"

    sidecar = tmp_path / "video.webm.zoom.json"
    sidecar.write_text(json.dumps({
        "viewport": {"width": 1280, "height": 720},
        "fps": 25,
        "zoom_factor": 2.0,
        "ramp_sec": 0.5,
        "events": [
            {"t": 1.0, "x": 640, "y": 360, "type": "in"},
            {"t": 2.0, "x": 640, "y": 360, "type": "out"},
        ],
    }), encoding="utf-8")

    with video.open("rb") as video_file, sidecar.open("rb") as sidecar_file:
        response = requests.post(
            f"{BASE_URL}/upload",
            files={
                "file": (video.name, video_file),
                "sidecar": (sidecar.name, sidecar_file),
            },
            data={"company_name": COMPANY},
            timeout=60,
        )

    response.raise_for_status()
    info = response.json()

    assert info["processing_status"] == "uploaded"

    response = requests.post(
        f"{BASE_URL}/videos/{info['id']}/process",
        timeout=10,
    )
    assert response.status_code == 202

    deadline = time.monotonic() + 180

    while time.monotonic() < deadline:
        response = requests.get(
            f"{BASE_URL}/get_video_url",
            params={"company_name": COMPANY},
            timeout=10,
        )
        response.raise_for_status()
        info = response.json()

        if info.get("processing_status") in ("done", "failed"):
            break

        time.sleep(2)

    assert info["processing_status"] == "done", info
    assert info["processed_video_url"], info

    head = requests.head(info["processed_video_url"], timeout=10)
    assert head.status_code == 200, head.text
