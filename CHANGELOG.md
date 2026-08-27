# Journal des modifications

Format inspiré de [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/).
Le projet suit le versionnage sémantique. `schema_version` du YAML évolue
indépendamment de la version du paquet et est documentée à chaque changement.

## [Non publié]

## [1.0.0] — 2026-08-27

Version initiale. `schema_version` du document YAML : `1.0`.

### Ajouté

- Extraction et validation de l'identifiant YouTube (`watch`, `youtu.be`, `shorts`,
  `embed`, `live`, identifiant nu).
- Récupération des sous-titres accessibles avec préférence pour le français, et
  distinction explicite entre pistes manuelles et générées automatiquement.
- Normalisation des segments : nettoyage HTML, filtrage des annotations sonores,
  horodatage `HH:MM:SS`, hash SHA-256 de la transcription.
- Analyse par Claude via LangChain en sortie structurée Pydantic, avec découpage
  en blocs et recouvrement, fusion assistée par modèle et repli déterministe.
- Modèles Pydantic v2 stricts (`extra="forbid"`), scores bornés, invariants de
  cohérence entre disponibilité de la transcription et contenu de l'analyse.
- Repli Whisper local sur fichier explicitement fourni, avec `vad_filter` imposé.
- Documents d'état pour les vidéos sans transcription : aucune analyse, confiance
  nulle, revue humaine exigée, code de sortie dédié.
- Export YAML sûr : `safe_dump`, alias désactivés, relecture et revalidation,
  écriture atomique, protection contre l'écrasement sans `--force`.
- Revue humaine imposée automatiquement pour les domaines sensibles, les
  renseignements personnels, les blocs en échec et les confiances faibles.
- Interface en ligne de commande avec 17 codes de sortie distincts.
- 126 tests, tous hors ligne.
