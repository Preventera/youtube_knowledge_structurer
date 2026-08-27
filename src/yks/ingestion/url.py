"""Extraction et validation de l'identifiant d'une vidéo YouTube."""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

from ..errors import InvalidYouTubeUrlError

_VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{6,32}$")

_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtube-nocookie.com",
    "www.youtube-nocookie.com",
}
_SHORT_HOSTS = {"youtu.be", "www.youtu.be"}
_PATH_PREFIXES = ("/shorts/", "/embed/", "/live/", "/v/")


def extract_video_id(value: str) -> str:
    """Retourne l'identifiant d'une vidéo à partir d'une URL ou d'un identifiant.

    Formats acceptés :

    - ``https://www.youtube.com/watch?v=VIDEO_ID``
    - ``https://youtu.be/VIDEO_ID``
    - ``https://www.youtube.com/shorts/VIDEO_ID``
    - ``https://www.youtube.com/embed/VIDEO_ID`` et ``/live/VIDEO_ID``
    - un identifiant nu

    :raises InvalidYouTubeUrlError: si aucun identifiant valide ne peut être extrait.
    """
    if not isinstance(value, str) or not value.strip():
        raise InvalidYouTubeUrlError("Aucune URL ou identifiant fourni")

    text = value.strip()

    if _VIDEO_ID_RE.match(text) and "/" not in text and "." not in text:
        return text

    candidate = text if "//" in text else f"https://{text}"
    parsed = urlparse(candidate)
    host = (parsed.hostname or "").lower()
    path = parsed.path or ""

    found: str | None = None
    if host in _SHORT_HOSTS:
        found = path.strip("/").split("/")[0] or None
    elif host in _HOSTS:
        if path == "/watch":
            values = parse_qs(parsed.query).get("v") or []
            found = values[0] if values else None
        else:
            for prefix in _PATH_PREFIXES:
                if path.startswith(prefix):
                    parts = path.strip("/").split("/")
                    found = parts[1] if len(parts) >= 2 else None
                    break
    else:
        raise InvalidYouTubeUrlError(
            f"Domaine non reconnu comme une URL YouTube : {host or value!r}"
        )

    if not found or not _VIDEO_ID_RE.match(found):
        raise InvalidYouTubeUrlError(
            f"Impossible d'extraire un identifiant valide de : {value!r}"
        )
    return found


def canonical_url(video_id: str) -> str:
    """Retourne l'URL canonique de la vidéo."""
    return f"https://www.youtube.com/watch?v={video_id}"
