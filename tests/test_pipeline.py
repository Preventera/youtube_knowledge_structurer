"""Tests d'intégration du pipeline avec un faux fournisseur d'IA."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tests.conftest import FakeRunner, make_analysis
from yks.cli import main
from yks.config import Settings
from yks.errors import (
    ExitCode,
    InvalidYouTubeUrlError,
    MissingApiKeyError,
    TranscriptsDisabledError,
    VideoUnavailableError,
)
from yks.export.export_yaml import load_validated_yaml
from yks.ingestion.captions import CaptionResult
from yks.models import TranscriptSegment
from yks.pipeline import run_pipeline
from yks.transcription.whisper_local import WhisperResult

URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


def _segments() -> list[TranscriptSegment]:
    return [
        TranscriptSegment(
            index=0, text="Bonjour à tous.", start=0.0, duration=3.0, timestamp="00:00:00"
        ),
        TranscriptSegment(
            index=1,
            text="Il faut commencer par un pilote mesurable.",
            start=258.0,
            duration=4.0,
            timestamp="00:04:18",
        ),
    ]


def captions_ok(auto: bool = False):
    def fetcher(url_or_id: str, languages: Any) -> CaptionResult:
        return CaptionResult(segments=_segments(), language="fr", is_auto_generated=auto)

    return fetcher


def captions_error(exc: Exception):
    def fetcher(url_or_id: str, languages: Any) -> CaptionResult:
        raise exc

    return fetcher


def whisper_ok(url_or_id: str, **kwargs: Any) -> WhisperResult:
    return WhisperResult(segments=_segments(), language="fr", model_name="small")


def whisper_unused(*args: Any, **kwargs: Any) -> WhisperResult:
    raise AssertionError("Whisper ne doit pas être appelé ici")


# --- Chemin nominal --------------------------------------------------------


def test_pipeline_nominal() -> None:
    result = run_pipeline(
        URL,
        settings=Settings(),
        runner=FakeRunner([make_analysis()]),
        captions_fetcher=captions_ok(),
        media_transcriber=whisper_unused,
    )
    assert result.succeeded
    document = result.document
    assert document.video.transcript_source == "youtube_captions_manual"
    assert document.transcript.segment_count == 2
    assert document.analysis.key_points[0].timestamp == "00:04:18"
    assert document.quality.analysis_model == Settings().model
    assert document.quality.errors == []


def test_sous_titres_generes_signales_et_revue_exigee() -> None:
    result = run_pipeline(
        URL,
        settings=Settings(),
        runner=FakeRunner([make_analysis()]),
        captions_fetcher=captions_ok(auto=True),
        media_transcriber=whisper_unused,
    )
    document = result.document
    assert document.video.transcript_source == "youtube_captions_generated"
    assert document.transcript.is_auto_generated is True
    assert any("automatiquement" in w for w in document.quality.warnings)
    assert "générée automatiquement" in (document.quality.review_reason or "")


def test_contenu_sensible_force_la_revue() -> None:
    result = run_pipeline(
        URL,
        settings=Settings(),
        runner=FakeRunner([make_analysis(sensitive=["sst"], personal=True)]),
        captions_fetcher=captions_ok(),
        media_transcriber=whisper_unused,
    )
    quality = result.document.quality
    assert quality.human_review_required is True
    assert "sst" in (quality.review_reason or "")
    assert "renseignements personnels" in (quality.review_reason or "")


def test_note_de_droits_personnalisee() -> None:
    result = run_pipeline(
        URL,
        settings=Settings(),
        runner=FakeRunner([make_analysis()]),
        captions_fetcher=captions_ok(),
        media_transcriber=whisper_unused,
        rights_note="Vidéo de notre organisation, usage interne autorisé.",
    )
    assert "usage interne" in result.document.video.rights_note


# --- Repli Whisper ---------------------------------------------------------


def test_repli_whisper_quand_media_fourni() -> None:
    result = run_pipeline(
        URL,
        settings=Settings(),
        media_path="/chemin/extrait.mp3",
        runner=FakeRunner([make_analysis()]),
        captions_fetcher=captions_error(TranscriptsDisabledError("Sous-titres désactivés")),
        media_transcriber=whisper_ok,
    )
    assert result.succeeded
    document = result.document
    assert document.video.transcript_source == "local_whisper"
    assert document.quality.extraction_method == "local_whisper"
    # L'échec des sous-titres reste tracé, même après un repli réussi.
    assert document.quality.errors[0]["code"] == "transcripts_disabled"


def test_pas_de_whisper_sans_media() -> None:
    result = run_pipeline(
        URL,
        settings=Settings(),
        runner=FakeRunner([make_analysis()]),
        captions_fetcher=captions_error(TranscriptsDisabledError("Sous-titres désactivés")),
        media_transcriber=whisper_unused,
    )
    assert result.exit_code == ExitCode.TRANSCRIPTS_DISABLED
    document = result.document
    assert document.video.transcript_available is False
    assert document.analysis.confidence == 0.0
    assert document.analysis.key_points == []
    assert document.analysis.topics == []


def test_video_indisponible_produit_un_document_etat() -> None:
    result = run_pipeline(
        URL,
        settings=Settings(),
        runner=FakeRunner([make_analysis()]),
        captions_fetcher=captions_error(VideoUnavailableError("Vidéo privée")),
        media_transcriber=whisper_unused,
    )
    assert result.exit_code == ExitCode.VIDEO_UNAVAILABLE
    assert result.document.quality.extraction_method == "failed"
    assert result.document.quality.analysis_method == "not_executed"


def test_url_invalide_propage_l_erreur() -> None:
    with pytest.raises(InvalidYouTubeUrlError):
        run_pipeline("https://vimeo.com/1", settings=Settings())


def test_modele_indisponible_ne_produit_aucune_conclusion() -> None:
    """Une transcription obtenue mais non analysable ne doit pas donner de résumé."""
    result = run_pipeline(
        URL,
        settings=Settings(),
        runner=FakeRunner(error=MissingApiKeyError("clé absente")),
        captions_fetcher=captions_ok(),
        media_transcriber=whisper_unused,
    )
    assert result.exit_code == ExitCode.MISSING_API_KEY
    assert result.document.analysis.topics == []
    assert result.document.analysis.confidence == 0.0


# --- Idempotence et export -------------------------------------------------


def test_execution_idempotente_du_hash() -> None:
    from yks.transcription.segments import transcript_hash

    assert transcript_hash(_segments()) == transcript_hash(_segments())


def test_cli_ecrit_un_yaml_valide(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    output = tmp_path / "resultat.yaml"

    def fake_run(url: str, **kwargs: Any):
        return run_pipeline(
            url,
            settings=kwargs.get("settings"),
            runner=FakeRunner([make_analysis()]),
            captions_fetcher=captions_ok(),
            media_transcriber=whisper_unused,
        )

    monkeypatch.setattr("yks.cli.run_pipeline", fake_run)
    code = main([URL, "-o", str(output)])
    assert code == ExitCode.OK
    document = load_validated_yaml(output)
    assert document.video.video_id == "dQw4w9WgXcQ"


def test_cli_refuse_d_ecraser(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    output = tmp_path / "resultat.yaml"
    output.write_text("ancien contenu", encoding="utf-8")

    def fake_run(url: str, **kwargs: Any):
        return run_pipeline(
            url,
            settings=kwargs.get("settings"),
            runner=FakeRunner([make_analysis()]),
            captions_fetcher=captions_ok(),
            media_transcriber=whisper_unused,
        )

    monkeypatch.setattr("yks.cli.run_pipeline", fake_run)
    assert main([URL, "-o", str(output)]) == ExitCode.OUTPUT_EXISTS
    assert output.read_text(encoding="utf-8") == "ancien contenu"
    assert main([URL, "-o", str(output), "--force"]) == ExitCode.OK


def test_cli_url_invalide() -> None:
    assert main(["https://vimeo.com/1", "-o", "/tmp/inutilise.yaml"]) == ExitCode.INVALID_URL


def test_cli_affiche_le_schema(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--print-schema", "document"]) == ExitCode.OK
    assert "Document" in capsys.readouterr().out
