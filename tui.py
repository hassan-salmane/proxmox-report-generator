#!/usr/bin/env python3
"""
tui.py — Interface Terminal générique pour gestion multi-sites Proxmox
========================================================================
Navigation : ↑↓ flèches | Enter sélectionner | Q quitter

Auteur : projet communautaire — contributions bienvenues

Le fichier sites.csv accepte une colonne optionnelle "group" (région, client,
environnement... selon le contexte d'usage). Si absente, tous les sites sont
affichés à plat sous un groupe générique. Cette colonne ne porte aucune
signification métier figée — elle sert juste à organiser l'affichage et à
permettre une génération de rapports en masse par groupe.

Configuration (variables d'environnement, toutes optionnelles) :
  PVE_TUI_SITES_CSV   Chemin du fichier CSV des sites (défaut: ./sites.csv)
  PVE_TUI_REPORT      Chemin du script de génération de rapport (défaut: ./proxmox_report.py)
  PVE_TUI_LOGO        Chemin du logo à inclure dans les rapports PDF (optionnel)
  PVE_TUI_OUTDIR      Dossier de sortie des rapports (défaut: ~/rapports)
  PVE_TUI_TITLE       Titre affiché en en-tête de l'interface (défaut générique)
  PVE_TUI_GROUP_LABEL Libellé du regroupement (ex: "Région", "Client", "Environnement")
  PVE_REPORT_ORG      Nom d'organisation affiché dans l'en-tête des rapports PDF
  PVE_REPORT_AUTHOR   Nom affiché en pied de page des rapports PDF

Format sites.csv :
  site,host,cluster[,group]
  SITE1,192.0.2.10,cluster-name-1,REGION-A
  SITE2,192.0.2.20,cluster-name-2,REGION-B
"""

import csv
import curses
import getpass
import os
import subprocess
import sys
import platform
from dataclasses import dataclass
from pathlib import Path
from typing import List, Union

# ─── Config ───────────────────────────────────────────────────────────────────
SCRIPT_DIR    = Path(__file__).parent
SITES_CSV     = Path(os.environ.get("PVE_TUI_SITES_CSV", SCRIPT_DIR / "sites.csv"))
REPORT_SCRIPT = Path(os.environ.get("PVE_TUI_REPORT", SCRIPT_DIR / "proxmox_report.py"))
LOGO_PATH     = Path(os.environ["PVE_TUI_LOGO"]) if os.environ.get("PVE_TUI_LOGO") else None
OUTPUT_DIR    = Path(os.environ.get("PVE_TUI_OUTDIR", Path.home() / "rapports"))
APP_TITLE     = os.environ.get("PVE_TUI_TITLE", "Gestionnaire de sites Proxmox")
GROUP_LABEL   = os.environ.get("PVE_TUI_GROUP_LABEL", "Groupe")
NO_GROUP      = "Tous les sites"

# Couleurs (index curses)
C_HEADER     = 1
C_SELECTED   = 2
C_NORMAL     = 3
C_STATUS_OK  = 4
C_STATUS_ERR = 5
C_TITLE      = 6
C_DIM        = 7
C_GROUP      = 8


@dataclass
class Site:
    site: str
    host: str
    cluster: str
    group: str = NO_GROUP


@dataclass
class GroupHeader:
    """Ligne non sélectionnable séparant les groupes dans la liste."""
    name: str
    count: int


ListItem = Union[Site, GroupHeader]


def load_sites(csv_path: Path) -> List[Site]:
    sites = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        has_group = bool(reader.fieldnames) and "group" in reader.fieldnames
        for row in reader:
            sites.append(Site(
                site=row["site"].strip(),
                host=row["host"].strip(),
                cluster=row["cluster"].strip(),
                group=((row.get("group") or "").strip() or NO_GROUP) if has_group else NO_GROUP,
            ))
    return sorted(sites, key=lambda s: (s.group, s.site))


def build_display_list(sites: List[Site]) -> List[ListItem]:
    """Construit la liste affichée : en-têtes de groupe + sites, triés par groupe."""
    groups_present = sorted(set(s.group for s in sites))
    if groups_present == [NO_GROUP]:
        return list(sites)

    items: List[ListItem] = []
    for g in groups_present:
        group_sites = [s for s in sites if s.group == g]
        items.append(GroupHeader(name=g, count=len(group_sites)))
        items.extend(group_sites)
    return items


def init_colors():
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(C_HEADER,     curses.COLOR_WHITE,  curses.COLOR_BLUE)
    curses.init_pair(C_SELECTED,   curses.COLOR_WHITE,  curses.COLOR_BLUE)
    curses.init_pair(C_NORMAL,     curses.COLOR_WHITE,  -1)
    curses.init_pair(C_STATUS_OK,  curses.COLOR_GREEN,  -1)
    curses.init_pair(C_STATUS_ERR, curses.COLOR_RED,    -1)
    curses.init_pair(C_TITLE,      curses.COLOR_CYAN,   -1)
    curses.init_pair(C_DIM,        curses.COLOR_BLACK,  -1)
    curses.init_pair(C_GROUP,      curses.COLOR_YELLOW, -1)


def draw_header(stdscr, rows, cols):
    header = f" {APP_TITLE} "
    try:
        stdscr.attron(curses.color_pair(C_HEADER) | curses.A_BOLD)
        stdscr.addstr(0, 0, " " * (cols - 1))
        x = max(0, (cols - len(header)) // 2)
        stdscr.addstr(0, x, header[:cols - 1])
        stdscr.attroff(curses.color_pair(C_HEADER) | curses.A_BOLD)
    except Exception:
        pass

    sub = " Naviguer: fleches haut/bas   Selectionner: Enter   Quitter: Q "
    try:
        stdscr.attron(curses.color_pair(C_DIM))
        stdscr.addstr(1, max(0, (cols - len(sub)) // 2), sub[:cols - 1])
        stdscr.attroff(curses.color_pair(C_DIM))
    except Exception:
        pass


def draw_sites(stdscr, items: List[ListItem], selected: int, top: int, list_y: int, list_h: int, cols: int):
    stdscr.attron(curses.color_pair(C_HEADER) | curses.A_BOLD)
    header_line = f"  {'SITE':<10}{'HOST':<20}{'CLUSTER':<35}"
    stdscr.addstr(list_y, 0, header_line[:cols].ljust(cols))
    stdscr.attroff(curses.color_pair(C_HEADER) | curses.A_BOLD)

    visible = min(list_h, len(items) - top)
    for i in range(visible):
        idx  = top + i
        item = items[idx]
        y    = list_y + 1 + i

        if isinstance(item, GroupHeader):
            line = f" ▾ {GROUP_LABEL} : {item.name} ({item.count} site(s)) — Enter: rapport groupé"
            line = line[:cols].ljust(cols)
            try:
                stdscr.attron(curses.color_pair(C_GROUP) | curses.A_BOLD)
                stdscr.addstr(y, 0, line[:cols - 1].ljust(cols - 1))
                stdscr.attroff(curses.color_pair(C_GROUP) | curses.A_BOLD)
            except Exception:
                pass
            continue

        site = item
        line = f"  {site.site:<10}{site.host:<20}{site.cluster:<35}"
        line = line[:cols].ljust(cols)

        try:
            if idx == selected:
                stdscr.attron(curses.color_pair(C_SELECTED) | curses.A_BOLD)
                stdscr.addstr(y, 0, line[:cols - 1].ljust(cols - 1))
                stdscr.attroff(curses.color_pair(C_SELECTED) | curses.A_BOLD)
            else:
                stdscr.attron(curses.color_pair(C_NORMAL))
                stdscr.addstr(y, 0, line[:cols - 1].ljust(cols - 1))
                stdscr.attroff(curses.color_pair(C_NORMAL))
        except Exception:
            pass

    total = len(items)
    if total > list_h:
        pct = int((selected / max(total - 1, 1)) * (list_h - 1))
        for i in range(list_h):
            sym = "█" if i == pct else "│"
            try:
                stdscr.addstr(list_y + 1 + i, cols - 1, sym)
            except Exception:
                pass


def draw_footer(stdscr, rows, cols, item: ListItem):
    if isinstance(item, GroupHeader):
        info = f" {GROUP_LABEL} selectionne : {item.name}  |  {item.count} site(s)  |  Enter = rapport groupe "
    else:
        info = f" Site selectionne : {item.site}  |  {item.host}  |  {item.cluster} "
    safe = info[:cols - 1].ljust(cols - 1)
    try:
        stdscr.attron(curses.color_pair(C_HEADER))
        stdscr.addstr(rows - 1, 0, safe)
        stdscr.attroff(curses.color_pair(C_HEADER))
    except Exception:
        pass


def show_message(stdscr, rows, cols, msg: str, color=C_STATUS_OK, wait=True):
    y = rows - 2
    stdscr.attron(curses.color_pair(color) | curses.A_BOLD)
    stdscr.addstr(y, 0, msg[:cols].ljust(cols))
    stdscr.attroff(curses.color_pair(color) | curses.A_BOLD)
    stdscr.refresh()
    if wait:
        stdscr.getch()


# ─── Menu d'actions (site unique) ──────────────────────────────────────────────
ACTIONS = [
    ("pdf",   "📄  Générer rapport PDF"),
    ("ping",  "🔗  Ping du nœud principal"),
    ("info",  "ℹ️   Infos rapides (version PVE, nœuds)"),
    ("ssh",   "🖥️   Ouvrir SSH vers le nœud"),
    ("back",  "← Retour à la liste"),
]


def draw_action_menu(stdscr, rows, cols, site: Site, selected_action: int):
    stdscr.clear()

    stdscr.attron(curses.color_pair(C_HEADER) | curses.A_BOLD)
    h = f" Site {site.site} | {site.host} "
    stdscr.addstr(0, max(0, (cols - len(h)) // 2), h[:cols])
    stdscr.attroff(curses.color_pair(C_HEADER) | curses.A_BOLD)

    stdscr.attron(curses.color_pair(C_DIM))
    info = f" Cluster : {site.cluster}"
    if site.group != NO_GROUP:
        info += f"  |  {GROUP_LABEL} : {site.group}"
    info += " "
    stdscr.addstr(1, max(0, (cols - len(info)) // 2), info[:cols])
    stdscr.attroff(curses.color_pair(C_DIM))

    stdscr.addstr(2, 0, "─" * min(cols, 80))

    stdscr.attron(curses.color_pair(C_TITLE) | curses.A_BOLD)
    stdscr.addstr(4, 4, "Choisissez une action :")
    stdscr.attroff(curses.color_pair(C_TITLE) | curses.A_BOLD)

    for i, (key, label) in enumerate(ACTIONS):
        y = 6 + i * 2
        if i == selected_action:
            stdscr.attron(curses.color_pair(C_SELECTED) | curses.A_BOLD)
            stdscr.addstr(y, 4, f"  ▶  {label}  ".ljust(40))
            stdscr.attroff(curses.color_pair(C_SELECTED) | curses.A_BOLD)
        else:
            stdscr.attron(curses.color_pair(C_NORMAL))
            stdscr.addstr(y, 4, f"     {label}  ".ljust(40))
            stdscr.attroff(curses.color_pair(C_NORMAL))

    try:
        stdscr.attron(curses.color_pair(C_HEADER))
        footer = " Naviguer: fleches   Executer: Enter   Retour: Q "
        stdscr.addstr(rows - 1, 0, footer[:cols - 1].ljust(cols - 1))
        stdscr.attroff(curses.color_pair(C_HEADER))
    except Exception:
        pass

    stdscr.refresh()


# ─── Menu d'actions (groupe / tous les sites) ──────────────────────────────────
BATCH_ACTIONS = [
    ("pdf_batch", "📄  Générer un rapport PDF pour chaque site"),
    ("back",      "← Retour à la liste"),
]


def draw_batch_menu(stdscr, rows, cols, label: str, sites: List[Site], selected_action: int):
    stdscr.clear()

    stdscr.attron(curses.color_pair(C_HEADER) | curses.A_BOLD)
    h = f" {label} — {len(sites)} site(s) "
    stdscr.addstr(0, max(0, (cols - len(h)) // 2), h[:cols])
    stdscr.attroff(curses.color_pair(C_HEADER) | curses.A_BOLD)

    stdscr.attron(curses.color_pair(C_DIM))
    names = ", ".join(s.site for s in sites)
    info = f" Sites concernes : {names} "
    stdscr.addstr(1, max(0, (cols - len(info)) // 2), info[:min(len(info), cols)])
    stdscr.attroff(curses.color_pair(C_DIM))

    stdscr.addstr(2, 0, "─" * min(cols, 80))

    stdscr.attron(curses.color_pair(C_TITLE) | curses.A_BOLD)
    stdscr.addstr(4, 4, "Choisissez une action :")
    stdscr.attroff(curses.color_pair(C_TITLE) | curses.A_BOLD)

    for i, (key, label_) in enumerate(BATCH_ACTIONS):
        y = 6 + i * 2
        if i == selected_action:
            stdscr.attron(curses.color_pair(C_SELECTED) | curses.A_BOLD)
            stdscr.addstr(y, 4, f"  ▶  {label_}  ".ljust(50))
            stdscr.attroff(curses.color_pair(C_SELECTED) | curses.A_BOLD)
        else:
            stdscr.attron(curses.color_pair(C_NORMAL))
            stdscr.addstr(y, 4, f"     {label_}  ".ljust(50))
            stdscr.attroff(curses.color_pair(C_NORMAL))

    try:
        stdscr.attron(curses.color_pair(C_HEADER))
        footer = " Naviguer: fleches   Executer: Enter   Retour: Q "
        stdscr.addstr(rows - 1, 0, footer[:cols - 1].ljust(cols - 1))
        stdscr.attroff(curses.color_pair(C_HEADER))
    except Exception:
        pass

    stdscr.refresh()


# ─── Actions ──────────────────────────────────────────────────────────────────
def run_outside_curses(stdscr, func):
    curses.endwin()
    try:
        func()
    finally:
        stdscr.refresh()
        curses.doupdate()


def _generate_pdf_for_site(module, site: Site, username: str, password: str) -> Path:
    import datetime as dt
    auth = {
        "mode": "ticket",
        "username": username,
        "password": password,
        "token_user": None,
        "token_id": None,
        "token_secret": None,
    }
    api = module.ProxmoxAPI(host=site.host, auth=auth, verify_ssl=False)
    api.login()

    pdf_bytes = module.build_report(
        api, site.site,
        str(LOGO_PATH) if (LOGO_PATH and LOGO_PATH.exists()) else None,
        False, None,
    )
    date_str = dt.datetime.now().strftime("%Y%m%d_%H%M")
    outfile  = OUTPUT_DIR / f"Proxmox_{site.site}_{date_str}.pdf"
    outfile.write_bytes(pdf_bytes)
    return outfile


def _load_report_module():
    import importlib.util
    spec   = importlib.util.spec_from_file_location("proxmox_report", REPORT_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def action_pdf(stdscr, site: Site):
    def _run():
        print(f"\n{'='*60}")
        print(f"  Génération PDF — Site {site.site}")
        print(f"{'='*60}")
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

        username = input(f"Proxmox username [{site.host}] (ex: root@pam) : ").strip() or "root@pam"
        password = getpass.getpass(f"Proxmox password ({username}) : ")

        print(f"\n[INFO] Lancement du rapport pour {site.site}...")
        sys.path.insert(0, str(SCRIPT_DIR))
        try:
            module = _load_report_module()
            outfile = _generate_pdf_for_site(module, site, username, password)
            print(f"\n[OK] Rapport sauvegardé : {outfile}")
        except Exception as e:
            print(f"\n[ERREUR] {e}")
        finally:
            if str(SCRIPT_DIR) in sys.path:
                sys.path.remove(str(SCRIPT_DIR))

        input("\nAppuyez sur Entrée pour continuer...")

    run_outside_curses(stdscr, _run)


def action_pdf_batch(stdscr, label: str, sites: List[Site]):
    """Génère un rapport PDF pour chaque site du lot (groupe ou totalité)."""
    def _run():
        print(f"\n{'='*60}")
        print(f"  Génération PDF en masse — {label}")
        print(f"  {len(sites)} site(s) : {', '.join(s.site for s in sites)}")
        print(f"{'='*60}")
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

        same_creds = input("Utiliser les mêmes identifiants pour tous les sites ? [o/N] : ").strip().lower()
        shared_username = shared_password = None
        if same_creds == "o":
            shared_username = input("Proxmox username (ex: root@pam) : ").strip() or "root@pam"
            shared_password = getpass.getpass(f"Proxmox password ({shared_username}) : ")

        sys.path.insert(0, str(SCRIPT_DIR))
        results = []
        try:
            module = _load_report_module()
            for site in sites:
                print(f"\n--- {site.site} ({site.host}) ---")
                if shared_username is not None:
                    username, password = shared_username, shared_password
                else:
                    username = input(f"  Username [{site.host}] (ex: root@pam) : ").strip() or "root@pam"
                    password = getpass.getpass(f"  Password ({username}) : ")
                try:
                    outfile = _generate_pdf_for_site(module, site, username, password)
                    print(f"  [OK] {outfile}")
                    results.append((site.site, True, str(outfile)))
                except Exception as e:
                    print(f"  [ERREUR] {e}")
                    results.append((site.site, False, str(e)))
        finally:
            if str(SCRIPT_DIR) in sys.path:
                sys.path.remove(str(SCRIPT_DIR))

        ok = sum(1 for _, success, _ in results if success)
        print(f"\n{'='*60}")
        print(f"  Bilan : {ok}/{len(results)} rapport(s) généré(s) avec succès")
        for name, success, detail in results:
            mark = "OK " if success else "ECHEC"
            print(f"    [{mark}] {name} — {detail}")
        print(f"{'='*60}")

        input("\nAppuyez sur Entrée pour continuer...")

    run_outside_curses(stdscr, _run)


def action_ping(stdscr, site: Site):
    def _run():
        print(f"\n{'='*60}")
        print(f"  Ping — {site.site} ({site.host})")
        print(f"{'='*60}\n")
        param = "-n" if platform.system().lower() == "windows" else "-c"
        result = subprocess.run(["ping", param, "4", site.host], text=True)
        print(f"\nCode retour : {'OK ✓' if result.returncode == 0 else 'ÉCHEC ✗'}")
        input("\nAppuyez sur Entrée pour continuer...")

    run_outside_curses(stdscr, _run)


def action_info(stdscr, site: Site):
    def _run():
        print(f"\n{'='*60}")
        print(f"  Infos rapides — Site {site.site} ({site.host})")
        print(f"{'='*60}\n")

        username = input(f"Proxmox username (ex: root@pam) : ").strip() or "root@pam"
        password = getpass.getpass(f"Proxmox password ({username}) : ")

        sys.path.insert(0, str(SCRIPT_DIR))
        try:
            module = _load_report_module()

            auth = {"mode": "ticket", "username": username, "password": password,
                    "token_user": None, "token_id": None, "token_secret": None}
            api = module.ProxmoxAPI(host=site.host, auth=auth, verify_ssl=False)
            api.login()

            summary = module.get_cluster_summary(api)
            nodes   = api.nodes()
            vms     = api.cluster_resources_vm()
            qemu    = [v for v in vms if v.get("type") == "qemu"]
            lxc     = [v for v in vms if v.get("type") == "lxc"]
            running = [v for v in qemu if v.get("status") == "running"]

            print(f"\n  Cluster      : {summary['name']}")
            print(f"  Version PVE  : {summary['version']}")
            print(f"  Quorum       : {summary['quorum']}")
            print(f"  Nœuds        : {summary['nodes_online']}/{summary['nodes_total']} en ligne")
            print(f"  VMs QEMU     : {len(qemu)} total  ({len(running)} running)")
            print(f"  Conteneurs   : {len(lxc)}")
            print()
            print(f"  {'NŒUD':<20} {'STATUT':<10} {'CPU':>6} {'RAM':>8}")
            print(f"  {'─'*20} {'─'*10} {'─'*6} {'─'*8}")
            for n in nodes:
                name = n.get("node", "-")
                try:
                    ns   = api.node_status(name)
                    cpu  = f"{ns.get('cpu', 0)*100:.1f}%"
                    mem  = ns.get("memory", {})
                    ram  = f"{module.pct(mem.get('used',0), mem.get('total',1)):.0f}%"
                except Exception:
                    cpu = ram = "-"
                status = n.get("status", "-")
                print(f"  {name:<20} {status:<10} {cpu:>6} {ram:>8}")

        except Exception as e:
            print(f"\n[ERREUR] {e}")
        finally:
            if str(SCRIPT_DIR) in sys.path:
                sys.path.remove(str(SCRIPT_DIR))

        input("\nAppuyez sur Entrée pour continuer...")

    run_outside_curses(stdscr, _run)


def action_ssh(stdscr, site: Site):
    def _run():
        print(f"\n[SSH] Connexion vers root@{site.host}...\n")
        os.execlp("ssh", "ssh", "-o", "StrictHostKeyChecking=no", f"root@{site.host}")

    run_outside_curses(stdscr, _run)


# ─── Boucles de menu ────────────────────────────────────────────────────────────
def action_menu_loop(stdscr, site: Site):
    """Boucle du menu d'actions pour un site unique."""
    selected = 0
    while True:
        rows, cols = stdscr.getmaxyx()
        draw_action_menu(stdscr, rows, cols, site, selected)
        key = stdscr.getch()

        if key == curses.KEY_UP:
            selected = (selected - 1) % len(ACTIONS)
        elif key == curses.KEY_DOWN:
            selected = (selected + 1) % len(ACTIONS)
        elif key in (curses.KEY_ENTER, ord("\n"), ord("\r")):
            action_key = ACTIONS[selected][0]
            if action_key == "back":
                return
            elif action_key == "pdf":
                action_pdf(stdscr, site)
            elif action_key == "ping":
                action_ping(stdscr, site)
            elif action_key == "info":
                action_info(stdscr, site)
            elif action_key == "ssh":
                action_ssh(stdscr, site)
                return
        elif key in (ord("q"), ord("Q")):
            return


def batch_menu_loop(stdscr, label: str, sites: List[Site]):
    """Boucle du menu d'actions pour un groupe (ou tous les sites)."""
    selected = 0
    while True:
        rows, cols = stdscr.getmaxyx()
        draw_batch_menu(stdscr, rows, cols, label, sites, selected)
        key = stdscr.getch()

        if key == curses.KEY_UP:
            selected = (selected - 1) % len(BATCH_ACTIONS)
        elif key == curses.KEY_DOWN:
            selected = (selected + 1) % len(BATCH_ACTIONS)
        elif key in (curses.KEY_ENTER, ord("\n"), ord("\r")):
            action_key = BATCH_ACTIONS[selected][0]
            if action_key == "back":
                return
            elif action_key == "pdf_batch":
                action_pdf_batch(stdscr, label, sites)
        elif key in (ord("q"), ord("Q")):
            return


def main_loop(stdscr, sites: List[Site]):
    """Boucle principale — liste des sites (avec en-têtes de groupe si présents)."""
    curses.curs_set(0)
    init_colors()

    selected = 0
    top      = 0

    base_items = build_display_list(sites)
    has_groups = any(isinstance(i, GroupHeader) for i in base_items)

    extra: List[ListItem] = []
    if has_groups:
        extra.append(GroupHeader(name=NO_GROUP, count=len(sites)))
    quit_site = Site(site="── Quitter ──", host="", cluster="", group=NO_GROUP)
    all_items = base_items + extra + [quit_site]

    while selected < len(all_items) and isinstance(all_items[selected], GroupHeader):
        selected += 1

    while True:
        items = all_items
        stdscr.clear()
        rows, cols = stdscr.getmaxyx()

        list_y = 3
        list_h = rows - list_y - 2

        draw_header(stdscr, rows, cols)
        draw_sites(stdscr, items, selected, top, list_y, list_h, cols)
        draw_footer(stdscr, rows, cols, items[selected])

        stdscr.refresh()
        key = stdscr.getch()

        if key == curses.KEY_UP:
            if selected > 0:
                selected -= 1
                if selected < top:
                    top -= 1
        elif key == curses.KEY_DOWN:
            if selected < len(items) - 1:
                selected += 1
                if selected >= top + list_h:
                    top += 1
        elif key in (curses.KEY_ENTER, ord("\n"), ord("\r")):
            current = items[selected]
            if isinstance(current, Site) and current.host == "":
                break
            elif isinstance(current, GroupHeader):
                if current.name == NO_GROUP:
                    batch_menu_loop(stdscr, NO_GROUP, sites)
                else:
                    group_sites = [s for s in sites if s.group == current.name]
                    batch_menu_loop(stdscr, f"{GROUP_LABEL} {current.name}", group_sites)
            else:
                action_menu_loop(stdscr, current)
        elif key in (ord("q"), ord("Q"), 27):
            break


def main():
    if not SITES_CSV.exists():
        print(f"[ERREUR] Fichier de sites introuvable : {SITES_CSV}")
        sys.exit(1)
    if not REPORT_SCRIPT.exists():
        print(f"[ERREUR] Script rapport introuvable : {REPORT_SCRIPT}")
        sys.exit(1)

    sites = load_sites(SITES_CSV)
    if not sites:
        print("[ERREUR] Aucun site trouvé dans le CSV.")
        sys.exit(1)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    try:
        curses.wrapper(main_loop, sites)
    except KeyboardInterrupt:
        pass
    print("\nAu revoir\n")


if __name__ == "__main__":
    main()
