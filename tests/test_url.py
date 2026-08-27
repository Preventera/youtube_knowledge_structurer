"""Tests d'extraction de l'identifiant de vidéo."""

from __future__ import annotations

import pytest

from yks.errors import InvalidYouTubeUrlError
from yks.ingestion.url import canonical_url, extract_video_id


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://youtube.com/watch?v=dQw4w9WgXcQ&t=42s", "dQw4w9WgXcQ"),
        ("https://m.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://youtu.be/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://youtu.be/dQw4w9WgXcQ?t=10", "dQw4w9WgXcQ"),
        ("https://www.youtube.com/shorts/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://www.youtube.com/embed/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://www.youtube.com/live/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("www.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("  dQw4w9WgXcQ  ", "dQw4w9WgXcQ"),
    ],
)
def test_extract_video_id_valide(value: str, expected: str) -> None:
    assert extract_video_id(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "",
        "   ",
        "https://vimeo.com/123456789",
        "https://www.youtube.com/",
        "https://www.youtube.com/watch",
        "https://www.youtube.com/watch?list=PL123",
        "https://www.youtube.com/shorts/",
        "abc",
        "https://youtu.be/",
    ],
)
def test_extract_video_id_invalide(value: str) -> None:
    with pytest.raises(InvalidYouTubeUrlError):
        extract_video_id(value)


def test_extract_video_id_type_incorrect() -> None:
    with pytest.raises(InvalidYouTubeUrlError):
        extract_video_id(None)  # type: ignore[arg-type]


def test_canonical_url() -> None:
    assert canonical_url("dQw4w9WgXcQ") == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
