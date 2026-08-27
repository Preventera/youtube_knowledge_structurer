"""Hiérarchie d'exceptions et codes de sortie du pipeline YKS.

Chaque exception porte son propre code de sortie CLI, ce qui permet à un
ordonnanceur (cron, Power Automate, GitHub Actions) de distinguer une erreur
d'entrée d'une erreur d'infrastructure sans analyser la sortie texte.
"""

from __future__ import annotations


class ExitCode:
    """Codes de sortie du programme.

    0 est réservé au succès complet. Les codes 2-9 concernent la source,
    10-19 les médias locaux, 20-29 le modèle d'IA, 30-39 la sortie.
    """

    OK = 0
    UNEXPECTED = 1
    INVALID_URL = 2
    VIDEO_UNAVAILABLE = 3
    TRANSCRIPTS_DISABLED = 4
    TRANSCRIPT_NOT_FOUND = 5
    EMPTY_TRANSCRIPT = 6
    TRANSCRIPT_FETCH_ERROR = 7
    MEDIA_NOT_FOUND = 10
    MEDIA_FORMAT_INVALID = 11
    WHISPER_NOT_INSTALLED = 12
    WHISPER_ERROR = 13
    WHISPER_RESOURCE_ERROR = 14
    MISSING_API_KEY = 20
    MODEL_ERROR = 21
    STRUCTURED_OUTPUT_ERROR = 22
    YAML_INVALID = 30
    YAML_WRITE_ERROR = 31
    OUTPUT_EXISTS = 32


class YKSError(Exception):
    """Exception de base du projet."""

    exit_code: int = ExitCode.UNEXPECTED
    #: Libellé court réutilisé dans quality.errors du document YAML.
    code: str = "unexpected_error"

    def __init__(self, message: str, *, details: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details

    def as_record(self) -> dict[str, str]:
        """Représentation sérialisable pour le champ quality.errors."""
        record = {"code": self.code, "message": self.message}
        if self.details:
            record["details"] = self.details
        return record


# --- Ingestion -------------------------------------------------------------


class InvalidYouTubeUrlError(YKSError):
    exit_code = ExitCode.INVALID_URL
    code = "invalid_youtube_url"


class VideoUnavailableError(YKSError):
    exit_code = ExitCode.VIDEO_UNAVAILABLE
    code = "video_unavailable"


class TranscriptsDisabledError(YKSError):
    exit_code = ExitCode.TRANSCRIPTS_DISABLED
    code = "transcripts_disabled"


class TranscriptNotFoundError(YKSError):
    exit_code = ExitCode.TRANSCRIPT_NOT_FOUND
    code = "transcript_not_found"


class EmptyTranscriptError(YKSError):
    exit_code = ExitCode.EMPTY_TRANSCRIPT
    code = "empty_transcript"


class TranscriptFetchError(YKSError):
    """Erreur réseau, blocage d'adresse IP ou changement de format en amont."""

    exit_code = ExitCode.TRANSCRIPT_FETCH_ERROR
    code = "transcript_fetch_error"


# --- Média local / Whisper -------------------------------------------------


class MediaFileNotFoundError(YKSError):
    exit_code = ExitCode.MEDIA_NOT_FOUND
    code = "media_not_found"


class UnsupportedMediaFormatError(YKSError):
    exit_code = ExitCode.MEDIA_FORMAT_INVALID
    code = "media_format_invalid"


class WhisperNotInstalledError(YKSError):
    exit_code = ExitCode.WHISPER_NOT_INSTALLED
    code = "whisper_not_installed"


class WhisperResourceError(YKSError):
    """Mémoire insuffisante, GPU indisponible, type de calcul non supporté."""

    exit_code = ExitCode.WHISPER_RESOURCE_ERROR
    code = "whisper_resource_error"


class WhisperTranscriptionError(YKSError):
    exit_code = ExitCode.WHISPER_ERROR
    code = "whisper_error"


# --- Modèle d'IA -----------------------------------------------------------


class MissingApiKeyError(YKSError):
    exit_code = ExitCode.MISSING_API_KEY
    code = "missing_api_key"


class ModelInvocationError(YKSError):
    exit_code = ExitCode.MODEL_ERROR
    code = "model_error"


class StructuredOutputError(YKSError):
    """Le modèle a répondu, mais la sortie ne respecte pas le schéma."""

    exit_code = ExitCode.STRUCTURED_OUTPUT_ERROR
    code = "structured_output_error"


# --- Export ----------------------------------------------------------------


class YamlValidationError(YKSError):
    exit_code = ExitCode.YAML_INVALID
    code = "yaml_invalid"


class YamlWriteError(YKSError):
    exit_code = ExitCode.YAML_WRITE_ERROR
    code = "yaml_write_error"


class OutputExistsError(YKSError):
    exit_code = ExitCode.OUTPUT_EXISTS
    code = "output_exists"


#: Erreurs qui n'empêchent pas de produire un document YAML d'état.
TRANSCRIPT_ERRORS = (
    VideoUnavailableError,
    TranscriptsDisabledError,
    TranscriptNotFoundError,
    EmptyTranscriptError,
    TranscriptFetchError,
    MediaFileNotFoundError,
    UnsupportedMediaFormatError,
    WhisperNotInstalledError,
    WhisperResourceError,
    WhisperTranscriptionError,
)
