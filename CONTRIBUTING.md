# Contribuer

## Mise en route

```bash
git clone https://github.com/Preventera/youtube_knowledge_structurer.git
cd youtube_knowledge_structurer
python -m venv .venv && source .venv/bin/activate   # Windows : .venv\Scripts\activate
pip install -r requirements-dev.txt
pip install -e .
pre-commit install        # facultatif mais recommandé
pytest                    # doit passer intégralement, hors ligne
```

## Avant chaque commit

```bash
ruff check . --fix
ruff format .
mypy src/yks
pytest
```

## Règles non négociables

Ces garanties sont la raison d'être du projet. Une PR qui les affaiblit sera refusée,
même si les tests passent.

1. **Aucune information inventée.** Sans transcription, aucun résumé n'est produit et le
   modèle d'analyse n'est pas appelé. Le validateur de `Document` refuse d'ailleurs un
   document dont l'analyse serait non vide alors que `transcript_available` est faux.
2. **Aucun contournement.** Pas de téléchargement de vidéo distante, pas de scraping,
   pas de contournement de restriction d'accès. Whisper ne s'exécute que sur un fichier
   local fourni explicitement avec `--media`.
3. **YAML sûr.** `safe_dump` et `safe_load` uniquement. Jamais `yaml.load` ni `yaml.dump`.
4. **Le modèle ne produit jamais de YAML.** Il retourne une structure Pydantic validée ;
   la sérialisation est faite par Python.
5. **La revue humaine reste imposée** pour les contenus juridiques, médicaux, SST,
   réglementaires, financiers ou comportant des renseignements personnels.
6. **Tests hors ligne.** Aucun test unitaire n'appelle YouTube, l'API Claude ou Whisper.
   Les frontières externes s'injectent : `captions_fetcher`, `runner`, `model_loader`.

## Changer le schéma YAML

Le YAML est consommé par d'autres systèmes ; un changement de champ est une rupture.

- Ajout de champ optionnel : `schema_version` en version mineure, exemples régénérés.
- Suppression, renommage ou changement de type : version majeure, entrée dédiée dans
  le CHANGELOG et note de migration.
- Dans tous les cas, régénérez `examples/` et vérifiez que le job `schema` de la CI passe.

## Style

- Python 3.11+, typage complet, fonctions courtes et testables.
- Docstrings et commentaires en français ; noms de variables et de fonctions en anglais
  quand c'est l'usage de l'écosystème (`chunk`, `segments`, `runner`).
- Un commentaire explique *pourquoi*, pas *quoi*.
- Ligne de 100 caractères, mise en forme par `ruff format`.

## Branches et commits

- `main` protégée, PR obligatoire, CI verte exigée.
- Branches `feat/...`, `fix/...`, `docs/...`, `chore/...`.
- Commits au format Conventional Commits : `feat(analysis): ...`, `fix(export): ...`.
