"""Tests des modèles Pydantic : contraintes, normalisation, invariants."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from tests.conftest import make_analysis
from yks.errors import TranscriptsDisabledError
from yks.fallback import build_unavailable_document, empty_transcript_info, unavailable_analysis
from yks.models import (
    Analysis,
    Document,
    KeyPoint,
    QualityRecord,
    TranscriptInfo,
    VideoInfo,
    normalize_timestamp,
    seconds_to_timestamp,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("00:04:18", "00:04:18"),
        ("0:4:18", "00:04:18"),
        ("4:18", "00:04:18"),
        ("1:02:03", "01:02:03"),
        (258, "00:04:18"),
        (258.9, "00:04:18"),
        (None, None),
        ("", None),
        ("null", None),
    ],
)
def test_normalisation_horodatage(value: object, expected: str | None) -> None:
    assert normalize_timestamp(value) == expected


@pytest.mark.parametrize("value", ["hier", "12:99:00", "abc:def", "00:00:99"])
def test_horodatage_invalide(value: str) -> None:
    with pytest.raises(ValueError):
        normalize_timestamp(value)


def test_seconds_to_timestamp() -> None:
    assert seconds_to_timestamp(0) == "00:00:00"
    assert seconds_to_timestamp(3661) == "01:01:01"
    assert seconds_to_timestamp(-5) == "00:00:00"


def test_key_point_normalise_horodatage() -> None:
    point = KeyPoint(id="KP-001", statement="Un point clé.", timestamp="4:18", confidence=0.9)
    assert point.timestamp == "00:04:18"


def test_key_point_identifiant_invalide() -> None:
    with pytest.raises(ValidationError):
        KeyPoint(id="POINT1", statement="Un point clé.", confidence=0.9)


@pytest.mark.parametrize("score", [-0.1, 1.1, 2.0])
def test_confiance_hors_bornes(score: float) -> None:
    with pytest.raises(ValidationError):
        KeyPoint(id="KP-001", statement="Un point clé.", confidence=score)


def test_champ_inattendu_refuse() -> None:
    with pytest.raises(ValidationError):
        KeyPoint(
            id="KP-001",
            statement="Un point clé.",
            confidence=0.9,
            champ_invente="valeur",  # type: ignore[call-arg]
        )


def test_domaine_sensible_force_la_revue() -> None:
    analysis = make_analysis(sensitive=["sst"])
    assert analysis.human_review_required is True


def test_confiance_faible_force_la_revue() -> None:
    analysis = make_analysis(confidence=0.3)
    assert analysis.human_review_required is True


def test_donnees_personnelles_forcent_la_revue() -> None:
    analysis = make_analysis(personal=True)
    assert analysis.human_review_required is True


def test_video_info_incoherente() -> None:
    with pytest.raises(ValidationError):
        VideoInfo(
            url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            video_id="dQw4w9WgXcQ",
            transcript_available=True,
            transcript_source="unavailable",
        )


def test_video_info_sans_transcription_impose_unavailable() -> None:
    with pytest.raises(ValidationError):
        VideoInfo(
            url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            video_id="dQw4w9WgXcQ",
            transcript_available=False,
            transcript_source="youtube_captions_manual",
        )


def test_document_refuse_analyse_sans_transcription() -> None:
    """Sans transcription, une analyse non vide doit être rejetée."""
    with pytest.raises(ValidationError):
        Document(
            video=VideoInfo(
                url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                video_id="dQw4w9WgXcQ",
                transcript_available=False,
                transcript_source="unavailable",
            ),
            transcript=empty_transcript_info(),
            analysis=make_analysis(),
            quality=QualityRecord(extraction_method="failed"),
        )


def test_document_etat_valide() -> None:
    document = build_unavailable_document(
        url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        video_id="dQw4w9WgXcQ",
        error=TranscriptsDisabledError("Sous-titres désactivés"),
    )
    assert document.video.transcript_available is False
    assert document.analysis.confidence == 0.0
    assert document.analysis.key_points == []
    assert document.quality.human_review_required is True
    assert document.quality.errors[0]["code"] == "transcripts_disabled"


def test_analyse_indisponible_ne_resume_pas_le_contenu() -> None:
    analysis = unavailable_analysis("Sous-titres désactivés")
    assert analysis.topics == []
    assert analysis.confidence == 0.0
    assert "impossible" in analysis.short_summary.lower()


def test_hash_invalide_refuse() -> None:
    with pytest.raises(ValidationError):
        TranscriptInfo(segment_count=1, source="local_whisper", hash="pas-un-hash")


def test_schema_json_exportable() -> None:
    schema = Document.model_json_schema()
    assert schema["title"] == "Document"
    assert "video" in schema["properties"]


def test_round_trip_model_dump(analysis: Analysis) -> None:
    data = analysis.model_dump(mode="json")
    assert Analysis.model_validate(data) == analysis
