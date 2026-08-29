"""Chaîne d'analyse : transcription -> instance ``Analysis`` validée.

Le modèle d'IA ne produit jamais de YAML ni de texte libre. Il est contraint par
``with_structured_output(Analysis)``, donc par le schéma JSON dérivé de Pydantic.
La sortie est ensuite revalidée côté programme avant tout export.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from pydantic import ValidationError

from ..config import Settings
from ..errors import (
    MissingApiKeyError,
    ModelInvocationError,
    StructuredOutputError,
)
from ..logging_setup import get_logger
from ..models import Analysis, TranscriptSegment
from .chunking import Chunk, chunk_segments
from .prompts import (
    ANALYSIS_HUMAN_PROMPT,
    ANALYSIS_SYSTEM_PROMPT,
    AUTO_CAPTION_WARNING,
    MANUAL_CAPTION_WARNING,
    MERGE_HUMAN_PROMPT,
    MERGE_SYSTEM_PROMPT,
)

logger = get_logger("analysis")


class StructuredRunner(Protocol):
    """Objet capable de retourner une ``Analysis`` à partir d'un prompt.

    Cette abstraction permet de tester la chaîne complète avec un faux
    fournisseur, sans appel réseau ni clé d'API.
    """

    def run(self, system: str, human: str) -> Analysis:  # pragma: no cover - protocole
        ...


@dataclass
class AnalysisTelemetry:
    """Informations de qualité collectées pendant l'analyse."""

    chunk_count: int = 0
    failed_chunks: int = 0
    merge_strategy: str = "single_chunk"
    warnings: list[str] = field(default_factory=list)
    errors: list[dict[str, str]] = field(default_factory=list)


class LangChainRunner:
    """Implémentation réelle : LangChain + ChatAnthropic.

    Les imports sont différés pour que les tests unitaires et l'usage hors ligne
    n'exigent pas l'installation de LangChain.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._structured: Any = None

    def _build(self) -> Any:
        if self._structured is not None:
            return self._structured
        api_key = self.settings.api_key()
        if not api_key:
            raise MissingApiKeyError(
                f"Variable d'environnement {self.settings.api_key_env_var} absente. "
                "Renseignez-la dans .env ou dans l'environnement."
            )
        try:
            from langchain_anthropic import ChatAnthropic
            from langchain_core.prompts import ChatPromptTemplate  # noqa: F401
        except ImportError as exc:
            raise ModelInvocationError(
                "LangChain ou langchain-anthropic n'est pas installé. "
                "Installez : pip install langchain langchain-anthropic",
                details=str(exc),
            ) from exc

        # Les paramètres passent par un dictionnaire : ChatAnthropic est un modèle
        # Pydantic dont plusieurs champs sont déclarés par alias, ce que les stubs de
        # typage ne reflètent pas. Le splat évite des ignores qui deviendraient faux
        # à la prochaine version de la bibliothèque.
        llm_kwargs: dict[str, Any] = {
            "model": self.settings.model,
            "timeout": self.settings.timeout_seconds,
            "max_retries": self.settings.max_retries,
            "api_key": api_key,
        }
        # Les modèles récents rejettent « temperature » avec une erreur 400. On ne
        # l'envoie donc que s'il est explicitement réglé sur une valeur non nulle.
        # Le déterminisme reste assuré par with_structured_output, qui contraint la
        # sortie au schéma Pydantic.
        temperature = self.settings.temperature
        if temperature is not None and temperature != 0.0:
            llm_kwargs["temperature"] = temperature

        llm = ChatAnthropic(**llm_kwargs)
        self._structured = llm.with_structured_output(Analysis)
        return self._structured

    def run(self, system: str, human: str) -> Analysis:
        """Exécute un appel structuré et retourne une ``Analysis`` validée."""
        from langchain_core.prompts import ChatPromptTemplate

        structured = self._build()
        prompt = ChatPromptTemplate.from_messages(
            [("system", "{system}"), ("human", "{human}")]
        )
        chain = prompt | structured
        try:
            result = chain.invoke({"system": system, "human": human})
        except ValidationError as exc:
            raise StructuredOutputError(
                "La sortie du modèle ne respecte pas le schéma Analysis",
                details=str(exc),
            ) from exc
        except Exception as exc:
            raise ModelInvocationError(
                "Échec de l'appel au modèle d'analyse",
                details=f"{type(exc).__name__}: {exc}",
            ) from exc

        if isinstance(result, Analysis):
            return result
        try:
            return Analysis.model_validate(result)
        except ValidationError as exc:
            raise StructuredOutputError(
                "La sortie du modèle ne respecte pas le schéma Analysis",
                details=str(exc),
            ) from exc


def renumber_key_points(analysis: Analysis) -> Analysis:
    """Renumérote les points clés de façon continue et stable."""
    data = analysis.model_dump()
    for position, point in enumerate(data.get("key_points", []), start=1):
        point["id"] = f"KP-{position:03d}"
    return Analysis.model_validate(data)


def _dedupe(items: list[dict], key: Callable[[dict], str]) -> list[dict]:
    """Déduplique en conservant l'entrée la plus fiable (preuve puis confiance)."""
    best: dict[str, dict] = {}
    for item in items:
        signature = key(item)
        current = best.get(signature)
        if current is None:
            best[signature] = item
            continue
        score = (bool(item.get("evidence")), float(item.get("confidence") or 0.0))
        current_score = (
            bool(current.get("evidence")),
            float(current.get("confidence") or 0.0),
        )
        if score > current_score:
            best[signature] = item
    return list(best.values())


def merge_locally(analyses: Sequence[Analysis]) -> Analysis:
    """Fusion déterministe, sans appel au modèle.

    Sert de solution de repli si la fusion par IA échoue, et de comportement par
    défaut si l'utilisateur préfère une fusion reproductible. Aucune information
    nouvelle n'est créée : seules des unions et des déduplications sont faites.
    """
    if not analyses:
        raise ValueError("Aucune analyse à fusionner")
    if len(analyses) == 1:
        return renumber_key_points(analyses[0])

    dumps = [a.model_dump() for a in analyses]

    def union(field_name: str) -> list[str]:
        seen: dict[str, str] = {}
        for dump in dumps:
            for value in dump.get(field_name, []):
                seen.setdefault(str(value).strip().lower(), str(value).strip())
        return list(seen.values())

    key_points = _dedupe(
        [kp for dump in dumps for kp in dump["key_points"]],
        key=lambda item: item["statement"].strip().lower(),
    )
    key_points.sort(key=lambda item: (item.get("timestamp") or "99:99:99"))

    merged = {
        "short_summary": " ".join(
            dump["short_summary"].strip() for dump in dumps if dump["short_summary"]
        )[:1200],
        "detailed_summary": [
            line for dump in dumps for line in dump["detailed_summary"]
        ],
        "topics": union("topics"),
        "key_points": key_points,
        "recommendations": _dedupe(
            [r for dump in dumps for r in dump["recommendations"]],
            key=lambda item: item["text"].strip().lower(),
        ),
        "risks": _dedupe(
            [r for dump in dumps for r in dump["risks"]],
            key=lambda item: item["description"].strip().lower(),
        ),
        "people": union("people"),
        "organizations": union("organizations"),
        "technologies": union("technologies"),
        "unanswered_questions": union("unanswered_questions"),
        "claims": _dedupe(
            [c for dump in dumps for c in dump["claims"]],
            key=lambda item: item["text"].strip().lower(),
        ),
        "contains_personal_data": any(d["contains_personal_data"] for d in dumps),
        "sensitive_domains": union("sensitive_domains"),
        # La confiance fusionnée ne dépasse jamais la moyenne des blocs : une
        # certitude locale ne vaut pas une certitude sur l'ensemble de la vidéo.
        "confidence": round(sum(d["confidence"] for d in dumps) / len(dumps), 2),
        "human_review_required": any(d["human_review_required"] for d in dumps),
    }
    return renumber_key_points(Analysis.model_validate(merged))


def merge_with_model(runner: StructuredRunner, analyses: Sequence[Analysis]) -> Analysis:
    """Fusion assistée par le modèle, avec repli déterministe en cas d'échec."""
    if len(analyses) == 1:
        return renumber_key_points(analyses[0])
    serialized = "\n\n--- ANALYSE SUIVANTE ---\n\n".join(
        a.model_dump_json(indent=2) for a in analyses
    )
    merged = runner.run(
        MERGE_SYSTEM_PROMPT, MERGE_HUMAN_PROMPT.format(analyses=serialized)
    )
    ceiling = max(a.confidence for a in analyses)
    if merged.confidence > ceiling:
        merged = merged.model_copy(update={"confidence": ceiling})
    return renumber_key_points(merged)


def analyze_segments(
    segments: Sequence[TranscriptSegment],
    *,
    runner: StructuredRunner,
    settings: Settings,
    language: str,
    source: str,
    is_auto_generated: bool,
    use_model_merge: bool = True,
) -> tuple[Analysis, AnalysisTelemetry]:
    """Analyse une transcription complète et retourne l'analyse fusionnée.

    Un bloc en échec n'interrompt pas le traitement : l'erreur est consignée dans
    la télémétrie, le bloc est ignoré et la revue humaine devient obligatoire. Si
    tous les blocs échouent, l'exception est propagée.
    """
    telemetry = AnalysisTelemetry()
    chunks: list[Chunk] = chunk_segments(segments, settings.chunk_characters)
    telemetry.chunk_count = len(chunks)
    if not chunks:
        raise ModelInvocationError("Aucun bloc à analyser")

    warning = AUTO_CAPTION_WARNING if is_auto_generated else MANUAL_CAPTION_WARNING
    partials: list[Analysis] = []
    last_error: Exception | None = None

    for chunk in chunks:
        human = ANALYSIS_HUMAN_PROMPT.format(
            chunk_number=chunk.number,
            total_chunks=len(chunks),
            start_timestamp=chunk.start_timestamp,
            end_timestamp=chunk.end_timestamp,
            language=language,
            source=source,
            source_warning=warning,
            chunk=chunk.text,
        )
        try:
            partials.append(runner.run(ANALYSIS_SYSTEM_PROMPT, human))
            logger.info("Bloc %d/%d analysé", chunk.number, len(chunks))
        except (ModelInvocationError, StructuredOutputError) as exc:
            last_error = exc
            telemetry.failed_chunks += 1
            telemetry.errors.append(exc.as_record())
            telemetry.warnings.append(
                f"Bloc {chunk.number}/{len(chunks)} non analysé : {exc.code}"
            )
            logger.warning("Bloc %d en échec : %s", chunk.number, exc)

    if not partials:
        raise last_error or ModelInvocationError("Tous les blocs ont échoué")

    if len(partials) == 1:
        telemetry.merge_strategy = "single_chunk"
        merged = renumber_key_points(partials[0])
    elif use_model_merge:
        try:
            merged = merge_with_model(runner, partials)
            telemetry.merge_strategy = "model_merge"
        except (ModelInvocationError, StructuredOutputError) as exc:
            telemetry.warnings.append(
                "Fusion par le modèle indisponible : fusion déterministe appliquée"
            )
            telemetry.errors.append(exc.as_record())
            merged = merge_locally(partials)
            telemetry.merge_strategy = "local_merge_fallback"
    else:
        merged = merge_locally(partials)
        telemetry.merge_strategy = "local_merge"

    if telemetry.failed_chunks:
        # Une couverture partielle ne peut pas produire une analyse sûre.
        penalty = telemetry.failed_chunks / max(1, telemetry.chunk_count)
        merged = merged.model_copy(
            update={
                "confidence": round(max(0.0, merged.confidence * (1 - penalty)), 2),
                "human_review_required": True,
            }
        )
    return merged, telemetry


def default_runner(settings: Settings | None = None) -> StructuredRunner:
    """Fabrique le runner réel basé sur LangChain et Claude."""
    return LangChainRunner(settings or Settings.from_env())