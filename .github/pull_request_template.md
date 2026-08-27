## Objet

<!-- Que change cette PR, et pourquoi ? -->

## Type de changement

- [ ] Correction de bogue
- [ ] Nouvelle fonctionnalité
- [ ] Changement de schéma YAML (rupture potentielle pour les consommateurs)
- [ ] Documentation ou outillage

## Vérifications

- [ ] `pytest` passe intégralement
- [ ] `ruff check .` et `mypy src/yks` passent
- [ ] Aucun appel réseau ajouté dans les tests unitaires
- [ ] Aucun secret, clé d'API ou transcription réelle dans le diff
- [ ] Si le schéma change : `schema_version` incrémentée, exemples régénérés, CHANGELOG mis à jour

## Effet sur les garanties du projet

<!-- Cette PR touche-t-elle une des garanties suivantes ? Si oui, expliquer. -->

- [ ] Aucune information n'est inventée en l'absence de transcription
- [ ] Aucun contournement d'accès ni téléchargement distant
- [ ] `yaml.safe_dump` / `yaml.safe_load` exclusivement
- [ ] La revue humaine reste imposée pour les contenus sensibles
