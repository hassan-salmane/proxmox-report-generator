# Proxmox Report Generator

![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)
![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python)
![Proxmox VE](https://img.shields.io/badge/Proxmox-VE%208.x-orange?logo=proxmox)
![Status](https://img.shields.io/badge/Status-Stable-brightgreen)

Python tool for generating PDF reports and administering **Proxmox VE** multi-site infrastructure, with an interactive terminal UI.

---

## Features

- Full PDF report per cluster (nodes, VMs, storage, network)
- Interactive terminal UI (TUI) to navigate between sites
- Secure authentication — no credentials in plain text
- CI/CD ready (GitLab, GitHub Actions)

---

## Requirements

- Python **3.10+**
- Network access to Proxmox VE nodes (port **8006**)
- Proxmox account with read permissions (`PVEAuditor` minimum)

---

## Installation

### 1. Clone the repository

    git clone https://github.com/hassan-salmane/proxmox-report-generator.git
    cd proxmox-report-generator

### 2. Install dependencies

    pip install requests urllib3 fpdf2 paramiko

### 3. Configure sites

Edit `sites.csv`:

    site,host,cluster
    SITE1,192.168.1.10,cluster-name-1
    SITE2,192.168.1.20,cluster-name-2

### 4. Add a logo (optional)

    cp /path/to/logo.png ./logo.png

---

## Usage

### Terminal UI (recommended)

    python3 tui.py

| Key | Action |
|-----|--------|
| Up / Down | Navigate between sites |
| Enter | Select a site |
| Q / Esc | Back / Quit |

Available actions per site:

| Action | Description |
|--------|-------------|
| Generate PDF report | Full cluster PDF report |
| Ping | Network connectivity test |
| Quick info | Live PVE version, nodes, VMs |
| SSH | Open SSH session to the main node |

Reports are saved to ~/reports/.

---

### Direct script

    python3 report.py --host 192.168.1.10 --site SITE1 --logo ./logo.png --username root@pam

Password is prompted securely via getpass — no credentials in plain text.

---

## Authentication

### Interactive mode

No configuration required. Username and password are prompted at startup.

### CI/CD mode

| Variable | Description | Sensitive |
|----------|-------------|-----------|
| PVE_TOKEN_USER | Token user (e.g. root@pam) | No |
| PVE_TOKEN_ID | Proxmox API token ID | No |
| PVE_TOKEN_SECRET | Proxmox API token secret | Yes |

Create the token in Proxmox: Datacenter -> Permissions -> API Tokens -> Add.

---

## Project structure

    proxmox-report-generator/
    |-- report.py       # PDF report generation script
    |-- tui.py          # Interactive terminal UI
    |-- sites.csv       # Site list
    |-- logo.png        # Custom logo (optional, not versioned)
    |-- README.md       # This file

---

## Dependencies

| Package | Usage |
|---------|-------|
| requests | Proxmox API calls |
| urllib3 | SSL/TLS handling |
| fpdf2 | PDF generation |
| paramiko | SSH NIC speed collection (optional) |

---

## License

MIT — see LICENSE.

---

## Author

**Hassan Salmane** — IT Infrastructure Engineer
[salmane.pro](https://salmane.pro) · [LinkedIn](https://linkedin.com/in/hassansalmane) · [GitHub](https://github.com/hassan-salmane)
