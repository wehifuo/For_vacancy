from __future__ import annotations

import argparse
import json
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple, Sequence

DEFAULT_FPS = 25
DEFAULT_ZOOM = 2.0
DEFAULT_RAMP = 0.5


class ZoomEvent(NamedTuple):
    t: float
    x: float
    y: float
    type: str


class ZoomPair(NamedTuple):
    in_t: float
    out_t: float | None
    x: float
    y: float


class ZoomSpec(NamedTuple):
    width: int
    height: int
    fps: int
    zoom: float
    ramp: float
    events: list[ZoomEvent]


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def smoothstep(value: float) -> float:
    p = clamp(value, 0.0, 1.0)
    return p * p * (3.0 - 2.0 * p)


def load_sidecar(path: Path) -> ZoomSpec:
    if not path.is_file():
        return ZoomSpec(1280, 720, DEFAULT_FPS, DEFAULT_ZOOM, DEFAULT_RAMP, [])

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Не удалось прочитать sidecar {path}: {error}") from error

    if not isinstance(raw, dict):
        raise ValueError("sidecar должен быть JSON-объектом")

    viewport = raw.get("viewport") or {}
    width = int(viewport.get("width") or 1280)
    height = int(viewport.get("height") or 720)
    fps = int(raw.get("fps") or DEFAULT_FPS)
    zoom = float(raw.get("zoom_factor") or DEFAULT_ZOOM)
    ramp = float(raw.get("ramp_sec") or DEFAULT_RAMP)

    if (
        width <= 0
        or height <= 0
        or fps <= 0
        or not 1.0 < zoom <= 10.0
        or ramp <= 0
    ):
        raise ValueError("Некорректные параметры sidecar")

    raw_events = raw.get("events") or []
    if not isinstance(raw_events, list):
        raise ValueError("events должен быть списком")

    events: list[ZoomEvent] = []
    expected = "in"

    for index, item in enumerate(raw_events):
        try:
            t = float(item["t"])
            x = float(item["x"])
            y = float(item["y"])
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(
                f"events[{index}]: нужны числовые t, x, y"
            ) from error

        event_type = item.get("type")
        if event_type not in ("in", "out"):
            event_type = expected

        expected = "out" if event_type == "in" else "in"
        events.append(ZoomEvent(max(0.0, t), x, y, event_type))

    events.sort(key=lambda event: event.t)
    return ZoomSpec(width, height, fps, zoom, ramp, events)


def pair_events(events: Sequence[ZoomEvent]) -> list[ZoomPair]:
    pairs: list[ZoomPair] = []
    current: ZoomEvent | None = None

    for event in sorted(events, key=lambda item: item.t):
        if event.type == "in":
            if current is None:
                current = event
            continue

        if current is not None:
            if event.t > current.t:
                pairs.append(
                    ZoomPair(current.t, event.t, current.x, current.y)
                )
            current = None

    if current is not None:
        pairs.append(ZoomPair(current.t, None, current.x, current.y))

    return pairs


def pair_ramp(pair: ZoomPair, ramp: float) -> float:
    if pair.out_t is None:
        return ramp
    return max(0.001, min(ramp, (pair.out_t - pair.in_t) / 2.0))


def pair_delta(
    pair: ZoomPair,
    t: float,
    ramp: float,
    zoom: float,
) -> float:
    delta = zoom - 1.0
    r = pair_ramp(pair, ramp)

    if t < pair.in_t:
        return 0.0
    if t < pair.in_t + r:
        return delta * smoothstep((t - pair.in_t) / r)
    if pair.out_t is None:
        return delta
    if t < pair.out_t:
        return delta
    if t < pair.out_t + r:
        return delta * (1.0 - smoothstep((t - pair.out_t) / r))
    return 0.0


def zoom_at(
    pairs: Sequence[ZoomPair],
    t: float,
    ramp: float,
    zoom: float,
) -> float:
    total = 1.0 + sum(
        pair_delta(pair, t, ramp, zoom) for pair in pairs
    )
    return min(zoom, total)


def crop_at(
    center_x: float,
    center_y: float,
    zoom: float,
    width: int,
    height: int,
) -> tuple[float, float]:
    zoom = max(1.0, zoom)
    crop_w = width / zoom
    crop_h = height / zoom
    x = clamp(center_x - crop_w / 2.0, 0.0, width - crop_w)
    y = clamp(center_y - crop_h / 2.0, 0.0, height - crop_h)
    return x, y


def _ease_expr(p: str) -> str:
    return f"pow({p},2)*(3-2*{p})"


def _delta_expr(pair: ZoomPair, zoom: float, ramp: float) -> str:
    a, b = pair.in_t, pair.out_t
    delta = zoom - 1.0
    r = pair_ramp(pair, ramp)

    p_in = f"(in_time-{a:.3f})/{r:.3f}"
    ease_in = _ease_expr(p_in)

    if b is None:
        return (
            f"if(between(in_time,{a:.3f},{a + r:.3f}),"
            f"{delta:.3f}*({ease_in}),"
            f"if(gte(in_time,{a + r:.3f}),{delta:.3f},0))"
        )

    p_out = f"(in_time-{b:.3f})/{r:.3f}"
    ease_out = _ease_expr(p_out)
    return (
        f"if(between(in_time,{a:.3f},{a + r:.3f}),"
        f"{delta:.3f}*({ease_in}),"
        f"if(between(in_time,{a + r:.3f},{b:.3f}),{delta:.3f},"
        f"if(between(in_time,{b:.3f},{b + r:.3f}),"
        f"{delta:.3f}*(1-({ease_out})),0)))"
    )


def build_zoom_filter(
    spec: ZoomSpec,
    pairs: Sequence[ZoomPair],
) -> str | None:
    valid: list[tuple[ZoomPair, float, float, float]] = []

    for pair in pairs:
        if pair.out_t is not None and pair.out_t <= pair.in_t:
            continue
        ramp = pair_ramp(pair, spec.ramp)
        x = clamp(pair.x, 0.0, float(spec.width))
        y = clamp(pair.y, 0.0, float(spec.height))
        valid.append((pair, x, y, ramp))

    if not valid:
        return None

    deltas = [
        _delta_expr(pair, spec.zoom, spec.ramp)
        for pair, _, _, _ in valid
    ]
    zoom_expr = f"min({spec.zoom:.3f},1+{'+'.join(deltas)})"

    center_x = "iw/2"
    center_y = "ih/2"

    for pair, x, y, ramp in reversed(valid):
        if pair.out_t is None:
            condition = f"gte(in_time,{pair.in_t:.3f})"
        else:
            condition = (
                f"between(in_time,{pair.in_t:.3f},"
                f"{pair.out_t + ramp:.3f})"
            )
        center_x = f"if({condition},{x:.3f},{center_x})"
        center_y = f"if({condition},{y:.3f},{center_y})"

    return (
        f"zoompan=z='{zoom_expr}':"
        f"x='clip({center_x}-iw/(2*zoom),0,iw-iw/zoom)':"
        f"y='clip({center_y}-ih/(2*zoom),0,ih-ih/zoom)':"
        f"d=1:s={spec.width}x{spec.height}:fps={spec.fps}"
    )


def _copy(video: Path, output: Path, dry_run: bool) -> Path | None:
    if dry_run:
        print(f"cp {shlex.quote(str(video))} {shlex.quote(str(output))}")
        return None

    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(video, output)
    return output


def process_video(video: Path, ffmpeg: str, dry_run: bool) -> Path | None:
    if not video.is_file():
        raise FileNotFoundError(f"Видео не найдено: {video}")

    sidecar = Path(str(video) + ".zoom.json")
    output = video.with_name(video.stem + ".zoomed.webm")

    if video.resolve() == output.resolve():
        raise ValueError("output не должен совпадать с input")

    spec = load_sidecar(sidecar)
    pairs = pair_events(spec.events)

    if not pairs:
        return _copy(video, output, dry_run)

    filter_expr = build_zoom_filter(spec, pairs)
    if filter_expr is None:
        return _copy(video, output, dry_run)

    command = [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-i", str(video),
        "-vf", filter_expr,
        "-c:v", "libvpx-vp9",
        "-b:v", "0",
        "-crf", "32",
        "-row-mt", "1",
        "-cpu-used", "2",
        "-deadline", "good",
        "-pix_fmt", "yuv420p",
        "-an",
        str(output),
    ]

    if dry_run:
        print(shlex.join(command))
        return None

    output.parent.mkdir(parents=True, exist_ok=True)

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=300,
        )
    except FileNotFoundError as error:
        raise RuntimeError(f"ffmpeg не найден: {ffmpeg}") from error
    except subprocess.TimeoutExpired as error:
        raise RuntimeError("ffmpeg превысил таймаут 300 секунд") from error

    if result.returncode != 0:
        raise RuntimeError(
            f"ffmpeg завершился с кодом {result.returncode}:\n"
            f"{(result.stderr or '').strip()[-2000:]}"
        )

    return output


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Camtasia-style zoom для записанного видео",
    )
    parser.add_argument("--video", required=True)
    parser.add_argument("--ffmpeg")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    video = Path(args.video).expanduser().resolve()
    ffmpeg = args.ffmpeg or shutil.which("ffmpeg") or "ffmpeg"

    try:
        result = process_video(video, ffmpeg, args.dry_run)
    except (FileNotFoundError, ValueError, RuntimeError) as error:
        print(f"Ошибка: {error}", file=sys.stderr)
        return 1

    if result is not None:
        print(f"Готово: {result}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
