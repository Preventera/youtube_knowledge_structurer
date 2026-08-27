"""Comportement en l'absence de transcription exploitable.

Règle de conception centrale : une absence de données ne doit jamais ressembler
à une conclusion de l'IA. Quand aucune transcription n'est obtenue, le modèle
d'analyse n'est pas appelé du tout et le programme produit un document d'état
explicite, avec ``confidence: 0.0`` et ``human_review_required: true``.

Arbre de décision effectivement implémenté ::

    Essayer les langues demandées
      ├─ Transcription trouvée
      │    ├─ manuelle   -> source = youtube_captions_manual
      │    └─ générée    -> source = youtube_captions_generated + avertissement
      └─ Aucune transcription
           ├─ --media fourni -> Whisper local (fichier autorisé uniquement)
           └─ sinon          -> document d'état, aucune analyse, code de sortie dédié
"""

from __future__ import annotations

from collections.abc import Sequence

from .errors import YKSError
from .models import (
    Analysis,
    Document,
    QualityRecord,
    Risk,
    TranscriptInfo,
    VideoInfo,
)

SENSITIVE_REVIEW_MESSAGE = (
    "Contenu potentiellement juridique, médical, SST, réglementaire ou comportant "
    "des renseignements personnels : validation humaine requise avant diffusion."
)


def unavailable_analysis(reason: str) -> Analysis:
    """Analyse d'état signalant l'absence de contenu analysable.

    Aucun résumé n'est fabriqué : le seul contenu est la raison de l'échec.
    """
    return Analysis(
        short_summary=(
            "Analyse impossible : aucune transcription exploitable n'a été obtenue. "
            "Aucun contenu de la vidéo n'a été résumé."
        ),
        detailed_summary=[],
        topics=[],
        key_points=[],
        recommendations=[],
        risks=[
            Risk(
                description=reason,
                severity="medium",
                mitigation=(
                    "Fournir une transcription autorisée, ou un fichier audio/vidéo "
                    "auquel vous avez légalement accès via --media."
                ),
                confidence=1.0,
            )
        ],
        people=[],
        organizations=[],
        technologies=[],
        unanswered_questions=["Quel est le contenu exact de la vidéo ?"],
        claims=[],
        contains_personal_data=False,
        sensitive_domains=[],
        confidence=0.0,
        human_review_required=True,
    )


def empty_transcript_info() -> TranscriptInfo:
    """Bloc ``transcript`` correspondant à une absence totale de source."""
    return TranscriptInfo(
        segment_count=0,
        language=None,
        source="unavailable",
        is_auto_generated=False,
        hash=None,
        duration_seconds=None,
        quality_score=None,
        segments=None,
    )


def build_unavailable_document(
    *,
    url: str,
    video_id: str,
    error: YKSError,
    warnings: Sequence[str] | None = None,
    extra_errors: Sequence[dict[str, str]] | None = None,
) -> Document:
    """Construit le document d'état complet pour une vidéo non analysable."""
    reason = f"{error.message}" + (f" ({error.details})" if error.details else "")
    errors = [error.as_record(), *(extra_errors or [])]
    return Document(
        video=VideoInfo(
            url=url,
            video_id=video_id,
            transcript_available=False,
            transcript_source="unavailable",
        ),
        transcript=empty_transcript_info(),
        analysis=unavailable_analysis(reason),
        quality=QualityRecord(
            extraction_method="failed",
            analysis_method="not_executed",
            analysis_model=None,
            chunk_count=0,
            warnings=list(warnings or []),
            errors=errors,
            human_review_required=True,
            review_reason="Aucune transcription : document d'état, non exploitable tel quel.",
            reviewed=False,
        ),
    )


def review_reason(analysis: Analysis, *, auto_generated: bool, failed_chunks: int) -> str:
    """Explique pourquoi une revue humaine est demandée."""
    reasons: list[str] = []
    sensitive = [d for d in analysis.sensitive_domains if d != "aucun"]
    if sensitive:
        reasons.append(f"domaines sensibles détectés : {', '.join(sensitive)}")
    if analysis.contains_personal_data:
        reasons.append("renseignements personnels possibles")
    if auto_generated:
        reasons.append("transcription générée automatiquement")
    if failed_chunks:
        reasons.append(f"{failed_chunks} bloc(s) non analysé(s)")
    if analysis.confidence < 0.6:
        reasons.append(f"confiance globale faible ({analysis.confidence})")
    if not reasons:
        reasons.append("revue de contrôle standard avant diffusion")
    return "; ".join(reasons)
