"""Orchestration du pipeline complet.

Cette fonction est volontairement la seule à connaître l'enchaînement complet :
ingestion, repli Whisper, analyse, assemblage, export. Chaque étape reste
testable isolément.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from .analysis.analysis_chain import (
    AnalysisTelemetry,
    StructuredRunner,
    analyze_segments,
    default_runner,
)
from .config import Settings
from .errors import (
    TRANSCRIPT_ERRORS,
    ExitCode,
    MissingApiKeyError,
    ModelInvocationError,
    StructuredOutputError,
)
from .fallback import build_unavailable_document, review_reason
from .ingestion.captions import CaptionResult, fetch_captions
from .ingestion.url import extract_video_id
from .logging_setup import get_logger
from .models import Analysis, Document, QualityRecord, TranscriptInfo, VideoInfo
from .transcription.whisper_local import WhisperResult, transcribe_media

logger = get_logger("pipeline")


@dataclass
class PipelineResult:
    """Résultat d'une exécution, qu'elle ait abouti ou non."""

    document: Document
    exit_code: int = ExitCode.OK
    output_path: Path | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def succeeded(self) -> bool:
        """Vrai si une analyse fondée sur une transcription a été produite."""
        return self.exit_code == ExitCode.OK


def _acquire_transcript(
    *,
    video_id: str,
    settings: Settings,
    media_path: str | None,
    whisper_model: str,
    whisper_language: str | None,
    whisper_device: str,
    captions_fetcher: Callable[..., CaptionResult],
    media_transcriber: Callable[..., WhisperResult],
) -> tuple[TranscriptInfo, list, str, bool, list[str], list[dict[str, str]]]:
    """Obtient une transcription selon l'arbre de décision du module ``fallback``.

    Retourne ``(info, segments, extraction_method, auto_generated, warnings, errors)``.
    Propage une erreur typée si aucune source n'aboutit.
    """
    warnings: list[str] = []
    errors: list[dict[str, str]] = []

    try:
        captions = captions_fetcher(video_id, settings.languages)
        info = captions.to_transcript_info(include_segments=settings.include_segments)
        if captions.is_auto_generated:
            warnings.append(
                "Sous-titres générés automatiquement : exactitude non garantie, "
                "notamment sur les noms propres et les chiffres."
            )
        return (
            info,
            captions.segments,
            "youtube_transcript_api",
            captions.is_auto_generated,
            warnings,
            errors,
        )
    except TRANSCRIPT_ERRORS as caption_error:
        errors.append(caption_error.as_record())
        warnings.append(f"Sous-titres YouTube indisponibles : {caption_error.code}")
        if not media_path:
            raise caption_error
        logger.info("Repli sur Whisper local avec le média fourni")

    result = media_transcriber(
        media_path,
        model_name=whisper_model,
        language=whisper_language,
        device=whisper_device,
    )
    info = result.to_transcript_info(include_segments=settings.include_segments)
    warnings.append(
        f"Transcription produite localement par Whisper ({result.model_name}) : "
        "vérifier les passages critiques avec le média source."
    )
    return info, result.segments, "local_whisper", True, warnings, errors


def _build_document(
    *,
    url: str,
    video_id: str,
    transcript_info: TranscriptInfo,
    analysis: Analysis,
    telemetry: AnalysisTelemetry,
    settings: Settings,
    extraction_method: str,
    warnings: Sequence[str],
    errors: Sequence[dict[str, str]],
    rights_note: str | None,
) -> Document:
    """Assemble le document final et impose la cohérence de la revue humaine."""
    video = VideoInfo(
        url=url,
        video_id=video_id,
        language=transcript_info.language,
        transcript_available=True,
        transcript_source=transcript_info.source,
        **({"rights_note": rights_note} if rights_note else {}),
    )
    quality = QualityRecord(
        extraction_method=extraction_method,
        analysis_method=f"langchain_structured_output:{telemetry.merge_strategy}",
        analysis_model=settings.model,
        chunk_count=telemetry.chunk_count,
        warnings=[*warnings, *telemetry.warnings],
        errors=[*errors, *telemetry.errors],
        human_review_required=analysis.human_review_required,
        review_reason=review_reason(
            analysis,
            auto_generated=transcript_info.is_auto_generated,
            failed_chunks=telemetry.failed_chunks,
        ),
        reviewed=False,
    )
    return Document(
        video=video, transcript=transcript_info, analysis=analysis, quality=quality
    )


def run_pipeline(
    url: str,
    *,
    settings: Settings | None = None,
    media_path: str | None = None,
    whisper_model: str = "small",
    whisper_language: str | None = None,
    whisper_device: str = "cpu",
    rights_note: str | None = None,
    runner: StructuredRunner | None = None,
    captions_fetcher: Callable[..., CaptionResult] = fetch_captions,
    media_transcriber: Callable[..., WhisperResult] = transcribe_media,
) -> PipelineResult:
    """Exécute le pipeline et retourne le document ainsi que le code de sortie.

    L'URL invalide est la seule erreur qui empêche de produire un document :
    sans identifiant de vidéo, il n'y a rien à tracer. Toutes les autres erreurs
    de source donnent un document d'état exploitable.
    """
    active = settings or Settings.from_env()
    video_id = extract_video_id(url)  # InvalidYouTubeUrlError propagée telle quelle

    try:
        (
            transcript_info,
            segments,
            extraction_method,
            auto_generated,
            warnings,
            errors,
        ) = _acquire_transcript(
            video_id=video_id,
            settings=active,
            media_path=media_path,
            whisper_model=whisper_model,
            whisper_language=whisper_language,
            whisper_device=whisper_device,
            captions_fetcher=captions_fetcher,
            media_transcriber=media_transcriber,
        )
    except TRANSCRIPT_ERRORS as exc:
        logger.warning("Aucune transcription exploitable : %s", exc.code)
        document = build_unavailable_document(url=url, video_id=video_id, error=exc)
        return PipelineResult(
            document=document, exit_code=exc.exit_code, warnings=[exc.message]
        )

    active_runner = runner or default_runner(active)

    try:
        analysis, telemetry = analyze_segments(
            segments,
            runner=active_runner,
            settings=active,
            language=transcript_info.language or "und",
            source=transcript_info.source,
            is_auto_generated=auto_generated,
        )
    except (MissingApiKeyError, ModelInvocationError, StructuredOutputError) as exc:
        logger.error("Analyse impossible : %s", exc.code)
        document = build_unavailable_document(
            url=url,
            video_id=video_id,
            error=exc,
            warnings=[
                *warnings,
                "Une transcription a été obtenue mais n'a pas pu être analysée : "
                "aucune conclusion n'est produite.",
            ],
            extra_errors=errors,
        )
        return PipelineResult(
            document=document, exit_code=exc.exit_code, warnings=[exc.message]
        )

    document = _build_document(
        url=url,
        video_id=video_id,
        transcript_info=transcript_info,
        analysis=analysis,
        telemetry=telemetry,
        settings=active,
        extraction_method=extraction_method,
        warnings=warnings,
        errors=errors,
        rights_note=rights_note,
    )
    exit_code = ExitCode.OK if not telemetry.failed_chunks else ExitCode.MODEL_ERROR
    return PipelineResult(document=document, exit_code=exit_code, warnings=list(warnings))
