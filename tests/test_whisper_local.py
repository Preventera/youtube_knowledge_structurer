"""Tests du repli Whisper local, sans téléchargement ni exécution de modèle."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from yks.errors import (
    MediaFileNotFoundError,
    UnsupportedMediaFormatError,
    WhisperResourceError,
    WhisperTranscriptionError,
)
from yks.transcription.whisper_local import (
    SUPPORTED_EXTENSIONS,
    transcribe_media,
    validate_media_path,
)


class FakeSegment:
    def __init__(self, text: str, start: float, end: float) -> None:
        self.text = text
        self.start = start
        self.end = end


class FakeInfo:
    language = "fr"


class FakeModel:
    """Modèle Whisper simulé : enregistre ses paramètres d'appel."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.kwargs: dict[str, Any] = {}

    def transcribe(self, path: str, **kwargs: Any):
        self.kwargs = kwargs
        segments = [
            FakeSegment("Bonjour à tous.", 0.0, 3.0),
            FakeSegment("Le pilote doit être mesurable.", 3.0, 7.5),
        ]
        return iter(segments), FakeInfo()


@pytest.fixture
def media_file(tmp_path: Path) -> Path:
    path = tmp_path / "extrait.mp3"
    path.write_bytes(b"\x00" * 2048)
    return path


def test_validation_fichier_absent(tmp_path: Path) -> None:
    with pytest.raises(MediaFileNotFoundError):
        validate_media_path(tmp_path / "absent.mp3")


def test_validation_extension_refusee(tmp_path: Path) -> None:
    path = tmp_path / "document.pdf"
    path.write_bytes(b"data")
    with pytest.raises(UnsupportedMediaFormatError):
        validate_media_path(path)


def test_validation_fichier_vide(tmp_path: Path) -> None:
    path = tmp_path / "vide.wav"
    path.touch()
    with pytest.raises(UnsupportedMediaFormatError):
        validate_media_path(path)


def test_extensions_supportees() -> None:
    assert {".mp3", ".wav", ".m4a", ".mp4", ".mkv"} <= SUPPORTED_EXTENSIONS


def test_transcription_locale(media_file: Path) -> None:
    holder: dict[str, FakeModel] = {}

    def loader(name: str, **kwargs: Any) -> FakeModel:
        model = FakeModel()
        holder["model"] = model
        return model

    result = transcribe_media(media_file, model_name="small", model_loader=loader)
    assert result.language == "fr"
    assert result.model_name == "small"
    assert len(result.segments) == 2
    assert result.segments[1].timestamp == "00:00:03"
    # Le filtre de détection d'activité vocale est imposé, pas optionnel.
    assert holder["model"].kwargs["vad_filter"] is True


def test_info_transcript_marque_la_source(media_file: Path) -> None:
    result = transcribe_media(media_file, model_loader=lambda *a, **k: FakeModel())
    info = result.to_transcript_info()
    assert info.source == "local_whisper"
    assert info.is_auto_generated is True
    assert len(info.hash or "") == 64


def test_erreur_memoire_traduite(media_file: Path) -> None:
    class OomModel(FakeModel):
        def transcribe(self, path: str, **kwargs: Any):
            raise MemoryError("plus de mémoire")

    with pytest.raises(WhisperResourceError):
        transcribe_media(media_file, model_loader=lambda *a, **k: OomModel())


def test_fichier_corrompu_traduit(media_file: Path) -> None:
    class BrokenModel(FakeModel):
        def transcribe(self, path: str, **kwargs: Any):
            raise RuntimeError("format audio illisible")

    with pytest.raises(WhisperTranscriptionError):
        transcribe_media(media_file, model_loader=lambda *a, **k: BrokenModel())


def test_aucun_telechargement_distant(media_file: Path) -> None:
    """Le module n'accepte qu'un chemin local : une URL est rejetée d'emblée."""
    with pytest.raises(MediaFileNotFoundError):
        transcribe_media(
            "https://example.com/video.mp4", model_loader=lambda *a, **k: FakeModel()
        )
