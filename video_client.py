from pathlib import Path


def _requests():
    import requests

    return requests


def UploadVideo(server_url: str, video_path: str, company_name: str) -> str:
    path = Path(video_path)
    if not path.is_file():
        raise FileNotFoundError(f"Видео не найдено: {video_path}")

    requests = _requests()

    with path.open("rb") as file_obj:
        response = requests.post(
            f"{server_url.rstrip("/")}/upload",
            files={"file": (path.name, file_obj)},
            data={"company_name": company_name},
            timeout=60,
        )

    response.raise_for_status()

    video_url = response.json().get("video_url")
    if not video_url:
        raise RuntimeError(f"Сервер не вернул video_url: {response.text}")
    return video_url


def GetVideoURL(server_url: str, company_name: str) -> str:

    requests = _requests()

    response = requests.get(
        f"{server_url.rstrip("/")}/get_video_url",
        params={"company_name": company_name},
        timeout=10,
    )

    response.raise_for_status()

    video_url = response.json().get("video_url")
    if not video_url:
        raise RuntimeError(f"Сервер не вернул video_url: {response.text}")
    return video_url
