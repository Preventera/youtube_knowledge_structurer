"""Interface en ligne de commande de YouTube Knowledge Structurer."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from . import __version__
from .config import DEFAULT_LANGUAGES, Settings
from .errors import ExitCode, YKSError
from .export.export_yaml import export_document
from .logging_setup import configure_logging, get_logger
from .models import analysis_json_schema, document_json_schema
from .pipeline import run_pipeline

logger = get_logger("cli")

EPILOG = """\
Codes de sortie :
  0  succès                       10 média local introuvable
  1  erreur inattendue            11 format média invalide
  2  URL invalide                 12 faster-whisper non installé
  3  vidéo indisponible           13 erreur Whisper
  4  sous-titres désactivés       14 ressources insuffisantes
  5  aucune langue disponible     20 clé d'API absente
  6  transcription vide           21 erreur du modèle
  7  erreur de récupération       22 sortie non conforme au schéma
                                  30 YAML invalide
                                  31 écriture impossible
                                  32 fichier de sortie existant

Un code différent de 0 accompagné d'un fichier YAML signifie qu'un document
d'état a été produit : il documente l'échec, il ne contient aucune analyse.
"""


def build_parser() -> argparse.ArgumentParser:
    """Construit l'analyseur d'arguments."""
    parser = argparse.ArgumentParser(
        prog="yks",
        description=(
            "Transforme le contenu accessible d'une vidéo YouTube en YAML "
            "structuré, validé et traçable."
        ),
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("url", nargs="?", help="URL ou identifiant de la vidéo YouTube")
    parser.add_argument(
        "-o", "--output", default="video_structuree.yaml", help="Fichier YAML de sortie"
    )
    parser.add_argument(
        "-l",
        "--languages",
        nargs="+",
        default=list(DEFAULT_LANGUAGES),
        help="Langues par ordre de préférence (défaut : fr fr-CA en)",
    )
    parser.add_argument(
        "--media",
        default=None,
        help=(
            "Chemin d'un fichier audio ou vidéo local auquel vous avez légalement "
            "accès, utilisé seulement si aucun sous-titre n'est disponible"
        ),
    )
    parser.add_argument(
        "--whisper-model",
        default="small",
        choices=["tiny", "base", "small", "medium", "large-v3"],
        help="Modèle faster-whisper pour le repli local",
    )
    parser.add_argument("--whisper-language", default=None, help="Forcer la langue de Whisper")
    parser.add_argument(
        "--whisper-device", default="cpu", choices=["cpu", "cuda"], help="Périphérique Whisper"
    )
    parser.add_argument("--model", default=None, help="Modèle Claude à utiliser")
    parser.add_argument(
        "--chunk-characters", type=int, default=None, help="Taille maximale d'un bloc"
    )
    parser.add_argument(
        "--include-segments",
        action="store_true",
        help="Inclure tous les segments horodatés dans le YAML (fichier volumineux)",
    )
    parser.add_argument(
        "--rights-note",
        default=None,
        help="Note sur la base légale ou l'autorisation d'utilisation du contenu",
    )
    parser.add_argument(
        "--force", action="store_true", help="Écraser le fichier de sortie existant"
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Niveau de journalisation",
    )
    parser.add_argument(
        "--print-schema",
        choices=["document", "analysis"],
        default=None,
        help="Afficher le schéma JSON et quitter",
    )
    parser.add_argument("--version", action="version", version=f"yks {__version__}")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Point d'entrée : retourne le code de sortie du processus."""
    parser = build_parser()
    args = parser.parse_args(argv)
    configure_logging(args.log_level)

    if args.print_schema:
        import json

        schema = (
            document_json_schema()
            if args.print_schema == "document"
            else analysis_json_schema()
        )
        print(json.dumps(schema, indent=2, ensure_ascii=False))
        return ExitCode.OK

    if not args.url:
        parser.error("une URL ou un identifiant YouTube est requis")

    settings = Settings.from_env(
        model=args.model,
        chunk_characters=args.chunk_characters,
        languages=tuple(args.languages),
        include_segments=args.include_segments or None,
        log_level=args.log_level,
    )

    try:
        result = run_pipeline(
            args.url,
            settings=settings,
            media_path=args.media,
            whisper_model=args.whisper_model,
            whisper_language=args.whisper_language,
            whisper_device=args.whisper_device,
            rights_note=args.rights_note,
        )
    except YKSError as exc:
        logger.error("%s : %s", exc.code, exc.message)
        print(f"Erreur ({exc.code}) : {exc.message}", file=sys.stderr)
        return exc.exit_code

    try:
        path = export_document(result.document, Path(args.output), force=args.force)
    except YKSError as exc:
        logger.error("Export impossible : %s", exc.message)
        print(f"Erreur ({exc.code}) : {exc.message}", file=sys.stderr)
        return exc.exit_code

    if result.succeeded:
        print(f"YAML généré : {path}")
    else:
        print(
            f"Document d'état généré : {path} (aucune analyse produite)",
            file=sys.stderr,
        )
    if result.document.quality.human_review_required:
        print(
            f"Revue humaine requise : {result.document.quality.review_reason}",
            file=sys.stderr,
        )
    return result.exit_code


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
