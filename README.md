# Proxmox Report Generator

![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)
![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python)
![Proxmox VE](https://img.shields.io/badge/Proxmox-VE%208.x-orange?logo=proxmox)
![Status](https://img.shields.io/badge/Status-Stable-brightgreen)

Outil Python de génération de rapports PDF et d'administration pour infrastructure **Proxmox VE** multi-sites, avec interface terminal interactive.

---

## Fonctionnalités

- Rapport PDF complet par cluster (nœuds, VMs, stockage, réseau)
- Interface terminal interactive (TUI) pour naviguer entre les sites
- Authentification sécurisée — aucun credential en clair
- Compatible CI/CD (GitLab, GitHub Actions)

---

## Prérequis

- Python **3.10+**
- Accès réseau aux nœuds Proxmox VE (port **8006**)
- Compte Proxmox avec droits lecture (`PVEAuditor` minimum)

---

## Installation

### 1. Cloner le dépôt

```bash
git clone https://github.com/youruser/proxmox-report-generator.git
cd proxmox-report-generator
```

### 2. Installer les dépendances

```bash
pip install requests urllib3 fpdf2 paramiko
```

> Avec virtualenv :
> ```bash
> python3 -m venv .venv
> source .venv/bin/activate
> pip install requests urllib3 fpdf2 paramiko
> ```

### 3. Configurer les sites

Éditer `sites.csv` :

```csv
site,host,cluster
SITE1,192.168.1.10,cluster-name-1
SITE2,192.168.1.20,cluster-name-2
```

### 4. Placer le logo (optionnel)

```bash
cp /chemin/vers/logo.png ./logo.png
```

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

Actions disponibles par site :

| Action | Description |
|--------|-------------|
| Générer rapport PDF | Rapport complet du cluster |
| Ping | Test de connectivité |
| Infos rapides | Version PVE, nœuds, VMs en temps réel |
| SSH | Session SSH vers le nœud principal |

Les rapports sont sauvegardés dans `~/rapports/`.

---

### Script direct

```bash
python3 report.py \
  --host 192.168.1.10 \
  --site SITE1 \
  --logo ./logo.png \
  --username root@pam
```

Le mot de passe est demandé de manière sécurisée — aucun credential en clair.

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
    - python3 report.py --host $PVE_HOST --site $PVE_SITE --logo logo.png
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
├── report.py       # Script de génération PDF
├── tui.py          # Interface terminal interactive
├── sites.csv       # Liste des sites à administrer
├── logo.png        # Logo personnalisé (optionnel, non versionné)
└── README.md       # Ce fichier
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

---

## Author

**Hassan Salmane** — IT Infrastructure Engineer
[salmane.pro](https://salmane.pro) · [LinkedIn](https://linkedin.com/in/hassansalmane) · [GitHub](https://github.com/hassan-salmane)
