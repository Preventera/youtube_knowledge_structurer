"""Export YAML sûr et vérifié.

Chaîne imposée : ``Analysis`` validée -> ``Document`` validé -> dictionnaire
JSON-compatible -> ``yaml.safe_dump`` -> relecture ``yaml.safe_load`` ->
revalidation Pydantic. Le modèle d'IA n'écrit jamais de YAML directement.

``safe_dump``/``safe_load`` sont utilisés exclusivement : ils n'émettent que des
balises YAML standard et ne construisent aucun objet Python arbitraire à la
lecture.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import yaml
from pydantic import ValidationError

from ..errors import OutputExistsError, YamlValidationError, YamlWriteError
from ..logging_setup import get_logger
from ..models import Document

logger = get_logger("export")


class _NoAliasDumper(yaml.SafeDumper):
    """Dumper interdisant les ancres et alias YAML.

    Deux points clés au texte identique produiraient sinon un alias ``*id001``,
    illisible pour un humain et fragile pour les outils qui relisent le fichier.
    """

    def ignore_aliases(self, data: object) -> bool:  # noqa: ARG002 (signature PyYAML)
        """Désactive systématiquement les alias."""
        return True


def document_to_yaml(document: Document) -> str:
    """Sérialise un document validé en YAML UTF-8 lisible."""
    payload = document.model_dump(mode="json", exclude_none=False)
    return yaml.dump(
        payload,
        Dumper=_NoAliasDumper,
        allow_unicode=True,   # conserve les accents au lieu de les échapper
        sort_keys=False,      # conserve l'ordre déclaré du schéma
        default_flow_style=False,
        width=100,
    )


def validate_yaml_text(text: str) -> Document:
    """Relit un texte YAML et le revalide selon le schéma.

    :raises YamlValidationError: YAML mal formé ou non conforme au schéma.
    """
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise YamlValidationError("YAML syntaxiquement invalide", details=str(exc)) from exc
    if not isinstance(data, dict):
        raise YamlValidationError("Le document YAML racine doit être un dictionnaire")
    try:
        return Document.model_validate(data)
    except ValidationError as exc:
        raise YamlValidationError(
            "Le YAML relu ne respecte pas le schéma du document", details=str(exc)
        ) from exc


def load_validated_yaml(path: str | Path) -> Document:
    """Charge un fichier YAML existant et le valide."""
    file_path = Path(path)
    try:
        text = file_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise YamlValidationError(
            f"Lecture impossible : {file_path}", details=str(exc)
        ) from exc
    return validate_yaml_text(text)


def export_atomically(document: Document, path: str | Path, *, force: bool = False) -> Path:
    """Écrit le document YAML de façon atomique, après vérification.

    L'écriture passe par un fichier temporaire dans le même répertoire puis un
    ``os.replace`` : une interruption ne peut donc pas laisser un YAML tronqué à
    la place d'un fichier valide.

    :raises OutputExistsError: le fichier existe et ``force`` est faux.
    :raises YamlValidationError: la relecture du YAML échoue.
    :raises YamlWriteError: erreur système pendant l'écriture.
    """
    target = Path(path).expanduser()
    if target.exists() and not force:
        raise OutputExistsError(
            f"Le fichier {target} existe déjà. Utilisez --force pour l'écraser."
        )

    text = document_to_yaml(document)
    validate_yaml_text(text)  # échoue avant d'avoir touché au disque

    target.parent.mkdir(parents=True, exist_ok=True)
    handle = None
    temp_path: Path | None = None
    try:
        fd, temp_name = tempfile.mkstemp(
            dir=str(target.parent), prefix=f".{target.name}.", suffix=".tmp"
        )
        temp_path = Path(temp_name)
        handle = os.fdopen(fd, "w", encoding="utf-8")
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
        handle.close()
        handle = None
        os.replace(temp_path, target)
        temp_path = None
    except OSError as exc:
        raise YamlWriteError(
            f"Écriture impossible dans {target}", details=str(exc)
        ) from exc
    finally:
        if handle is not None:  # pragma: no cover - chemin d'erreur rare
            handle.close()
        if temp_path is not None and temp_path.exists():
            temp_path.unlink(missing_ok=True)

    logger.info("YAML écrit : %s (%d octets)", target, len(text.encode("utf-8")))
    return target


def export_document(document: Document, path: str | Path, *, force: bool = False) -> Path:
    """Point d'entrée public : export atomique puis relecture du fichier écrit."""
    target = export_atomically(document, path, force=force)
    load_validated_yaml(target)  # garantit qu'un fichier lisible et valide est sur disque
    return target
