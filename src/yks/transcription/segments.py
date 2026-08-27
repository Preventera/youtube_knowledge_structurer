"""Normalisation des segments de transcription.

Toute source (sous-titres YouTube, Whisper local, fichier fourni) est ramenée à
la même structure ``TranscriptSegment``. L'étape d'analyse ne dépend donc jamais
de la manière dont le texte a été obtenu.
"""

from __future__ import annotations

import hashlib
import html
import re
from collections.abc import Iterable, Sequence
from typing import Any

from ..errors import EmptyTranscriptError
from ..models import TranscriptSegment, seconds_to_timestamp

_TAG_RE = re.compile(r"<[^>]+>")
_BRACKET_NOISE_RE = re.compile(r"\[(musique|music|applaudissements|applause|rires|laughter)\]", re.I)
_WHITESPACE_RE = re.compile(r"\s+")


def normalize_text(text: str) -> str:
    """Retire les balises, décode les entités HTML et normalise les espaces."""
    if not text:
        return ""
    cleaned = _TAG_RE.sub(" ", text)
    cleaned = html.unescape(cleaned)
    cleaned = cleaned.replace("\u00a0", " ").replace("\u200b", "")
    cleaned = _WHITESPACE_RE.sub(" ", cleaned)
    return cleaned.strip()


def is_noise(text: str) -> bool:
    """Vrai si le segment ne contient que des annotations non verbales."""
    stripped = _BRACKET_NOISE_RE.sub("", text).strip()
    return not stripped


def build_segments(raw: Iterable[dict[str, Any]]) -> list[TranscriptSegment]:
    """Construit des segments validés à partir d'entrées brutes.

    Chaque entrée doit exposer ``text``, ``start`` et ``duration``. Les segments
    vides ou purement sonores sont écartés ; aucun texte n'est ajouté.

    :raises EmptyTranscriptError: si aucun segment exploitable ne subsiste.
    """
    segments: list[TranscriptSegment] = []
    index = 0
    for item in raw:
        text = normalize_text(str(item.get("text", "")))
        if not text or is_noise(text):
            continue
        try:
            start = float(item.get("start", 0.0) or 0.0)
            duration = float(item.get("duration", 0.0) or 0.0)
        except (TypeError, ValueError):
            continue
        segments.append(
            TranscriptSegment(
                index=index,
                text=text,
                start=max(0.0, start),
                duration=max(0.0, duration),
                timestamp=seconds_to_timestamp(start),
            )
        )
        index += 1

    if not segments:
        raise EmptyTranscriptError(
            "La transcription récupérée ne contient aucun texte exploitable"
        )
    return segments


def transcript_text(segments: Sequence[TranscriptSegment]) -> str:
    """Concatène le texte des segments, sans horodatage."""
    return " ".join(segment.text for segment in segments)


def transcript_hash(segments: Sequence[TranscriptSegment]) -> str:
    """SHA-256 du texte concaténé, stable entre deux exécutions identiques."""
    digest = hashlib.sha256()
    digest.update(transcript_text(segments).encode("utf-8"))
    return digest.hexdigest()


def total_duration(segments: Sequence[TranscriptSegment]) -> float:
    """Durée couverte par les segments, en secondes."""
    if not segments:
        return 0.0
    last = segments[-1]
    return round(last.start + last.duration, 3)


def format_for_model(segments: Sequence[TranscriptSegment]) -> str:
    """Rend les segments sous forme ``[HH:MM:SS] texte`` pour le modèle d'IA."""
    return "\n".join(f"[{s.timestamp}] {s.text}" for s in segments)


def estimate_quality(segments: Sequence[TranscriptSegment], *, auto_generated: bool) -> float:
    """Estime grossièrement la qualité d'une transcription entre 0 et 1.

    Heuristique volontairement conservatrice : les sous-titres générés
    automatiquement sont pénalisés, tout comme l'absence de ponctuation, qui
    complique le repérage des frontières de phrases.
    """
    if not segments:
        return 0.0
    text = transcript_text(segments)
    score = 0.9 if not auto_generated else 0.65
    punctuation_ratio = sum(text.count(c) for c in ".!?") / max(1, len(text.split()))
    if punctuation_ratio < 0.01:
        score -= 0.15
    if len(text.split()) < 50:
        score -= 0.1
    return round(max(0.0, min(1.0, score)), 2)
