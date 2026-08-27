"""Transcription locale d'un média **déjà en votre possession**, via faster-whisper.

Contrainte structurante : ce module ne télécharge jamais de vidéo distante. Il
n'accepte qu'un chemin local fourni explicitement par l'utilisateur avec
``--media``. C'est à l'utilisateur de disposer d'un droit d'accès au fichier.

Compromis entre les modèles (indicatif, CPU récent, audio de 10 minutes) :

===========  ==========  =====================  ========================
Modèle       RAM ~       Vitesse relative        Usage conseillé
===========  ==========  =====================  ========================
tiny         ~1 Go       très rapide            test de tuyauterie
base         ~1 Go       rapide                 premier essai
small        ~2 Go       compromis recommandé   production légère
medium       ~5 Go       lent                   qualité supérieure
large-v3     ~10 Go      très lent              qualité maximale, GPU
===========  ==========  =====================  ========================
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from ..errors import (
    MediaFileNotFoundError,
    UnsupportedMediaFormatError,
    WhisperNotInstalledError,
    WhisperResourceError,
    WhisperTranscriptionError,
)
from ..logging_setup import get_logger
from ..models import TranscriptInfo, TranscriptSegment
from .segments import (
    build_segments,
    estimate_quality,
    total_duration,
    transcript_hash,
)

logger = get_logger("whisper")

WhisperModelName = Literal["tiny", "base", "small", "medium", "large-v3"]

SUPPORTED_EXTENSIONS = {".mp3", ".wav", ".m4a", ".mp4", ".mkv", ".flac", ".ogg", ".webm"}
MAX_MEDIA_BYTES = 4 * 1024**3  # 4 Go : garde-fou contre un fichier manifestement erroné


@dataclass(frozen=True)
class WhisperResult:
    """Transcription locale normalisée."""

    segments: list[TranscriptSegment]
    language: str
    model_name: str

    def to_transcript_info(self, *, include_segments: bool = False) -> TranscriptInfo:
        """Construit le bloc ``transcript`` du document."""
        return TranscriptInfo(
            segment_count=len(self.segments),
            language=self.language,
            source="local_whisper",
            is_auto_generated=True,
            hash=transcript_hash(self.segments),
            duration_seconds=total_duration(self.segments),
            quality_score=estimate_quality(self.segments, auto_generated=True),
            segments=list(self.segments) if include_segments else None,
        )


def validate_media_path(path: str | Path) -> Path:
    """Vérifie l'existence, l'extension et la taille du fichier média.

    :raises MediaFileNotFoundError: fichier absent ou illisible.
    :raises UnsupportedMediaFormatError: extension non prise en charge ou taille aberrante.
    """
    media = Path(path).expanduser()
    if not media.exists() or not media.is_file():
        raise MediaFileNotFoundError(f"Fichier média introuvable : {media}")
    if media.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise UnsupportedMediaFormatError(
            f"Extension non supportée : {media.suffix or '(aucune)'}. "
            f"Formats acceptés : {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
        )
    size = media.stat().st_size
    if size == 0:
        raise UnsupportedMediaFormatError(f"Fichier média vide : {media}")
    if size > MAX_MEDIA_BYTES:
        raise UnsupportedMediaFormatError(
            f"Fichier média trop volumineux ({size / 1024**3:.1f} Go, limite 4 Go)"
        )
    return media


def _load_model(
    model_name: str, device: str, compute_type: str, loader: Callable[..., Any] | None
) -> Any:
    """Charge le modèle faster-whisper, ou le chargeur injecté en test."""
    if loader is not None:
        return loader(model_name, device=device, compute_type=compute_type)
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise WhisperNotInstalledError(
            "faster-whisper n'est pas installé. Installez-le avec : "
            "pip install faster-whisper",
            details=str(exc),
        ) from exc
    try:
        return WhisperModel(model_name, device=device, compute_type=compute_type)
    except (MemoryError, RuntimeError) as exc:
        raise WhisperResourceError(
            "Ressources insuffisantes pour charger le modèle Whisper. "
            "Essayez un modèle plus petit ou device='cpu'.",
            details=str(exc),
        ) from exc


def transcribe_media(
    path: str | Path,
    *,
    model_name: WhisperModelName = "small",
    language: str | None = None,
    device: str = "cpu",
    compute_type: str = "int8",
    beam_size: int = 5,
    show_progress: bool = True,
    model_loader: Callable[..., Any] | None = None,
) -> WhisperResult:
    """Transcrit un fichier local avec faster-whisper.

    ``vad_filter=True`` est imposé : il supprime les silences, ce qui réduit à la
    fois le coût de calcul et les hallucinations classiques de Whisper sur les
    passages muets.

    :param model_loader: injecté par les tests pour éviter tout téléchargement.
    """
    media = validate_media_path(path)
    logger.info("Transcription locale de %s avec le modèle %s", media.name, model_name)

    model = _load_model(model_name, device, compute_type, model_loader)

    try:
        segments_iter, info = model.transcribe(
            str(media),
            language=language,
            beam_size=beam_size,
            vad_filter=True,
        )
        raw: list[dict[str, Any]] = []
        for position, segment in enumerate(segments_iter, start=1):
            start = float(getattr(segment, "start", 0.0))
            end = float(getattr(segment, "end", start))
            raw.append(
                {
                    "text": getattr(segment, "text", ""),
                    "start": start,
                    "duration": max(0.0, end - start),
                }
            )
            if show_progress and position % 25 == 0:
                logger.info("... %d segments transcrits", position)
    except MemoryError as exc:
        raise WhisperResourceError(
            "Mémoire insuffisante pendant la transcription", details=str(exc)
        ) from exc
    except Exception as exc:
        raise WhisperTranscriptionError(
            "Échec de la transcription locale", details=f"{type(exc).__name__}: {exc}"
        ) from exc

    segments = build_segments(raw)
    detected = getattr(info, "language", None) or language or "und"
    logger.info("Transcription locale terminée : %d segments (langue=%s)", len(segments), detected)
    return WhisperResult(segments=segments, language=detected, model_name=model_name)
