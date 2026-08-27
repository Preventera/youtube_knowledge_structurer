"""Transcription : normalisation des segments et repli Whisper local."""

from .segments import build_segments, normalize_text, transcript_hash
from .whisper_local import WhisperResult, transcribe_media, validate_media_path

__all__ = [
    "WhisperResult",
    "build_segments",
    "normalize_text",
    "transcribe_media",
    "transcript_hash",
    "validate_media_path",
]
