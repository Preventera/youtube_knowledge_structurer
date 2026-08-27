# Politique de sécurité

## Signaler une vulnérabilité

N'ouvrez pas d'issue publique. Utilisez l'onglet **Security → Report a vulnerability**
du dépôt, ou écrivez au mainteneur. Décrivez l'impact, les étapes de reproduction
et la version concernée. Une première réponse est visée sous 7 jours.

## Périmètre

Sont considérés comme des vulnérabilités :

- toute exécution de code déclenchée par la lecture d'un fichier YAML produit ou relu ;
- toute fuite de la clé d'API dans les journaux, le YAML ou un message d'erreur ;
- tout chemin de code permettant d'écrire hors du fichier de sortie demandé ;
- toute injection par le contenu de la transcription menant le modèle à ignorer
  ses contraintes (le texte analysé est une donnée, jamais une consigne).

## Bonnes pratiques imposées par le code

- `yaml.safe_dump` et `yaml.safe_load` exclusivement : aucun objet Python arbitraire
  n'est construit à la lecture.
- `extra="forbid"` sur tous les modèles : un champ inattendu fait échouer la validation.
- Aucun secret n'est codé en dur ; la clé est lue depuis l'environnement au moment de l'appel.
- Aucun téléchargement de média distant, aucun contournement de restriction d'accès.

## Ce que vous devez faire de votre côté

- Ne versionnez jamais `.env`. Le fichier est dans `.gitignore` et la CI refuse un dépôt
  qui le contiendrait.
- Faites tourner votre clé d'API si elle a été exposée, même brièvement.
- Pour un contenu comportant des renseignements personnels, évaluez l'usage d'un modèle
  hébergé dans votre juridiction plutôt qu'une API externe, et conservez la transcription
  source séparément du YAML diffusé.
