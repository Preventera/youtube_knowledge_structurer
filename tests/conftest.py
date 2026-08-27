"""Fixtures et doublures de test.

Aucun test unitaire n'effectue d'appel réseau, ne télécharge de modèle Whisper
ni ne consomme de clé d'API : toutes les frontières externes sont injectées.
"""

from __future__ import annotations

import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from yks.analysis.analysis_chain import StructuredRunner
from yks.models import Analysis, KeyPoint, Risk


class FakeTranscript:
    """Imite une piste de sous-titres de youtube-transcript-api."""

    def __init__(self, raw: list[dict[str, Any]], language_code: str, is_generated: bool):
        self._raw = raw
        self.language_code = language_code
        self.is_generated = is_generated

    def fetch(self) -> FakeFetched:
        return FakeFetched(self._raw)


class FakeFetched:
    def __init__(self, raw: list[dict[str, Any]]):
        self._raw = raw

    def to_raw_data(self) -> list[dict[str, Any]]:
        return list(self._raw)


class FakeTranscriptList:
    """Imite l'objet retourné par ``YouTubeTranscriptApi.list``."""

    def __init__(self, manual: FakeTranscript | None, generated: FakeTranscript | None):
        self._manual = manual
        self._generated = generated

    def find_manually_created_transcript(self, languages: Iterable[str]) -> FakeTranscript:
        if self._manual is None:
            raise LookupError("Aucun sous-titre manuel")
        return self._manual

    def find_generated_transcript(self, languages: Iterable[str]) -> FakeTranscript:
        if self._generated is None:
            raise LookupError("Aucun sous-titre généré")
        return self._generated

    def find_transcript(self, languages: Iterable[str]) -> FakeTranscript:
        found = self._manual or self._generated
        if found is None:
            raise LookupError("Aucun sous-titre")
        return found


class FakeApi:
    """Client injectable remplaçant YouTubeTranscriptApi."""

    def __init__(self, transcript_list: Any = None, error: Exception | None = None):
        self._transcript_list = transcript_list
        self._error = error

    def list(self, video_id: str) -> Any:
        if self._error is not None:
            raise self._error
        return self._transcript_list


class FakeRunner(StructuredRunner):
    """Faux fournisseur d'IA retournant des analyses prédéfinies."""

    def __init__(self, responses: list[Analysis] | None = None, error: Exception | None = None):
        self.responses = list(responses or [])
        self.error = error
        self.calls: list[tuple[str, str]] = []

    def run(self, system: str, human: str) -> Analysis:
        self.calls.append((system, human))
        if self.error is not None:
            raise self.error
        if not self.responses:
            return make_analysis()
        return self.responses.pop(0)


def make_analysis(
    *,
    summary: str = "La vidéo présente une méthode de déploiement progressif.",
    statement: str = "Un projet pilote doit avoir des indicateurs de succès définis.",
    timestamp: str | None = "00:04:18",
    confidence: float = 0.9,
    sensitive: list[str] | None = None,
    personal: bool = False,
) -> Analysis:
    """Construit une analyse valide, paramétrable pour les tests."""
    return Analysis(
        short_summary=summary,
        detailed_summary=["Définir le problème avant de choisir la technologie."],
        topics=["intelligence artificielle", "gouvernance des données"],
        key_points=[
            KeyPoint(
                id="KP-001",
                statement=statement,
                timestamp=timestamp,
                evidence="il faut commencer par un pilote mesurable",
                confidence=confidence,
            )
        ],
        recommendations=[],
        risks=[
            Risk(
                description="La transcription automatique peut contenir des erreurs.",
                severity="medium",
                mitigation="Valider les passages importants avec la vidéo.",
                confidence=0.8,
            )
        ],
        people=[],
        organizations=[],
        technologies=["Python"],
        unanswered_questions=[],
        claims=[],
        contains_personal_data=personal,
        sensitive_domains=sensitive or [],
        confidence=confidence,
        human_review_required=False,
    )


@pytest.fixture
def analysis() -> Analysis:
    return make_analysis()


@pytest.fixture
def raw_segments() -> list[dict[str, Any]]:
    return [
        {"text": "Bonjour et <i>bienvenue</i> dans cette présentation.", "start": 0.0, "duration": 3.5},
        {"text": "[Musique]", "start": 3.5, "duration": 2.0},
        {"text": "Il faut commencer par un pilote mesurable.", "start": 258.0, "duration": 4.2},
        {"text": "   ", "start": 262.2, "duration": 1.0},
        {"text": "La gouvernance des données reste essentielle.", "start": 263.2, "duration": 5.0},
    ]


@pytest.fixture
def fake_captions_api(raw_segments: list[dict[str, Any]]) -> FakeApi:
    manual = FakeTranscript(raw_segments, "fr", is_generated=False)
    return FakeApi(FakeTranscriptList(manual=manual, generated=None))
