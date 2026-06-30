#!/usr/bin/env python3
"""
extract_sites_from_zabbix.py — Génère sites.csv depuis l'API Zabbix
=====================================================================
Ce script interroge votre instance Zabbix pour construire automatiquement
le fichier sites.csv utilisé par tui.py et proxmox_report.py.

Il repose sur deux conventions de nommage Zabbix (adaptables) :

  1. Un hostgroup par site, dont le nom contient le code site
     (ex: "DATACENTER/SITE1"). Chaque groupe contient un host
     "*-PVE-CLUSTER" monitoré via le template "Proxmox VE by HTTP".
     L'IP de l'API Proxmox est stockée dans la macro {$PVE.URL.HOST}.

  2. Des hostgroups de région (ex: "PBS-SITE-REGION-A",
     "PBS-SITE-REGION-B") regroupant les hosts d'une même région.
     Ces groupes servent à déduire la région de chaque site.

Si votre structure Zabbix diffère, adaptez les constantes
DATACENTER_PREFIX, REGION_GROUP_PATTERN et PVE_URL_MACRO ci-dessous
sans toucher au reste du code.

Pré-requis :
  export ZABBIX_URL="https://votre-zabbix/api_jsonrpc.php"
  export ZABBIX_TOKEN="votre-token-api"

Usage :
  python3 extract_sites_from_zabbix.py --dry-run    # aperçu sans écrire
  python3 extract_sites_from_zabbix.py --out sites.csv
"""

import argparse
import csv
import os
import re
import sys

import requests

# ─── Configuration — adapter à votre instance Zabbix ──────────────────────────
ZABBIX_URL = os.environ.get("ZABBIX_URL", "https://zabbix.example.com/api_jsonrpc.php")
ZABBIX_TOKEN = os.environ.get("ZABBIX_TOKEN")

HEADERS = {
    "Content-Type": "application/json-rpc",
    "Authorization": f"Bearer {ZABBIX_TOKEN}" if ZABBIX_TOKEN else "",
}

# Préfixe des hostgroups "site" dans Zabbix (ex: "DATACENTER/SITE1")
DATACENTER_PREFIX = "DATACENTER/"

# Pattern des hostgroups de région (ex: "PBS-SITE-REGION-A" -> "REGION-A")
REGION_GROUP_PATTERN = re.compile(r"^PBS-SITE-(\w+)$")

# Macro d'hôte contenant l'IP/URL de l'API Proxmox (template Proxmox VE by HTTP)
PVE_URL_MACRO = "{$PVE.URL.HOST}"
# ──────────────────────────────────────────────────────────────────────────────


def zbx_call(method: str, params: dict) -> dict:
    payload = {"jsonrpc": "2.0", "method": method, "params": params, "id": 1}
    resp = requests.post(ZABBIX_URL, headers=HEADERS, json=payload, verify=False, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    if "error" in data:
        raise RuntimeError(f"Zabbix API error: {data['error']}")
    return data["result"]


def extract_site_code(group_name: str) -> str:
    """DATACENTER/HIA -> HIA"""
    return group_name.split("/", 1)[-1].strip().upper()


def extract_cluster_host(host_name: str):
    """Repère le host *-PVE-CLUSTER dans une liste de hosts d'un groupe DATACENTER."""
    m = re.search(r"PVE-CLUSTER$", host_name.upper())
    return bool(m)


def build_region_map() -> dict:
    """Retourne {site_code: region} à partir des groupes PBS-SITE-*."""
    groups = zbx_call("hostgroup.get", {
        "output": ["groupid", "name"],
        "selectHosts": ["host"],
    })

    region_map = {}
    for g in groups:
        m = REGION_GROUP_PATTERN.match(g["name"])
        if not m:
            continue
        region = m.group(1)
        for h in g.get("hosts", []):
            # nom host PBS type "001-HIA-PBS-01" -> site HIA
            parts = re.split(r"[-_]", h["host"].upper())
            for p in parts:
                if p.isalpha() and len(p) >= 2 and p not in ("PBS",):
                    region_map.setdefault(p, region)
                    break
    return region_map


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", default="sites.csv", help="Fichier CSV de sortie (défaut: sites.csv)")
    parser.add_argument("--dry-run", action="store_true", help="Affiche le résultat sans écrire de fichier")
    args = parser.parse_args()

    if not ZABBIX_TOKEN:
        print("[ERREUR] Variable ZABBIX_TOKEN absente. Faire 'source ~/.bashrc' ou l'exporter.", file=sys.stderr)
        sys.exit(1)

    print(f"[INFO] Connexion à {ZABBIX_URL}...")

    print(f"[INFO] Construction de la table de région (groupes PBS-SITE-*)...")
    region_map = build_region_map()
    print(f"[INFO] {len(region_map)} site(s) avec région connue : {sorted(region_map.items())}")

    print(f"[INFO] Recherche des groupes {DATACENTER_PREFIX}*...")
    groups = zbx_call("hostgroup.get", {
        "output": ["groupid", "name"],
        "selectHosts": ["host", "name"],
    })
    dc_groups = [g for g in groups if g["name"].startswith(DATACENTER_PREFIX)]
    print(f"[INFO] {len(dc_groups)} groupe(s) {DATACENTER_PREFIX}* trouvé(s).")

    # On a besoin des IP : un appel host.get supplémentaire sur les hostids des clusters trouvés
    cluster_hostids = []
    cluster_meta = {}  # hostid -> (site_code, cluster_name)
    for g in dc_groups:
        site_code = extract_site_code(g["name"])
        for h in g.get("hosts", []):
            if extract_cluster_host(h["host"]):
                cluster_hostids.append(h["hostid"])
                cluster_meta[h["hostid"]] = (site_code, h["host"])

    print(f"[INFO] {len(cluster_hostids)} host(s) *-PVE-CLUSTER identifié(s) dans les groupes DATACENTER.")

    rows = []
    unresolved_region = []
    unresolved_ip = []
    if cluster_hostids:
        hosts_detail = zbx_call("host.get", {
            "output": ["hostid", "host"],
            "hostids": cluster_hostids,
            "selectMacros": "extend",
        })
        for h in hosts_detail:
            site_code, cluster_name = cluster_meta[h["hostid"]]
            ip = ""
            for macro in h.get("macros", []):
                if macro["macro"] == PVE_URL_MACRO:
                    ip = macro["value"]
                    break
            if not ip:
                unresolved_ip.append(site_code)
            region = region_map.get(site_code, "")
            if not region:
                unresolved_region.append(site_code)
            rows.append({"site": site_code, "host": ip, "cluster": cluster_name, "group": region})

    rows.sort(key=lambda r: (r["group"], r["site"]))

    print(f"\n[INFO] {len(rows)} site(s) extrait(s) :")
    print(f"  {'SITE':<10}{'HOST':<18}{'CLUSTER':<28}{'GROUP'}")
    for r in rows:
        print(f"  {r['site']:<10}{r['host']:<18}{r['cluster']:<28}{r['group']}")

    if unresolved_region:
        print(f"\n[WARN] Région non résolue pour : {sorted(set(unresolved_region))}")
        print("  => Complétez la colonne 'group' manuellement pour ces lignes.")

    if unresolved_ip:
        print(f"\n[WARN] IP (macro {PVE_URL_MACRO}) non trouvée pour : {sorted(set(unresolved_ip))}")
        print("  => Ces lignes auront un champ 'host' vide ; à compléter manuellement,")
        print("     ou vérifier que ces hosts utilisent bien le template Proxmox VE by HTTP.")

    if args.dry_run:
        print(f"\n[INFO] Mode --dry-run : aucun fichier écrit.")
        return

    with open(args.out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["site", "host", "cluster", "group"])
        writer.writeheader()
        writer.writerows(rows)

    print(f"\n[OK] Fichier généré : {args.out}")


if __name__ == "__main__":
    main()
