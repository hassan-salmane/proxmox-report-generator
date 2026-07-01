# Proxmox Report Generator

A Python tool to generate PDF audit reports for Proxmox VE clusters, with an interactive terminal UI for multi-site management.

Built for consultants and infrastructure engineers who manage multiple Proxmox clusters across different clients or sites — the kind of setup where you need a quick, repeatable way to produce clean reports without logging into each cluster manually.

---

## What it does

- Connects to the Proxmox API and pulls cluster data (nodes, VMs, LXC, storage, network)
- Generates a multi-page PDF report per cluster
- Provides a terminal UI to navigate and manage all your sites from one place
- Supports site grouping (by region, client, or any category you define)
- Batch PDF generation — run reports for an entire group or all sites at once
- Optional Zabbix integration to auto-build your sites inventory

---

## Requirements

- Python 3.10+
- API access to Proxmox VE nodes (port 8006)
- `PVEAuditor` role minimum — read-only is enough

```bash
pip install requests urllib3 fpdf2 paramiko
```

---

## Getting started

```bash
git clone https://github.com/hassan-salmane/proxmox-report-generator.git
cd proxmox-report-generator
pip install requests urllib3 fpdf2 paramiko
cp sites.csv.example sites.csv
# edit sites.csv with your clusters
python3 tui.py
```

---

## sites.csv

The only file you need to configure. One line per cluster:

```csv
site,host,cluster
SITE1,192.0.2.10,cluster-name-1
SITE2,192.0.2.20,cluster-name-2
```

Add a `group` column if you manage multiple regions or clients — the TUI will group your sites accordingly and let you run batch reports per group:

```csv
site,host,cluster,group
SITE1,192.0.2.10,cluster-name-1,CLIENT-A
SITE2,192.0.2.20,cluster-name-2,CLIENT-A
SITE3,192.0.2.30,cluster-name-3,CLIENT-B
```

`sites.csv` is excluded from git by default (see `.gitignore`) — it contains your real infrastructure IPs and should never be committed.

---

## TUI navigation

```
↑ ↓     Navigate sites or groups
Enter   Select a site → action menu (PDF, ping, quick info, SSH)
        Select a group → batch actions for all sites in the group
Q       Back / Quit
```

---

## Generating a report directly

```bash
python3 proxmox_report.py \
  --host 192.0.2.10 \
  --site SITE1 \
  --username root@pam
```

Password is prompted via `getpass` — nothing stored in plain text.

---

## Configuration

Everything is driven by environment variables — no need to touch the code:

| Variable | What it does | Default |
|----------|-------------|---------|
| `PVE_TUI_SITES_CSV` | Path to your sites file | `./sites.csv` |
| `PVE_TUI_LOGO` | Logo to embed in PDF reports | none |
| `PVE_TUI_OUTDIR` | Where reports are saved | `~/reports` |
| `PVE_TUI_TITLE` | TUI header title | `Proxmox Site Manager` |
| `PVE_TUI_GROUP_LABEL` | Label for the grouping level | `Group` |
| `PVE_REPORT_ORG` | Organization name in report header | `Infrastructure IT` |
| `PVE_REPORT_AUTHOR` | Name in report footer | `Infrastructure IT` |
| `PVE_REPORT_COLOR_HEADER` | Primary color `R,G,B` | `0,86,162` |

---

## Zabbix integration

If your clusters are monitored in Zabbix via the **Proxmox VE by HTTP** template, you can generate `sites.csv` automatically:

```bash
export ZABBIX_URL="https://your-zabbix/api_jsonrpc.php"
export ZABBIX_TOKEN="your-api-token"

python3 extract_sites_from_zabbix.py --dry-run   # check before writing
python3 extract_sites_from_zabbix.py --out sites.csv
```

The script expects:
- One hostgroup per site named `DATACENTER/<SITE>` containing the PVE cluster host
- The cluster host monitored via **Proxmox VE by HTTP**, with `{$PVE.URL.HOST}` set to the node IP
- Region/group hostgroups named `PBS-SITE-<GROUP>` (e.g. `PBS-SITE-NORTH`)

These conventions are fully configurable at the top of the script — adapt them to your Zabbix naming.

---

## Authentication

**Interactive**: username and password prompted at runtime.

**CI/CD**: use a Proxmox API token instead:

```yaml
# .gitlab-ci.yml example
generate_report:
  stage: report
  script:
    - pip install requests urllib3 fpdf2 paramiko
    - python3 proxmox_report.py --host $PVE_HOST --site $PVE_SITE
  artifacts:
    paths: ["*.pdf"]
    expire_in: 30 days
  only:
    - schedules
```

Set `PVE_TOKEN_USER`, `PVE_TOKEN_ID`, and `PVE_TOKEN_SECRET` as CI variables.

---

## Project structure

```
proxmox-report-generator/
├── tui.py                        # Terminal UI
├── proxmox_report.py             # PDF report engine
├── extract_sites_from_zabbix.py  # Zabbix → sites.csv
├── sites.csv.example             # Template — copy to sites.csv
├── .gitignore
└── README.md
```

---

## Contributing

Issues and pull requests are welcome.

## License

MIT
