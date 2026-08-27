"""Récupération des sous-titres YouTube rendus accessibles par la plateforme.

Le module n'utilise que ce que YouTube expose déjà : il ne contourne aucune
protection, ne télécharge aucun média et n'accède pas aux vidéos privées. Si les
sous-titres sont désactivés ou absents, il lève une erreur explicite plutôt que
de chercher une voie détournée.

La dépendance ``youtube-transcript-api`` s'appuie sur une partie non documentée
de l'interface de YouTube : son comportement peut changer et certaines adresses
IP (notamment infonuagiques) peuvent être bloquées. Les erreurs correspondantes
sont donc traitées comme des erreurs d'exécution normales, pas comme des bogues.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from ..errors import (
    EmptyTranscriptError,
    TranscriptFetchError,
    TranscriptNotFoundError,
    TranscriptsDisabledError,
    VideoUnavailableError,
)
from ..logging_setup import get_logger
from ..models import TranscriptInfo, TranscriptSegment, TranscriptSource
from ..transcription.segments import (
    build_segments,
    estimate_quality,
    total_duration,
    transcript_hash,
)
from .url import extract_video_id

logger = get_logger("captions")


@dataclass(frozen=True)
class CaptionResult:
    """Sous-titres normalisés et leurs métadonnées de traçabilité."""

    segments: list[TranscriptSegment]
    language: str
    is_auto_generated: bool

    def to_transcript_info(self, *, include_segments: bool = False) -> TranscriptInfo:
        """Construit le bloc ``transcript`` du document."""
        source: TranscriptSource = (
            "youtube_captions_generated"
            if self.is_auto_generated
            else "youtube_captions_manual"
        )
        return TranscriptInfo(
            segment_count=len(self.segments),
            language=self.language,
            source=source,
            is_auto_generated=self.is_auto_generated,
            hash=transcript_hash(self.segments),
            duration_seconds=total_duration(self.segments),
            quality_score=estimate_quality(
                self.segments, auto_generated=self.is_auto_generated
            ),
            segments=list(self.segments) if include_segments else None,
        )


class TranscriptApiProtocol(Protocol):
    """Interface minimale attendue, pour permettre l'injection d'un faux en test."""

    def list(self, video_id: str) -> Any:  # pragma: no cover - protocole
        ...


def _default_api() -> TranscriptApiProtocol:
    """Instancie le client réel ; importé tardivement pour garder les tests hors ligne."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError as exc:  # pragma: no cover - dépend de l'environnement
        raise TranscriptFetchError(
            "La bibliothèque youtube-transcript-api n'est pas installée",
            details=str(exc),
        ) from exc
    return YouTubeTranscriptApi()


def _classify(exc: Exception) -> Exception:
    """Traduit une exception de la bibliothèque en exception YKS typée.

    La correspondance se fait sur le nom de la classe afin de rester valable
    malgré les réorganisations de modules en amont.
    """
    name = type(exc).__name__
    message = str(exc).strip() or name
    if name in {"TranscriptsDisabled"}:
        return TranscriptsDisabledError(
            "Les sous-titres sont désactivés pour cette vidéo", details=message
        )
    if name in {"VideoUnavailable", "VideoUnplayable", "AgeRestricted"}:
        return VideoUnavailableError(
            "La vidéo est indisponible ou d'accès restreint", details=message
        )
    if name in {"NoTranscriptFound", "NoTranscriptAvailable", "TranslationLanguageNotAvailable"}:
        return TranscriptNotFoundError(
            "Aucune piste de sous-titres ne correspond aux langues demandées",
            details=message,
        )
    if name in {"IpBlocked", "RequestBlocked", "YouTubeRequestFailed", "CouldNotRetrieveTranscript"}:
        return TranscriptFetchError(
            "YouTube a refusé la requête (blocage ou limitation)", details=message
        )
    return TranscriptFetchError(
        "Erreur inattendue lors de la récupération des sous-titres",
        details=f"{name}: {message}",
    )


def _select_transcript(transcript_list: Any, languages: Sequence[str]) -> Any:
    """Choisit une piste : d'abord manuelle, puis générée automatiquement.

    Les sous-titres manuels sont préférés parce qu'ils sont ponctués et
    généralement plus fidèles, ce qui améliore la traçabilité des citations.
    """
    ordered = list(languages)
    for finder in ("find_manually_created_transcript", "find_generated_transcript"):
        method = getattr(transcript_list, finder, None)
        if method is None:
            continue
        try:
            return method(ordered)
        except Exception:
            continue
    return transcript_list.find_transcript(ordered)


def _raw_data(fetched: Any) -> list[dict[str, Any]]:
    """Extrait la liste de dictionnaires, quelle que soit la version de l'API."""
    if hasattr(fetched, "to_raw_data"):
        return list(fetched.to_raw_data())
    if isinstance(fetched, list):
        return list(fetched)
    raise TranscriptFetchError(
        "Format de transcription non reconnu",
        details=f"type={type(fetched).__name__}",
    )


def fetch_captions(
    url_or_id: str,
    languages: Sequence[str] = ("fr", "fr-CA", "en"),
    *,
    api: TranscriptApiProtocol | None = None,
) -> CaptionResult:
    """Récupère les sous-titres accessibles d'une vidéo.

    :param url_or_id: URL YouTube ou identifiant.
    :param languages: langues par ordre de préférence, le français d'abord.
    :param api: client injectable ; ``None`` instancie le client réel.
    :raises InvalidYouTubeUrlError, TranscriptsDisabledError,
        VideoUnavailableError, TranscriptNotFoundError, TranscriptFetchError,
        EmptyTranscriptError:
    """
    video_id = extract_video_id(url_or_id)
    client = api or _default_api()
    logger.info("Recherche de sous-titres pour %s (langues=%s)", video_id, list(languages))

    try:
        transcript_list = client.list(video_id)
        transcript = _select_transcript(transcript_list, languages)
        fetched = transcript.fetch()
    except Exception as exc:
        raise _classify(exc) from exc

    segments = build_segments(_raw_data(fetched))
    language = getattr(transcript, "language_code", None) or (
        languages[0] if languages else "und"
    )
    is_generated = bool(getattr(transcript, "is_generated", False))
    logger.info(
        "Sous-titres obtenus : %d segments, langue=%s, generes=%s",
        len(segments),
        language,
        is_generated,
    )
    return CaptionResult(
        segments=segments, language=language, is_auto_generated=is_generated
    )


__all__ = [
    "CaptionResult",
    "EmptyTranscriptError",
    "fetch_captions",
]
