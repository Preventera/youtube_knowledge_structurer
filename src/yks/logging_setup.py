"""Journalisation centralisée.

Le journal ne contient jamais de clé d'API ni de transcription intégrale :
seulement des métadonnées (identifiant de vidéo, langue, nombre de segments).
"""

from __future__ import annotations

import logging
import sys

_CONFIGURED = False


def configure_logging(level: str = "INFO") -> None:
    """Configure la journalisation une seule fois, sur la sortie d'erreur."""
    global _CONFIGURED
    if _CONFIGURED:
        logging.getLogger("yks").setLevel(level.upper())
        return
    handler = logging.StreamHandler(stream=sys.stderr)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-8s %(name)s :: %(message)s")
    )
    logger = logging.getLogger("yks")
    logger.addHandler(handler)
    logger.setLevel(level.upper())
    logger.propagate = False
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """Retourne un logger enfant du namespace ``yks``."""
    return logging.getLogger(f"yks.{name}")
