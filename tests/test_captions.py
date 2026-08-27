"""Tests de récupération des sous-titres et de normalisation des segments."""

from __future__ import annotations

import pytest

from tests.conftest import FakeApi, FakeTranscript, FakeTranscriptList
from yks.errors import (
    EmptyTranscriptError,
    InvalidYouTubeUrlError,
    TranscriptFetchError,
    TranscriptNotFoundError,
    TranscriptsDisabledError,
    VideoUnavailableError,
)
from yks.ingestion.captions import fetch_captions
from yks.transcription.segments import (
    build_segments,
    estimate_quality,
    format_for_model,
    is_noise,
    normalize_text,
    total_duration,
    transcript_hash,
)

# --- Normalisation ---------------------------------------------------------


def test_normalize_text_retire_balises_et_entites() -> None:
    assert normalize_text("Bonjour <i>tout</i>&nbsp;le   monde&amp;") == "Bonjour tout le monde&"


def test_normalize_text_conserve_les_accents() -> None:
    assert normalize_text("é à ù ç œ") == "é à ù ç œ"


def test_is_noise() -> None:
    assert is_noise("[Musique]")
    assert is_noise("[Applaudissements]")
    assert not is_noise("[Musique] et du texte")


def test_build_segments_filtre_le_bruit(raw_segments: list[dict]) -> None:
    segments = build_segments(raw_segments)
    assert len(segments) == 3
    assert segments[0].index == 0
    assert segments[1].timestamp == "00:04:18"
    assert all(s.text.strip() for s in segments)


def test_build_segments_vide() -> None:
    with pytest.raises(EmptyTranscriptError):
        build_segments([{"text": "[Musique]", "start": 0, "duration": 1}])


def test_build_segments_ignore_valeurs_illisibles() -> None:
    segments = build_segments(
        [
            {"text": "Valide", "start": "abc", "duration": 1},
            {"text": "Aussi valide", "start": 5, "duration": 2},
        ]
    )
    assert len(segments) == 1


def test_hash_stable_et_sensible(raw_segments: list[dict]) -> None:
    first = transcript_hash(build_segments(raw_segments))
    second = transcript_hash(build_segments(raw_segments))
    assert first == second and len(first) == 64
    modified = [*raw_segments, {"text": "Un ajout.", "start": 300.0, "duration": 1.0}]
    assert transcript_hash(build_segments(modified)) != first


def test_total_duration(raw_segments: list[dict]) -> None:
    assert total_duration(build_segments(raw_segments)) == pytest.approx(268.2)


def test_format_for_model(raw_segments: list[dict]) -> None:
    rendered = format_for_model(build_segments(raw_segments))
    assert rendered.startswith("[00:00:00] Bonjour")
    assert "[00:04:18]" in rendered


def test_qualite_penalise_les_sous_titres_generes(raw_segments: list[dict]) -> None:
    segments = build_segments(raw_segments)
    assert estimate_quality(segments, auto_generated=True) < estimate_quality(
        segments, auto_generated=False
    )


# --- Récupération ----------------------------------------------------------


def test_fetch_captions_manuel(fake_captions_api: FakeApi) -> None:
    result = fetch_captions("https://youtu.be/dQw4w9WgXcQ", ["fr"], api=fake_captions_api)
    assert result.language == "fr"
    assert result.is_auto_generated is False
    assert len(result.segments) == 3

    info = result.to_transcript_info()
    assert info.source == "youtube_captions_manual"
    assert info.segment_count == 3
    assert info.segments is None  # exclus par défaut du YAML


def test_fetch_captions_inclut_les_segments_si_demande(fake_captions_api: FakeApi) -> None:
    result = fetch_captions("dQw4w9WgXcQ", ["fr"], api=fake_captions_api)
    info = result.to_transcript_info(include_segments=True)
    assert info.segments is not None and len(info.segments) == 3


def test_fetch_captions_prefere_le_manuel(raw_segments: list[dict]) -> None:
    manual = FakeTranscript(raw_segments, "fr", is_generated=False)
    generated = FakeTranscript(raw_segments, "en", is_generated=True)
    api = FakeApi(FakeTranscriptList(manual=manual, generated=generated))
    assert fetch_captions("dQw4w9WgXcQ", ["fr", "en"], api=api).language == "fr"


def test_fetch_captions_repli_sur_les_generes(raw_segments: list[dict]) -> None:
    generated = FakeTranscript(raw_segments, "fr", is_generated=True)
    api = FakeApi(FakeTranscriptList(manual=None, generated=generated))
    result = fetch_captions("dQw4w9WgXcQ", ["fr"], api=api)
    assert result.is_auto_generated is True
    assert result.to_transcript_info().source == "youtube_captions_generated"


def test_fetch_captions_url_invalide(fake_captions_api: FakeApi) -> None:
    with pytest.raises(InvalidYouTubeUrlError):
        fetch_captions("https://vimeo.com/1", ["fr"], api=fake_captions_api)


@pytest.mark.parametrize(
    ("exception_name", "expected"),
    [
        ("TranscriptsDisabled", TranscriptsDisabledError),
        ("VideoUnavailable", VideoUnavailableError),
        ("NoTranscriptFound", TranscriptNotFoundError),
        ("IpBlocked", TranscriptFetchError),
        ("UneErreurInconnue", TranscriptFetchError),
    ],
)
def test_classification_des_erreurs(exception_name: str, expected: type) -> None:
    """Les exceptions amont sont traduites en erreurs YKS typées."""
    error_type = type(exception_name, (Exception,), {})
    api = FakeApi(error=error_type("message amont"))
    with pytest.raises(expected):
        fetch_captions("dQw4w9WgXcQ", ["fr"], api=api)


def test_transcription_vide_leve_une_erreur() -> None:
    empty = FakeTranscript([], "fr", is_generated=False)
    api = FakeApi(FakeTranscriptList(manual=empty, generated=None))
    with pytest.raises(EmptyTranscriptError):
        fetch_captions("dQw4w9WgXcQ", ["fr"], api=api)
