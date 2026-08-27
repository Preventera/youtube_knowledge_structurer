"""Tests de l'export YAML : aller-retour, sécurité, atomicité."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from tests.conftest import make_analysis
from yks.errors import OutputExistsError, YamlValidationError
from yks.export.export_yaml import (
    document_to_yaml,
    export_atomically,
    export_document,
    load_validated_yaml,
    validate_yaml_text,
)
from yks.models import Document, QualityRecord, TranscriptInfo, VideoInfo


@pytest.fixture
def document() -> Document:
    analysis = make_analysis(summary="Résumé avec des accents : é, à, ç, œ.")
    return Document(
        video=VideoInfo(
            url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            video_id="dQw4w9WgXcQ",
            language="fr",
            transcript_available=True,
            transcript_source="youtube_captions_manual",
        ),
        transcript=TranscriptInfo(
            segment_count=3,
            language="fr",
            source="youtube_captions_manual",
            hash="a" * 64,
            quality_score=0.9,
        ),
        analysis=analysis,
        quality=QualityRecord(
            extraction_method="youtube_transcript_api",
            analysis_method="langchain_structured_output:single_chunk",
            analysis_model="claude-sonnet-5",
            chunk_count=1,
            human_review_required=analysis.human_review_required,
        ),
    )


def test_yaml_conserve_les_accents(document: Document) -> None:
    text = document_to_yaml(document)
    assert "é, à, ç, œ" in text
    assert "\\u" not in text


def test_yaml_conserve_l_ordre_des_champs(document: Document) -> None:
    text = document_to_yaml(document)
    keys = [line.split(":")[0] for line in text.splitlines() if line and not line[0].isspace()]
    assert keys[:6] == [
        "schema_version",
        "generated_at",
        "video",
        "transcript",
        "analysis",
        "quality",
    ]


def test_yaml_sans_ancres(document: Document) -> None:
    """Deux valeurs identiques ne doivent pas produire d'alias YAML."""
    data = document.model_dump()
    data["analysis"]["topics"] = ["identique", "identique"]
    text = document_to_yaml(Document.model_validate(data))
    assert "&id" not in text and "*id" not in text


def test_round_trip_pydantic_yaml_pydantic(document: Document) -> None:
    text = document_to_yaml(document)
    assert validate_yaml_text(text) == document


def test_yaml_refuse_les_objets_python(document: Document) -> None:
    """safe_load doit rejeter une balise Python arbitraire injectée dans le fichier."""
    malicious = "!!python/object/apply:os.system ['echo compromis']\n"
    with pytest.raises(YamlValidationError):
        validate_yaml_text(malicious)


def test_yaml_mal_forme() -> None:
    with pytest.raises(YamlValidationError):
        validate_yaml_text("video: [non fermé\n  autre: 1")


def test_yaml_hors_schema() -> None:
    with pytest.raises(YamlValidationError):
        validate_yaml_text("video:\n  url: x\n")


def test_yaml_racine_non_dictionnaire() -> None:
    with pytest.raises(YamlValidationError):
        validate_yaml_text("- un\n- deux\n")


def test_export_ecrit_et_relit(document: Document, tmp_path: Path) -> None:
    target = tmp_path / "sortie.yaml"
    path = export_document(document, target)
    assert path.exists()
    assert load_validated_yaml(path).video.video_id == "dQw4w9WgXcQ"
    assert yaml.safe_load(path.read_text(encoding="utf-8"))["schema_version"] == "1.0"


def test_export_protege_le_fichier_existant(document: Document, tmp_path: Path) -> None:
    target = tmp_path / "sortie.yaml"
    export_document(document, target)
    with pytest.raises(OutputExistsError):
        export_document(document, target)
    export_document(document, target, force=True)  # ne lève pas


def test_export_cree_les_repertoires(document: Document, tmp_path: Path) -> None:
    target = tmp_path / "a" / "b" / "sortie.yaml"
    assert export_document(document, target).exists()


def test_export_ne_laisse_pas_de_fichier_temporaire(document: Document, tmp_path: Path) -> None:
    export_atomically(document, tmp_path / "sortie.yaml")
    assert [p.name for p in tmp_path.iterdir()] == ["sortie.yaml"]


def test_export_preserve_l_ancien_fichier_si_le_document_est_invalide(
    document: Document, tmp_path: Path
) -> None:
    """La validation précède l'écriture : un échec ne détruit pas la version existante."""
    target = tmp_path / "sortie.yaml"
    export_document(document, target)
    original = target.read_text(encoding="utf-8")

    broken = document.model_copy(deep=True)
    object.__setattr__(broken, "transcript", None)
    with pytest.raises(Exception):
        export_atomically(broken, target, force=True)
    assert target.read_text(encoding="utf-8") == original


def test_load_fichier_absent(tmp_path: Path) -> None:
    with pytest.raises(YamlValidationError):
        load_validated_yaml(tmp_path / "absent.yaml")
