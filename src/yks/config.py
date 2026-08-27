"""Configuration du pipeline, chargée depuis l'environnement.

Aucun secret n'est codé en dur. La clé d'API est lue au moment de l'appel du
modèle, jamais journalisée, et absente du document YAML produit.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

#: Modèle Claude par défaut. Vérifiez la liste courante sur
#: https://docs.claude.com/en/docs/about-claude/models/overview
DEFAULT_MODEL = "claude-sonnet-5"
DEFAULT_LANGUAGES = ("fr", "fr-CA", "en")
DEFAULT_CHUNK_CHARACTERS = 12000
DEFAULT_TIMEOUT_SECONDS = 120
DEFAULT_MAX_RETRIES = 3


def _load_dotenv_if_available() -> None:
    """Charge .env si python-dotenv est installé, sans en faire une dépendance dure."""
    try:
        from dotenv import load_dotenv
    except ImportError:  # pragma: no cover - dépend de l'environnement
        return
    load_dotenv()


@dataclass(frozen=True)
class Settings:
    """Paramètres d'exécution du pipeline."""

    model: str = DEFAULT_MODEL
    temperature: float = 0.0
    max_retries: int = DEFAULT_MAX_RETRIES
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    chunk_characters: int = DEFAULT_CHUNK_CHARACTERS
    languages: tuple[str, ...] = DEFAULT_LANGUAGES
    include_segments: bool = False
    log_level: str = "INFO"
    api_key_env_var: str = "ANTHROPIC_API_KEY"
    extra_headers: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_env(cls, **overrides: object) -> Settings:
        """Construit les paramètres depuis l'environnement, puis applique les surcharges CLI."""
        _load_dotenv_if_available()
        base = cls(
            model=os.getenv("YKS_MODEL", DEFAULT_MODEL),
            temperature=float(os.getenv("YKS_TEMPERATURE", "0")),
            max_retries=int(os.getenv("YKS_MAX_RETRIES", str(DEFAULT_MAX_RETRIES))),
            timeout_seconds=int(
                os.getenv("YKS_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT_SECONDS))
            ),
            chunk_characters=int(
                os.getenv("YKS_CHUNK_CHARACTERS", str(DEFAULT_CHUNK_CHARACTERS))
            ),
            log_level=os.getenv("YKS_LOG_LEVEL", "INFO"),
        )
        clean = {k: v for k, v in overrides.items() if v is not None}
        if not clean:
            return base
        data = base.__dict__ | clean
        return cls(**data)

    def api_key(self) -> str | None:
        """Retourne la clé d'API si elle est présente dans l'environnement."""
        _load_dotenv_if_available()
        value = os.getenv(self.api_key_env_var, "").strip()
        return value or None
