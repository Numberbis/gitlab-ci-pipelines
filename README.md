# GitLab CI — Scan Trivy multi-images

Pipeline GitLab CI qui scanne automatiquement une liste d'images Docker avec
[Trivy](https://github.com/aquasecurity/trivy) et produit un rapport global
priorisant les images à mettre à jour selon le nombre de vulnérabilités
**CRITICAL** et **HIGH**.

Le pipeline est volontairement **non bloquant** pour le moment : il produit
le rapport mais ne fait jamais échouer le build. Voir
[Activer les seuils d'échec](#activer-les-seuils-déchec) pour rendre le
pipeline bloquant une fois les montées de versions terminées.

## Structure du dépôt

```
.
├── .gitlab-ci.yml             # Définition du pipeline (scan + report + publish)
├── images.txt                 # Liste des images à scanner (une par ligne)
└── scripts/
    ├── generate_report.py     # Agrégation des JSON Trivy en rapport global
    └── convert_to_html.py     # Conversion Markdown → HTML auto-contenu
```

## Fonctionnement du pipeline

Le pipeline est composé de trois stages.

### 1. `scan` — job `scan-images`

- Image : `aquasec/trivy:${TRIVY_VERSION}`.
- Lit `images.txt` ligne par ligne (les lignes vides et commençant par `#`
  sont ignorées). Si une ligne contient `=>`, seule la partie gauche est
  scannée — la partie droite est la cible de montée de version, utilisée
  uniquement par le rapport.
- Pour chaque image, exécute :
  ```sh
  trivy image \
    --severity CRITICAL,HIGH \
    --format json \
    --output reports/<nom_image>.json \
    --cache-dir .trivycache \
    --timeout 10m \
    --exit-code 0 \
    <image>
  ```
- `--exit-code 0` : le scan ne fait jamais échouer le job — la décision
  d'échec est centralisée dans le job de rapport.
- La DB de vulnérabilités Trivy est mise en cache (`cache.key: trivy-db`)
  pour accélérer les exécutions suivantes.
- Artefacts : le dossier `reports/` contenant un JSON par image, conservé
  1 semaine.

### 2. `report` — job `generate-report`

- Image : `python:3.11-slim`.
- Récupère les artefacts du job `scan-images` via `needs`.
- Exécute :
  `scripts/generate_report.py reports/ report.md report.json --images-file images.txt`.
- L'option `--images-file` permet d'alimenter la colonne *Version cible* du
  rapport à partir de la syntaxe `image => cible` du fichier d'images.
- Produit :
  - `report.md` — rapport Markdown lisible avec totaux et tableau priorisé.
  - `report.json` — version structurée, également exposée via
    `artifacts:reports:container_scanning` pour affichage dans le widget
    Merge Request de GitLab.
- Affiche les 40 premières lignes du rapport dans les logs du job.
- Artefacts conservés 1 mois.

### 3. `publish` — job `convert-html`

- Image : `python:3.11-slim`.
- Récupère `report.md` depuis l'artefact de `generate-report`.
- Installe `curl` et la dépendance Python `markdown`, puis exécute :
  `scripts/convert_to_html.py report.md report.html`.
- Produit `report.html` : page HTML **auto-contenue** (CSS inline, aucune
  ressource externe), prête à être servie depuis Artifactory ou n'importe
  quel serveur statique.
- **Upload automatique vers Artifactory** : pousse le HTML en deux
  exemplaires :
  - `report-<YYYYMMDD-HHMMSS>.html` — version horodatée (historique).
  - `report-latest.html` — alias mis à jour à chaque run pour un lien
    stable.
- Artefact `report.html` conservé 1 mois côté GitLab.

#### Variables à définir pour l'upload Artifactory

Dans le projet GitLab : *Settings > CI/CD > Variables*, ajouter :

| Variable                | Type                          | Exemple |
|-------------------------|-------------------------------|---------|
| `ARTIFACTORY_BASE_URL`  | Variable (non masquée)        | `https://artifactory.example.com/artifactory/my-repo/trivy-reports` |
| `ARTIFACTORY_USER`      | Variable masquée              | `ci-bot` |
| `ARTIFACTORY_TOKEN`     | Variable masquée + protégée   | *(token Artifactory)* |

Le job échoue clairement en début d'exécution si une de ces variables
est manquante (message `Variables manquantes : ...`). Les uploads
utilisent `curl --fail`, donc toute erreur HTTP (4xx / 5xx) fait échouer
le job.

Pour désactiver temporairement l'upload sans toucher au YAML, il suffit
de vider `ARTIFACTORY_BASE_URL` — le job s'arrêtera proprement avec un
message explicite.

## Le rapport généré

Le rapport Markdown contient :

- Les totaux globaux **CRITICAL** et **HIGH**, avec le sous-total des
  vulnérabilités *corrigeables* (celles pour lesquelles Trivy connaît une
  `FixedVersion` — ce sont les mises à jour à appliquer en priorité).
- Un tableau des images triées par priorité décroissante.

Le tri utilise un **score** simple : `10 × CRITICAL + HIGH`. Il sert
uniquement à ordonner les images, pas à les noter sur une échelle absolue.

Exemple :

```
| # | Image           | CRITICAL | HIGH | Corrigeables par montée de version (C/H) | Score | Version cible      |
|---|-----------------|----------|------|------------------------------------------|-------|--------------------|
| 1 | nginx:1.21      | 2        | 1    | 1 / 1                                    | 21    | nginx:1.27         |
| 2 | python:3.9-slim | 0        | 1    | 0 / 1                                    | 1     | python:3.12-slim   |
| 3 | redis:7.0       | 0        | 0    | 0 / 0                                    | 0     | _à définir_        |
```

## Utilisation

### Ajouter ou retirer une image

Éditer `images.txt` — une image par ligne. Aucune modification du
`.gitlab-ci.yml` n'est nécessaire. Deux syntaxes possibles :

```text
# Lignes commentées ignorées

# 1) Image seule — la colonne "Version cible" affichera "à définir".
registry.gitlab.com/mon-groupe/mon-image:1.2.3

# 2) Image + cible recommandée — la cible apparaît dans le rapport.
nginx:1.21 => nginx:1.27
python:3.9-slim => python:3.12-slim
```

Seule la partie à gauche de `=>` est scannée par Trivy. La partie droite
sert uniquement à alimenter la colonne *Version cible* du rapport pour
indiquer la montée de version à effectuer. Trivy n'a pas la connaissance
des tags Docker disponibles : c'est à toi de décider du tag cible et de
le reporter dans `images.txt`.

### Récupérer le rapport après une exécution

Quatre options :
- **Logs du job `generate-report`** : les premières lignes du rapport
  s'affichent directement.
- **Artefacts** : `report.md`, `report.json`, `reports/*.json` et
  `report.html` téléchargeables depuis l'interface GitLab pendant 1 mois.
- **Widget MR** : si le pipeline tourne sur une Merge Request, les
  vulnérabilités s'affichent dans l'onglet *Security* (via
  `container_scanning`).
- **Artifactory** : récupérer `report.html` depuis l'artefact du job
  `convert-html` et le déposer sur Artifactory (voir section dédiée
  ci-dessus).

### Variables configurables

| Variable           | Défaut      | Rôle                                            |
|--------------------|-------------|-------------------------------------------------|
| `TRIVY_VERSION`    | `0.50.1`    | Version de l'image Trivy utilisée.              |
| `TRIVY_CACHE_DIR`  | `.trivycache` | Dossier de cache pour la DB de vulnérabilités. |
| `IMAGES_FILE`      | `images.txt`| Fichier source de la liste d'images.            |

Ces variables peuvent être surchargées via les variables CI/CD du projet ou
via `variables:` dans le `.gitlab-ci.yml`.

## Activer les seuils d'échec

Une fois les montées de versions terminées, deux petites modifications
suffisent pour rendre le pipeline bloquant.

### 1. Ajouter les variables de seuil dans `.gitlab-ci.yml`

Dans le bloc `variables:` :

```yaml
variables:
  TRIVY_VERSION: "0.50.1"
  TRIVY_NO_PROGRESS: "true"
  TRIVY_CACHE_DIR: ".trivycache"
  IMAGES_FILE: "images.txt"
  FAIL_ON_CRITICAL: "1"   # 1 = échec si au moins une CRITICAL est trouvée
  FAIL_ON_HIGH: "0"       # 1 = échec aussi sur HIGH
```

### 2. Réintroduire la logique d'échec dans `scripts/generate_report.py`

À la fin de la fonction `main()`, juste avant `return 0`, ajouter :

```python
import os  # à remonter en haut du fichier

fail_on_critical = os.environ.get("FAIL_ON_CRITICAL", "0") == "1"
fail_on_high = os.environ.get("FAIL_ON_HIGH", "0") == "1"
if fail_on_critical and total_critical > 0:
    print("Seuil CRITICAL franchi — échec du pipeline.", file=sys.stderr)
    return 1
if fail_on_high and total_high > 0:
    print("Seuil HIGH franchi — échec du pipeline.", file=sys.stderr)
    return 1
```

Le pipeline échouera alors dès que les seuils seront dépassés, ce qui
forcera la prise en charge des nouvelles vulnérabilités à mesure qu'elles
apparaissent.

### Variantes possibles

- **Seuil numérique plutôt que booléen** : remplacer `FAIL_ON_CRITICAL` par
  `MAX_CRITICAL` et comparer `total_critical > int(MAX_CRITICAL)` — utile
  pour tolérer un nombre résiduel de CRITICAL connues.
- **Whitelist de CVE** : ajouter un fichier `.trivyignore` à la racine et
  passer `--ignorefile .trivyignore` à la commande `trivy image` pour
  ignorer des CVE précises.
- **Échec par image plutôt que global** : déplacer la logique de seuil dans
  la boucle de scan (en utilisant `--exit-code 1` sur Trivy) pour faire
  échouer uniquement les images en dépassement.
