# Proxmox Report Generator — version générique

Outil Python de génération de rapports PDF et d'administration pour infrastructure **Proxmox VE** multi-sites, avec interface terminal interactive (TUI).

Cette version n'est liée à aucun site, organisation ou logo en particulier : tout est paramétrable via `sites.csv` et des variables d'environnement optionnelles.

---

## Fonctionnalités

- Rapport PDF complet par cluster (nœuds, VMs, stockage, réseau)
- Interface terminal interactive (TUI) pour naviguer entre tous les sites déclarés dans `sites.csv`
- Authentification sécurisée — aucun credential en clair
- Compatible CI/CD (GitLab, GitHub Actions)
- Personnalisation (organisation, auteur, logo, couleurs) sans toucher au code

---

## Démarrage rapide

```bash
# 1. Cloner le repo
git clone https://github.com/votre-user/proxmox-report-generator.git
cd proxmox-report-generator

# 2. Installer les dépendances
pip install requests urllib3 fpdf2 paramiko

# 3. Créer votre fichier de sites (à partir de l'exemple fourni)
cp sites.csv.example sites.csv
# Puis éditer sites.csv avec vos vraies IP et noms de clusters

# 4. Lancer le TUI
python3 tui.py
```

> **Note** : `sites.csv` est volontairement exclu du versionnement (`.gitignore`)
> car il contient les IP réelles de votre infrastructure. Seul `sites.csv.example`
> est versionné comme modèle de départ.

---



- Python **3.10+**
- Accès réseau aux nœuds Proxmox VE (port **8006**)
- Compte Proxmox avec droits lecture (`PVEAuditor` minimum)

---

## Installation

```bash
pip install requests urllib3 fpdf2 paramiko
```

> Avec virtualenv :
> ```bash
> python3 -m venv .venv
> source .venv/bin/activate
> pip install requests urllib3 fpdf2 paramiko
> ```

---

## Configurer les sites

Éditer `sites.csv` — une ligne par site/cluster, aucune limite de nombre :

```csv
site,host,cluster
SITE1,192.0.2.10,cluster-name-1
SITE2,192.0.2.20,cluster-name-2
SITE3,192.0.2.30,cluster-name-3
```

### Regroupement optionnel (région, client, environnement…)

Une colonne `group` optionnelle permet de regrouper les sites dans l'interface — peu importe ce qu'elle représente selon le contexte (région chez un client en architecture régionale, nom de client si vous gérez plusieurs sociétés, environnement prod/test, etc.) :

```csv
site,host,cluster,group
SITE1,192.0.2.10,cluster-name-1,REGION-A
SITE2,192.0.2.20,cluster-name-2,REGION-B
SITE3,192.0.2.30,cluster-name-3,REGION-A
```

Voir `sites.example-with-groups.csv` pour un exemple complet (répartition fictive, à adapter).

Sans cette colonne, le TUI affiche tous les sites à plat, comme avant — aucune configuration supplémentaire n'est nécessaire.

Avec cette colonne, le TUI affiche des en-têtes de groupe dans la liste ; sélectionner un en-tête (au lieu d'un site) propose de générer un rapport PDF pour l'ensemble des sites du groupe en une seule opération, avec le choix d'utiliser les mêmes identifiants pour tous ou de les saisir site par site. Une entrée « Tous les sites » est aussi disponible pour un traitement en masse sur l'intégralité du parc, tous groupes confondus.

Le libellé affiché pour ce regroupement (« Groupe » par défaut) est personnalisable via `PVE_TUI_GROUP_LABEL` (voir ci-dessous) — par exemple `"Région"`, `"Client"` ou `"Environnement"` selon le contexte d'usage.

---

## Utilisation

### Interface terminal (TUI)

```bash
python3 tui.py
```

| Touche | Action |
|--------|--------|
| `↑` `↓` | Naviguer entre les sites |
| `Enter` | Sélectionner un site |
| `Q` / `Echap` | Retour / Quitter |

Actions disponibles par site : génération de rapport PDF, ping, infos rapides (version PVE, nœuds, VMs), ouverture d'une session SSH.

Les rapports sont sauvegardés par défaut dans `~/rapports/` (configurable, voir ci-dessous).

### Script direct

```bash
python3 proxmox_report.py \
  --host 192.0.2.10 \
  --site SITE1 \
  --username root@pam
```

Le mot de passe est demandé de manière sécurisée (`getpass`) — aucun credential en clair.

---

## Personnalisation (sans toucher au code)

Toutes ces variables sont optionnelles ; le script fonctionne sans elles avec des valeurs neutres.

### TUI (`tui.py`)

| Variable | Description | Défaut |
|----------|--------------|--------|
| `PVE_TUI_SITES_CSV` | Chemin du fichier CSV des sites | `./sites.csv` |
| `PVE_TUI_REPORT` | Chemin du script de génération de rapport | `./proxmox_report.py` |
| `PVE_TUI_LOGO` | Logo à inclure dans les rapports PDF | aucun |
| `PVE_TUI_OUTDIR` | Dossier de sortie des rapports | `~/rapports` |
| `PVE_TUI_TITLE` | Titre affiché en en-tête de l'interface | `Gestionnaire de sites Proxmox` |
| `PVE_TUI_GROUP_LABEL` | Libellé du regroupement affiché dans l'interface (ex: `Région`, `Client`) | `Groupe` |

### Rapport PDF (`proxmox_report.py`)

| Variable / Argument | Description | Défaut |
|----------------------|--------------|--------|
| `PVE_REPORT_ORG` / `--org` | Nom d'organisation affiché en en-tête du rapport | `Infrastructure IT` |
| `PVE_REPORT_AUTHOR` / `--author` | Nom affiché en pied de page | `Infrastructure IT` |
| `PVE_REPORT_COLOR_HEADER` | Couleur principale (format `R,G,B`) | `0,86,162` |
| `PVE_REPORT_COLOR_ACCENT` | Couleur d'accent (format `R,G,B`) | `0,174,239` |

Exemple :

```bash
export PVE_TUI_TITLE="Gestionnaire de sites Proxmox — Refonte & Migration"
export PVE_REPORT_ORG="Refonte & Migration — Infrastructure"
python3 tui.py
```

### Logo (optionnel)

```bash
export PVE_TUI_LOGO=/chemin/vers/logo.png
```

---

## Authentification

### Mode interactif

Aucune configuration requise. Username et password demandés au lancement via `getpass`.

### Mode CI/CD

Déclarer les variables d'environnement suivantes :

| Variable | Description | Sensible |
|----------|-------------|----------|
| `PVE_TOKEN_USER` | Utilisateur du token (ex: `root@pam`) | Non |
| `PVE_TOKEN_ID` | Identifiant du token Proxmox | Non |
| `PVE_TOKEN_SECRET` | Secret du token Proxmox | **Oui** |

Créer le token dans Proxmox : **Datacenter → Permissions → API Tokens → Add**.

Exemple `.gitlab-ci.yml` :

```yaml
generate_report:
  stage: report
  script:
    - pip install requests urllib3 fpdf2 paramiko
    - python3 proxmox_report.py --host $PVE_HOST --site $PVE_SITE
  artifacts:
    paths:
      - "*.pdf"
    expire_in: 30 days
  only:
    - schedules
```

---

## Structure du projet

```
proxmox-report-generator/
├── proxmox_report.py   # Script de génération PDF (générique, multi-sites)
├── tui.py              # Interface terminal interactive (générique)
├── sites.csv           # Liste des sites à administrer
└── README.md            # Ce fichier
```

> Ajouter dans `.gitignore` :
> ```
> logo.png
> *.pdf
> rapports/
> ```

---

## Dépendances

| Package | Usage |
|---------|-------|
| `requests` | Appels API Proxmox |
| `urllib3` | Gestion SSL/TLS |
| `fpdf2` | Génération PDF |
| `paramiko` | Collecte SSH (optionnel) |

---

## Licence

MIT License — libre d'utilisation, modification et distribution.
