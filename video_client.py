import time
from contextlib import ExitStack
from pathlib import Path

def _requests():
    import requests
    return requests


def UploadVideoInfo(server_url, video_path, company_name, sidecar_path=None):
    path = Path(video_path)
    if not path.is_file():
        raise FileNotFoundError(f"Видео не найдено: {video_path}")

    sidecar = Path(sidecar_path) if sidecar_path else None

    with ExitStack() as stack:
        video_file = stack.enter_context(path.open("rb"))
        files = {"file": (path.name, video_file)}

        if sidecar and sidecar.is_file():
            sidecar_file = stack.enter_context(sidecar.open("rb"))
            files["sidecar"] = (sidecar.name, sidecar_file)

        response = _requests().post(
            f"{server_url.rstrip('/')}/upload",
            files=files,
            data={"company_name": company_name},
            timeout=60,
        )

    response.raise_for_status()
    return response.json()


def UploadVideo(server_url, video_path, company_name, sidecar_path=None) -> str:
    info = UploadVideoInfo(server_url, video_path, company_name, sidecar_path)
    video_url = info.get("video_url")
    if not video_url:
        raise RuntimeError(f"Сервер не вернул video_url: {info}")
    return video_url

def GetVideoInfo(server_url, company_name) -> dict:
    response = _requests().get(
        f"{server_url.rstrip('/')}/get_video_url",
        params={"company_name": company_name},
        timeout=10,
    )
    response.raise_for_status()
    return response.json()

def GetVideoURL(server_url, company_name) -> str:
    info = GetVideoInfo(server_url, company_name)
    video_url = info.get("video_url")
    if not video_url:
        raise RuntimeError(f"Сервер не вернул video_url: {info}")
    return video_url

def ProcessVideo(server_url, video_id) -> dict:
    response = _requests().post(
        f"{server_url.rstrip('/')}/videos/{video_id}/process",
        timeout=10,
    )
    response.raise_for_status()
    return response.json()

def WaitForProcessed(server_url, company_name, timeout=60, interval=1.0) -> dict:
    deadline = time.monotonic() + timeout

    while True:
        info = GetVideoInfo(server_url, company_name)

        if info.get("processing_status") in ("done", "failed"):
            return info

        if time.monotonic() >= deadline:
            return info

        time.sleep(interval)
