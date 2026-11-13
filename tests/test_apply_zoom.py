import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import apply_zoom as az


def test_zoom_curve():
    pairs = [az.ZoomPair(2.0, 5.0, 640, 360)]
    assert az.zoom_at(pairs, 1.0, 0.5, 2.0) == pytest.approx(1.0)
    assert az.zoom_at(pairs, 2.25, 0.5, 2.0) == pytest.approx(1.5)
    assert az.zoom_at(pairs, 4.0, 0.5, 2.0) == pytest.approx(2.0)
    assert az.zoom_at(pairs, 5.25, 0.5, 2.0) == pytest.approx(1.5)
    assert az.zoom_at(pairs, 6.0, 0.5, 2.0) == pytest.approx(1.0)


def test_legacy_sidecar(tmp_path):
    path = tmp_path / "video.webm.zoom.json"
    path.write_text(json.dumps({
        "events": [
            {"t": 1.0, "x": 100, "y": 200},
            {"t": 2.0, "x": 100, "y": 200},
        ]
    }), encoding="utf-8")

    spec = az.load_sidecar(path)
    assert [event.type for event in spec.events] == ["in", "out"]


def test_crop_clamped():
    assert az.crop_at(640, 360, 2.0, 1280, 720) == (320.0, 180.0)
    assert az.crop_at(0, 0, 2.0, 1280, 720) == (0.0, 0.0)
    assert az.crop_at(1280, 720, 2.0, 1280, 720) == (640.0, 360.0)


def test_open_ended_filter():
    spec = az.ZoomSpec(1280, 720, 25, 2.0, 0.5, [])
    flt = az.build_zoom_filter(spec, [az.ZoomPair(1.0, None, 640, 360)])
    assert "gte(in_time,1.500)" in (flt or "") 


def test_no_events_copies(tmp_path, monkeypatch):
    video = tmp_path / "video.webm"
    video.write_bytes(b"fake video")

    monkeypatch.setattr(
        az.subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("ffmpeg must not run")
        ),
    )

    output = az.process_video(video, "ffmpeg", dry_run=False)
    assert output is not None
    assert output.read_bytes() == b"fake video"


def test_dry_run_prints_and_does_not_encode(tmp_path, capsys, monkeypatch):
    video = tmp_path / "video.webm"
    video.write_bytes(b"fake video")
    (tmp_path / "video.webm.zoom.json").write_text(
        '{"events": [{"t": 1, "x": 640, "y": 360, "type": "in"}]}',
        encoding="utf-8",
    )

    monkeypatch.setattr(
        az.subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("ffmpeg must not run")
        ),
    )

    az.process_video(video, "ffmpeg", dry_run=True)
    assert "zoompan" in capsys.readouterr().out
    assert not (tmp_path / "video.zoomed.webm").exists()
