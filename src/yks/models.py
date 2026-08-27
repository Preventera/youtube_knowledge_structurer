"""Modèles Pydantic v2 du document produit par YKS.

Principes de conception :

- ``extra="forbid"`` partout : un champ inventé par le modèle d'IA fait échouer
  la validation au lieu de se retrouver silencieusement dans le YAML.
- Aucune valeur par défaut trompeuse : une information réellement absente est
  ``None`` ou une liste vide, jamais une chaîne de remplissage.
- Tous les scores sont contraints entre 0 et 1.
- Les horodatages sont normalisés au format ``HH:MM:SS``.
- ``Analysis`` est le seul modèle demandé au modèle d'IA ; les autres blocs sont
  remplis par le programme, ce qui empêche l'IA de falsifier la traçabilité.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

SCHEMA_VERSION = "1.0"

#: Score de confiance normalisé.
Confidence = Annotated[float, Field(ge=0.0, le=1.0)]

TranscriptSource = Literal[
    "youtube_captions_manual",
    "youtube_captions_generated",
    "local_whisper",
    "user_provided",
    "unavailable",
]

Severity = Literal["low", "medium", "high"]
Priority = Literal["low", "medium", "high"]

_TIMESTAMP_RE = re.compile(r"^\d{1,3}:[0-5]\d:[0-5]\d$")
_LOOSE_TIMESTAMP_RE = re.compile(r"^(?:(\d{1,3}):)?(\d{1,3}):(\d{1,2})$")
_VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{6,32}$")


def normalize_timestamp(value: object) -> str | None:
    """Normalise un horodatage vers ``HH:MM:SS``.

    Accepte ``4:18``, ``00:4:18`` ou ``00:04:18``. Retourne ``None`` pour une
    valeur vide : un horodatage non exploitable vaut mieux absent qu'inventé.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return seconds_to_timestamp(float(value))
    if not isinstance(value, str):
        raise ValueError("Horodatage de type non supporté")
    text = value.strip()
    if not text or text.lower() in {"null", "none", "n/a", "inconnu"}:
        return None
    match = _LOOSE_TIMESTAMP_RE.match(text)
    if not match:
        raise ValueError(f"Horodatage invalide : {value!r}")
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2))
    seconds = int(match.group(3))
    if minutes > 59 or seconds > 59:
        raise ValueError(f"Horodatage invalide : {value!r}")
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def seconds_to_timestamp(seconds: float) -> str:
    """Convertit des secondes en ``HH:MM:SS``."""
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


class StrictModel(BaseModel):
    """Base commune : champs inconnus interdits, chaînes nettoyées."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        validate_assignment=True,
    )


class TimestampedModel(StrictModel):
    """Modèle disposant d'un champ ``timestamp`` normalisé."""

    @field_validator("timestamp", mode="before", check_fields=False)
    @classmethod
    def _normalize_timestamp(cls, value: object) -> str | None:
        return normalize_timestamp(value)


# --- Transcription ---------------------------------------------------------


class TranscriptSegment(StrictModel):
    """Segment horodaté normalisé, quelle que soit la source."""

    index: int = Field(ge=0, description="Position du segment dans la transcription")
    text: str = Field(min_length=1, description="Texte nettoyé du segment")
    start: float = Field(ge=0.0, description="Début du segment en secondes")
    duration: float = Field(ge=0.0, description="Durée du segment en secondes")
    timestamp: str = Field(description="Début du segment au format HH:MM:SS")

    @field_validator("timestamp")
    @classmethod
    def _check_timestamp(cls, value: str) -> str:
        if not _TIMESTAMP_RE.match(value):
            raise ValueError("Le format attendu est HH:MM:SS")
        return value


class TranscriptInfo(StrictModel):
    """Métadonnées de traçabilité de la transcription utilisée."""

    segment_count: int = Field(ge=0, description="Nombre de segments retenus")
    language: str | None = Field(
        default=None, description="Code de langue de la transcription, ex. fr-CA"
    )
    source: TranscriptSource = Field(description="Origine exacte de la transcription")
    is_auto_generated: bool = Field(
        default=False,
        description="Vrai si les sous-titres ont été générés automatiquement",
    )
    hash: str | None = Field(
        default=None,
        description="SHA-256 du texte concaténé, pour éviter les retraitements",
    )
    duration_seconds: float | None = Field(
        default=None, ge=0.0, description="Durée couverte par les segments"
    )
    quality_score: Confidence | None = Field(
        default=None,
        description="Qualité estimée de la transcription (0 à 1)",
    )
    segments: list[TranscriptSegment] | None = Field(
        default=None,
        description="Segments complets, inclus seulement si demandé explicitement",
    )

    @field_validator("hash")
    @classmethod
    def _check_hash(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not re.fullmatch(r"[0-9a-f]{64}", value):
            raise ValueError("Le hash doit être un SHA-256 hexadécimal minuscule")
        return value


# --- Analyse ---------------------------------------------------------------


class KeyPoint(TimestampedModel):
    """Point clé explicitement soutenu par la transcription."""

    id: str = Field(
        pattern=r"^KP-\d{3,4}$",
        description="Identifiant stable, par exemple KP-001",
    )
    statement: str = Field(
        min_length=3,
        description="Affirmation reformulée, soutenue par la transcription",
    )
    timestamp: str | None = Field(
        default=None, description="Horodatage HH:MM:SS du passage source"
    )
    evidence: str | None = Field(
        default=None,
        max_length=400,
        description="Courte citation littérale servant de preuve",
    )
    is_inference: bool = Field(
        default=False,
        description="Vrai si le point est une interprétation et non un propos explicite",
    )
    confidence: Confidence = Field(description="Niveau de confiance entre 0 et 1")


class Recommendation(TimestampedModel):
    """Recommandation formulée dans la vidéo, ou inférence signalée comme telle."""

    text: str = Field(min_length=3, description="Action recommandée")
    priority: Priority = Field(description="Priorité déclarée ou estimée")
    applicable_to: str | None = Field(
        default=None, description="Public ou contexte visé, si précisé"
    )
    timestamp: str | None = Field(default=None, description="Horodatage HH:MM:SS")
    is_inference: bool = Field(
        default=False,
        description="Vrai si la recommandation n'est pas explicitement prononcée",
    )
    confidence: Confidence = Field(default=0.5, description="Confiance entre 0 et 1")


class Risk(TimestampedModel):
    """Risque, limite ou incertitude mentionné dans le contenu."""

    description: str = Field(min_length=3, description="Description du risque")
    severity: Severity = Field(description="Gravité estimée")
    mitigation: str | None = Field(
        default=None, description="Mesure d'atténuation mentionnée"
    )
    timestamp: str | None = Field(default=None, description="Horodatage HH:MM:SS")
    confidence: Confidence = Field(default=0.5, description="Confiance entre 0 et 1")


class Claim(TimestampedModel):
    """Affirmation vérifiable, conservée avec sa provenance."""

    text: str = Field(min_length=3, description="Affirmation telle que comprise")
    timestamp: str | None = Field(default=None, description="Horodatage HH:MM:SS")
    evidence: str | None = Field(
        default=None, max_length=400, description="Extrait littéral de la transcription"
    )
    verifiable: bool = Field(
        default=True, description="Vrai si l'affirmation peut être vérifiée hors vidéo"
    )
    confidence: Confidence = Field(description="Confiance entre 0 et 1")


class Analysis(StrictModel):
    """Résultat d'analyse produit par le modèle d'IA.

    C'est le seul modèle passé à ``with_structured_output``. Toutes les listes
    ont pour défaut une liste vide afin qu'une absence d'information soit
    représentable sans invention.
    """

    short_summary: str = Field(
        description="Résumé de 150 mots maximum, fondé uniquement sur la transcription"
    )
    detailed_summary: list[str] = Field(
        default_factory=list, description="Résumé détaillé sous forme de points"
    )
    topics: list[str] = Field(default_factory=list, description="Thèmes principaux")
    key_points: list[KeyPoint] = Field(default_factory=list, description="Points clés")
    recommendations: list[Recommendation] = Field(
        default_factory=list, description="Recommandations"
    )
    risks: list[Risk] = Field(default_factory=list, description="Risques et limites")
    people: list[str] = Field(
        default_factory=list, description="Personnes explicitement nommées"
    )
    organizations: list[str] = Field(
        default_factory=list, description="Organisations explicitement nommées"
    )
    technologies: list[str] = Field(
        default_factory=list, description="Technologies, produits ou normes cités"
    )
    unanswered_questions: list[str] = Field(
        default_factory=list,
        description="Questions que la transcription ne permet pas de trancher",
    )
    claims: list[Claim] = Field(
        default_factory=list, description="Affirmations vérifiables avec provenance"
    )
    contains_personal_data: bool = Field(
        default=False,
        description="Vrai si le contenu semble comporter des renseignements personnels",
    )
    sensitive_domains: list[
        Literal["juridique", "medical", "sst", "reglementaire", "financier", "aucun"]
    ] = Field(
        default_factory=list,
        description="Domaines sensibles détectés, exigeant une revue humaine",
    )
    confidence: Confidence = Field(description="Confiance globale de l'analyse")
    human_review_required: bool = Field(
        default=True, description="Vrai si une revue humaine est nécessaire"
    )

    @model_validator(mode="after")
    def _force_review_when_sensitive(self) -> Analysis:
        """Une donnée sensible impose la revue humaine, quoi qu'en dise le modèle."""
        sensitive = [d for d in self.sensitive_domains if d != "aucun"]
        if sensitive or self.contains_personal_data or self.confidence < 0.6:
            object.__setattr__(self, "human_review_required", True)
        return self


# --- Qualité et document ---------------------------------------------------


class QualityRecord(StrictModel):
    """Journal de qualité : méthode, avertissements, erreurs, révision."""

    extraction_method: str = Field(description="Méthode d'obtention de la transcription")
    analysis_method: str = Field(
        default="not_executed", description="Méthode d'analyse employée"
    )
    analysis_model: str | None = Field(
        default=None, description="Identifiant du modèle d'IA utilisé"
    )
    chunk_count: int = Field(default=0, ge=0, description="Nombre de blocs analysés")
    warnings: list[str] = Field(default_factory=list, description="Avertissements")
    errors: list[dict[str, str]] = Field(
        default_factory=list, description="Erreurs structurées code/message"
    )
    human_review_required: bool = Field(
        default=True, description="Revue humaine exigée avant usage"
    )
    review_reason: str | None = Field(
        default=None, description="Motif de la revue humaine"
    )
    reviewed: bool = Field(default=False, description="Revue humaine effectuée")
    reviewed_by: str | None = Field(default=None, description="Réviseur")
    reviewed_at: str | None = Field(default=None, description="Date de revue ISO 8601")


class VideoInfo(StrictModel):
    """Identification de la source et base d'utilisation."""

    url: str = Field(description="URL fournie par l'utilisateur")
    video_id: str = Field(description="Identifiant YouTube de la vidéo")
    title: str | None = Field(default=None, description="Titre, si connu")
    channel: str | None = Field(default=None, description="Chaîne, si connue")
    published_at: str | None = Field(
        default=None, description="Date de publication ISO 8601, si connue"
    )
    duration: str | None = Field(
        default=None, description="Durée ISO 8601, ex. PT18M42S"
    )
    language: str | None = Field(default=None, description="Langue du contenu")
    transcript_available: bool = Field(
        description="Vrai si une transcription exploitable a été obtenue"
    )
    transcript_source: TranscriptSource = Field(
        default="unavailable", description="Origine de la transcription"
    )
    rights_note: str = Field(
        default=(
            "Contenu traité à partir de données rendues accessibles par la source. "
            "Aucune protection technique n'a été contournée."
        ),
        description="Base légale ou note sur les droits d'utilisation",
    )

    @field_validator("url")
    @classmethod
    def _check_url(cls, value: str) -> str:
        if not value.startswith(("http://", "https://")) and not _VIDEO_ID_RE.match(value):
            raise ValueError("URL ou identifiant YouTube attendu")
        return value

    @field_validator("video_id")
    @classmethod
    def _check_video_id(cls, value: str) -> str:
        if not _VIDEO_ID_RE.match(value):
            raise ValueError("Identifiant YouTube invalide")
        return value

    @model_validator(mode="after")
    def _coherent_source(self) -> VideoInfo:
        if self.transcript_available and self.transcript_source == "unavailable":
            raise ValueError(
                "transcript_available=True est incompatible avec transcript_source=unavailable"
            )
        if not self.transcript_available and self.transcript_source != "unavailable":
            raise ValueError(
                "transcript_available=False impose transcript_source=unavailable"
            )
        return self


class Document(StrictModel):
    """Document complet sérialisé en YAML."""

    schema_version: str = Field(default=SCHEMA_VERSION, description="Version du schéma")
    generated_at: str = Field(
        default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds"),
        description="Date de génération UTC, ISO 8601",
    )
    video: VideoInfo
    transcript: TranscriptInfo
    analysis: Analysis
    quality: QualityRecord

    @model_validator(mode="after")
    def _consistency(self) -> Document:
        """Empêche un document affirmant une analyse sans transcription."""
        if not self.video.transcript_available:
            if self.analysis.key_points or self.analysis.topics:
                raise ValueError(
                    "Aucune transcription disponible : l'analyse doit rester vide"
                )
            if self.analysis.confidence != 0.0:
                raise ValueError(
                    "Aucune transcription disponible : la confiance doit être nulle"
                )
        if self.analysis.human_review_required and not self.quality.human_review_required:
            raise ValueError(
                "quality.human_review_required doit refléter analysis.human_review_required"
            )
        return self


def document_json_schema() -> dict:
    """Schéma JSON du document, utile pour la documentation et les tests."""
    return Document.model_json_schema()


def analysis_json_schema() -> dict:
    """Schéma JSON de l'analyse, transmis au modèle d'IA."""
    return Analysis.model_json_schema()
