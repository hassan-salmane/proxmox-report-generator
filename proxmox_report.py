#!/usr/bin/env python3
"""
ProxmoxReportGenerator - Générique multi-sites
================================================
Basé sur : https://github.com/AungThuMyint/ProxmoxReportGenerator
Outil open-source, contributions bienvenues

Authentification sécurisée :
  - Mode CI/CD  : variables d'environnement PVE_TOKEN_USER, PVE_TOKEN_ID, PVE_TOKEN_SECRET
  - Mode manuel : getpass interactif (aucun credential en clair)

Usage :
  python proxmox_report.py --host 192.0.2.10 --site SITE1 --logo /chemin/logo.png
  python proxmox_report.py --host 192.0.2.10 --site SITE1 --logo /chemin/logo.png --ssh
  python proxmox_report.py --host 192.0.2.10 --site SITE1 --logo /chemin/logo.png --insecure
"""

import argparse
import datetime as dt
import getpass
import io
import os
import re
import sys
from typing import Any, Dict, List, Optional, Tuple

import requests
import urllib3
from fpdf import FPDF
from fpdf.enums import XPos, YPos

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ─── Constantes ────────────────────────────────────────────────────────────────
DEFAULT_REALM      = "pam"
VERIFY_SSL_DEFAULT = False
TIMEOUT            = 20
LOGO_W_MM          = 40
HEADER_GAP_MM      = 6
LOGO_CLEAR_H_MM    = 18

# Identité affichée dans le rapport — personnalisable sans toucher au code :
#   variables d'env PVE_REPORT_ORG / PVE_REPORT_AUTHOR, ou args --org/--author
ORG_NAME_DEFAULT    = os.environ.get("PVE_REPORT_ORG", "Infrastructure IT")
AUTHOR_DEFAULT      = os.environ.get("PVE_REPORT_AUTHOR", "Infrastructure IT")

# Couleurs du rapport — personnalisables via variables d'env (format "R,G,B")
def _color_from_env(var: str, default: tuple) -> tuple:
    val = os.environ.get(var)
    if not val:
        return default
    try:
        r, g, b = (int(x.strip()) for x in val.split(","))
        return (r, g, b)
    except Exception:
        return default

COLOR_HEADER_BG  = _color_from_env("PVE_REPORT_COLOR_HEADER", (0, 86, 162))
COLOR_HEADER_FG  = (255, 255, 255)
COLOR_ROW_ODD    = (240, 246, 255)
COLOR_ROW_EVEN   = (255, 255, 255)
COLOR_SECTION    = COLOR_HEADER_BG
COLOR_ACCENT     = _color_from_env("PVE_REPORT_COLOR_ACCENT", (0, 174, 239))


# ─── Utilitaires génériques ────────────────────────────────────────────────────
def parse_user_and_realm(user: str) -> Tuple[str, str]:
    if "@" in user:
        u, realm = user.split("@", 1)
        return f"{u}@{realm}", realm
    return f"{user}@{DEFAULT_REALM}", DEFAULT_REALM

def _to_gib(n: int) -> float:
    try:
        return float(n or 0) / (1024.0 ** 3)
    except Exception:
        return 0.0

def format_gib(n: int) -> str:
    g = _to_gib(n)
    if g < 10:
        return f"{g:.2f} GiB" if g < 1 else f"{g:.1f} GiB"
    return f"{g:.0f} GiB"

def pct(a: float, b: float) -> float:
    return (a / b) * 100.0 if b else 0.0

def secs_to_hms(seconds: int) -> str:
    d = dt.timedelta(seconds=int(seconds or 0))
    days = d.days
    h, rem = divmod(d.seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{days}d {h:02d}:{m:02d}:{s:02d}" if days else f"{h:02d}:{m:02d}:{s:02d}"

def clean_str(s: Optional[str]) -> str:
    return (s or "").strip().strip('"')

def join_nonempty(parts: List[str], sep=", ") -> str:
    return sep.join([p for p in parts if p])

def _parse_speed_to_mbps(val: Any) -> Optional[float]:
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val) if val > 0 else None
    s = str(val).strip().lower()
    if not s:
        return None
    m = re.search(r"(\d+(?:\.\d+)?)", s)
    if not m:
        return None
    num = float(m.group(1))
    if "gb" in s or "gbit" in s:
        return num * 1000.0
    if "mb" in s or "m/s" in s:
        return num
    return num

def _mbps_to_text(mbps: Optional[float]) -> str:
    if not mbps or mbps <= 0:
        return "-"
    if mbps >= 1000:
        g = mbps / 1000.0
        return f"{g:.1f} Gbps" if abs(g - round(g)) > 1e-6 else f"{int(round(g))} Gbps"
    return f"{int(round(mbps))} Mbps"

def _fmt_vcpu(v) -> str:
    if v is None:
        return "-"
    try:
        v = float(v)
        return "unlimited" if v <= 0 else f"{int(v) if abs(v - int(v)) < 1e-6 else v:g} vCPU"
    except Exception:
        return str(v)

def pair_gib(used: int, total: int) -> str:
    return f"{format_gib(used)}/{format_gib(total)} ({pct(used, total):.1f}%)"


# ─── Authentification sécurisée ───────────────────────────────────────────────
def resolve_auth(args) -> Dict[str, Optional[str]]:
    """
    Priorité :
      1. Variables d'environnement  → mode CI/CD GitLab
      2. Arguments --token-*        → token passé manuellement
      3. getpass interactif         → mode WSL/manuel (aucun credential en clair)
    """
    # 1. Env vars (GitLab CI/CD Variables)
    env_token_user   = os.environ.get("PVE_TOKEN_USER")
    env_token_id     = os.environ.get("PVE_TOKEN_ID")
    env_token_secret = os.environ.get("PVE_TOKEN_SECRET")

    if env_token_user and env_token_id and env_token_secret:
        print("[AUTH] Token API détecté via variables d'environnement (mode CI/CD)")
        return {
            "mode": "token",
            "token_user": env_token_user,
            "token_id": env_token_id,
            "token_secret": env_token_secret,
            "username": None,
            "password": None,
        }

    # 2. Token passé en arguments
    if args.token_id and args.token_secret and args.token_user:
        print("[AUTH] Token API détecté via arguments")
        return {
            "mode": "token",
            "token_user": args.token_user,
            "token_id": args.token_id,
            "token_secret": args.token_secret,
            "username": None,
            "password": None,
        }

    # 3. getpass interactif
    username = args.username or input(f"Proxmox username [{args.host}] (ex: root@pam) : ").strip()
    if not username:
        username = "root@pam"
    print(f"[AUTH] Authentification par ticket pour {username}@{args.host}")
    password = getpass.getpass(f"Proxmox password ({username}) : ")
    return {
        "mode": "ticket",
        "username": username,
        "password": password,
        "token_user": None,
        "token_id": None,
        "token_secret": None,
    }

def resolve_ssh_auth(args) -> Dict[str, Optional[str]]:
    """Résolution SSH : env vars → args → getpass interactif."""
    ssh_user = (
        os.environ.get("PVE_SSH_USER")
        or args.ssh_user
        or input("SSH username (ex: root) : ").strip()
        or "root"
    )
    # Clé SSH en priorité
    ssh_key = os.environ.get("PVE_SSH_KEY") or args.ssh_key
    if ssh_key:
        return {"ssh_user": ssh_user, "ssh_password": None, "ssh_key": ssh_key}

    # Sinon password
    ssh_password = os.environ.get("PVE_SSH_PASSWORD")
    if not ssh_password:
        ssh_password = getpass.getpass(f"SSH password ({ssh_user}@{args.host}) : ")
    return {"ssh_user": ssh_user, "ssh_password": ssh_password, "ssh_key": None}


# ─── Proxmox API ───────────────────────────────────────────────────────────────
class ProxmoxAPI:
    def __init__(self, host: str, auth: Dict, verify_ssl: bool = False, debug: bool = False):
        self.host    = host.strip().rstrip("/")
        self.base    = f"https://{self.host}:8006/api2/json"
        self.session = requests.Session()
        self.session.verify = verify_ssl
        self.debug   = debug
        self.auth    = auth
        self.ticket  = None
        self.csrf    = None

    def login(self):
        if self.auth["mode"] == "token":
            return  # Pas de login nécessaire avec token

        url  = f"{self.base}/access/ticket"
        data = {"username": self.auth["username"], "password": self.auth["password"]}
        r    = self.session.post(url, data=data, timeout=TIMEOUT)
        r.raise_for_status()
        j = r.json()["data"]
        self.ticket = j["ticket"]
        self.csrf   = j.get("CSRFPreventionToken")
        self.session.cookies.set("PVEAuthCookie", self.ticket)
        print(f"[AUTH] Authentifié avec succès sur {self.host}")

    def _headers(self) -> Dict:
        h = {"Accept": "application/json"}
        if self.auth["mode"] == "token":
            h["Authorization"] = (
                f"PVEAPIToken={self.auth['token_user']}!"
                f"{self.auth['token_id']}={self.auth['token_secret']}"
            )
        elif self.csrf:
            h["CSRFPreventionToken"] = self.csrf
        return h

    def get(self, path: str, params=None):
        url = f"{self.base}/{path.lstrip('/')}"
        r   = self.session.get(url, headers=self._headers(), params=params or {}, timeout=TIMEOUT)
        if self.debug and r.status_code >= 400:
            sys.stderr.write(f"[DEBUG] GET {url} → {r.status_code}\n{r.text}\n")
        r.raise_for_status()
        return r.json()["data"]

    def cluster_status(self):          return self.get("/cluster/status")
    def nodes(self):                   return self.get("/nodes")
    def node_status(self, node):       return self.get(f"/nodes/{node}/status")
    def node_network(self, node):      return self.get(f"/nodes/{node}/network")
    def cluster_resources_vm(self):    return self.get("/cluster/resources", params={"type": "vm"})
    def cluster_resources_storage(self): return self.get("/cluster/resources", params={"type": "storage"})
    def version(self):
        r = self.session.get(f"https://{self.host}:8006/api2/json/version", timeout=TIMEOUT)
        r.raise_for_status()
        return r.json()["data"]


# ─── SSH NIC speeds ────────────────────────────────────────────────────────────
def collect_nic_speeds_ssh(host: str, ssh_auth: Dict, port: int = 22, timeout: int = 8) -> Dict[str, float]:
    try:
        import paramiko
    except ImportError:
        sys.stderr.write("[WARN] paramiko non installé — vitesses NIC indisponibles. pip install paramiko\n")
        return {}

    speeds: Dict[str, float] = {}
    try:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        if ssh_auth.get("ssh_key"):
            client.connect(host, port=port, username=ssh_auth["ssh_user"],
                           key_filename=ssh_auth["ssh_key"], timeout=timeout)
        else:
            client.connect(host, port=port, username=ssh_auth["ssh_user"],
                           password=ssh_auth["ssh_password"], timeout=timeout)

        cmd = r"""for i in /sys/class/net/*; do
n=$(basename "$i"); s=$(cat "$i/speed" 2>/dev/null || echo -1); echo "S:$n:$s"
done"""
        _, stdout, _ = client.exec_command(cmd, timeout=timeout)
        for line in stdout.read().decode("utf-8", "ignore").splitlines():
            if line.startswith("S:"):
                _, iface, val = line.split(":", 2)
                try:
                    v = float(val)
                    if v > 0:
                        speeds[iface] = v
                except Exception:
                    pass
    except Exception as e:
        sys.stderr.write(f"[WARN] SSH échoué sur {host}: {e}\n")
        return {}
    finally:
        try:
            client.close()
        except Exception:
            pass
    return speeds


# ─── PDF ───────────────────────────────────────────────────────────────────────
class ReportPDF(FPDF):
    def __init__(self, site: str, org_name: str = None, author: str = None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.site         = site
        self.org_name     = org_name or ORG_NAME_DEFAULT
        self.author       = author or AUTHOR_DEFAULT
        self._logo_bytes  = None
        self._logo_stream = None

    def _latin1(self, s: str) -> str:
        """Convertit une chaîne unicode en latin-1 compatible fpdf2 core fonts."""
        if s is None:
            return ""
        # Table de translittération complète
        TRANS = {
            # Ponctuation unicode
            "\u2013": "-", "\u2014": "-", "\u2012": "-", "\u2212": "-",
            "\u2018": "'", "\u2019": "'", "\u201C": '"', "\u201D": '"',
            "\u2026": "...", "\u00A0": " ", "\u200B": "",
            "\u20AC": "EUR", "\u0153": "oe", "\u0152": "OE",
            # Minuscules accentuées
            "à": "a", "â": "a", "á": "a", "ä": "a",
            "è": "e", "é": "e", "ê": "e", "ë": "e",
            "î": "i", "ï": "i", "í": "i", "ì": "i",
            "ô": "o", "ö": "o", "ó": "o", "ò": "o",
            "ù": "u", "û": "u", "ú": "u", "ü": "u",
            "ç": "c", "ñ": "n", "œ": "oe", "æ": "ae",
            # Majuscules accentuées
            "À": "A", "Â": "A", "Á": "A", "Ä": "A",
            "È": "E", "É": "E", "Ê": "E", "Ë": "E",
            "Î": "I", "Ï": "I", "Í": "I", "Ì": "I",
            "Ô": "O", "Ö": "O", "Ó": "O", "Ò": "O",
            "Ù": "U", "Û": "U", "Ú": "U", "Ü": "U",
            "Ç": "C", "Ñ": "N", "Œ": "OE", "Æ": "AE",
        }
        result = []
        for ch in str(s):
            if ch in TRANS:
                result.append(TRANS[ch])
            else:
                try:
                    ch.encode("latin-1")
                    result.append(ch)
                except UnicodeEncodeError:
                    result.append("?")
        return "".join(result)

    def set_logo(self, logo_bytes: bytes):
        self._logo_bytes  = logo_bytes
        self._logo_stream = io.BytesIO(logo_bytes)

    def header(self):
        left, top = self.l_margin, self.t_margin

        # Logo à droite
        if self._logo_bytes:
            x_logo = self.w - self.r_margin - LOGO_W_MM
            try:
                self._logo_stream.seek(0)
                self.image(self._logo_stream, x=x_logo, y=top, w=LOGO_W_MM)
            except Exception:
                pass

        # Titre
        title_w = self.w - self.l_margin - self.r_margin - (LOGO_W_MM + HEADER_GAP_MM)
        self.set_xy(left, top + 2)
        self.set_font("Helvetica", "B", 16)
        self.set_text_color(*COLOR_SECTION)
        self.cell(title_w, 8, self._latin1(f"Datacenter — Site {self.site}"),
                  new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_font("Helvetica", "", 9)
        self.set_text_color(100, 100, 100)
        self.cell(title_w, 5, self._latin1(f"{self.org_name}  |  Généré le {dt.datetime.now().strftime('%d/%m/%Y à %H:%M')}"),
                  new_x=XPos.LMARGIN, new_y=YPos.NEXT)

        y_line = max(self.get_y(), top + LOGO_CLEAR_H_MM)
        self.set_draw_color(*COLOR_ACCENT)
        self.set_line_width(0.5)
        self.line(left, y_line, self.w - self.r_margin, y_line)
        self.set_text_color(0, 0, 0)
        self.set_y(y_line + 4)

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(130, 130, 130)
        self.cell(0, 10, self._latin1(self.author), new_x=XPos.RIGHT, new_y=YPos.TOP)
        self.cell(0, 10, self._latin1(f"Page {self.page_no()}/{{nb}}"), align="R")
        self.set_text_color(0, 0, 0)

    def section_title(self, text: str):
        self.ln(3)
        self.set_font("Helvetica", "B", 12)
        self.set_text_color(*COLOR_SECTION)
        self.set_fill_color(*COLOR_ROW_ODD)
        self.cell(0, 8, self._latin1(f"  {text}"), fill=True,
                  new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_text_color(0, 0, 0)
        self.ln(2)

    def key_value_block(self, rows: List[Tuple[str, str]], cols: int = 2):
        """Affiche une grille de paires clé/valeur sur N colonnes."""
        self.set_font("Helvetica", "", 10)
        usable  = self.w - self.l_margin - self.r_margin
        col_w   = usable / cols
        key_w   = col_w * 0.45
        val_w   = col_w * 0.55
        row_h   = 6.5
        i = 0
        while i < len(rows):
            for c in range(cols):
                if i + c >= len(rows):
                    break
                k, v = rows[i + c]
                x = self.l_margin + c * col_w
                self.set_xy(x, self.get_y())
                self.set_font("Helvetica", "B", 9)
                self.set_text_color(80, 80, 80)
                self.cell(key_w, row_h, self._latin1(f"{k}:"), border="B")
                self.set_font("Helvetica", "", 9)
                self.set_text_color(0, 0, 0)
                self.cell(val_w, row_h, self._latin1(str(v)), border="B")
            self.ln(row_h)
            i += cols
        self.ln(3)

    def _fit_text(self, text: str, max_width_mm: float) -> str:
        text  = self._latin1(text)
        max_w = max_width_mm - 1.0
        if self.get_string_width(text) <= max_w:
            return text
        ell   = "..."
        ell_w = self.get_string_width(ell)
        out   = ""
        for ch in text:
            if self.get_string_width(out + ch) + ell_w > max_w:
                break
            out += ch
        return out + ell

    def table(self, headers: List[str], rows: List[List[str]],
              weights: Optional[List[float]] = None):
        usable  = self.w - self.l_margin - self.r_margin
        n       = len(headers)
        weights = weights or [1] * n
        pad     = 2.5

        self.set_font("Helvetica", "B", 9)
        header_w = [self.get_string_width(self._latin1(h)) + pad for h in headers]
        self.set_font("Helvetica", "", 8)
        body_w = [0.0] * n
        for row in rows:
            for i, cell in enumerate(row):
                body_w[i] = max(body_w[i], self.get_string_width(self._latin1(str(cell))) + pad)

        content_mins = [max(header_w[i], body_w[i]) for i in range(n)]
        widths = [(usable * w / sum(weights)) for w in weights]
        widths = [max(w, content_mins[i]) for i, w in enumerate(widths)]

        # Rognage si dépassement
        total = sum(widths)
        if total > usable:
            scale  = usable / total
            widths = [w * scale for w in widths]

        header_h = 7
        self.set_font("Helvetica", "B", 9)
        self.set_fill_color(*COLOR_HEADER_BG)
        self.set_text_color(*COLOR_HEADER_FG)
        for i, h in enumerate(headers):
            self.cell(widths[i], header_h, self._fit_text(h, widths[i]),
                      border=1, align="C", fill=True)
        self.cell(0, header_h, "", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

        row_h = 6
        self.set_font("Helvetica", "", 8)
        for idx, row in enumerate(rows):
            if self.get_y() + row_h > self.h - self.b_margin:
                self.add_page()
                # Répétition entête
                self.set_font("Helvetica", "B", 9)
                self.set_fill_color(*COLOR_HEADER_BG)
                self.set_text_color(*COLOR_HEADER_FG)
                for i, h in enumerate(headers):
                    self.cell(widths[i], header_h, self._fit_text(h, widths[i]),
                              border=1, align="C", fill=True)
                self.cell(0, header_h, "", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
                self.set_font("Helvetica", "", 8)

            fill = idx % 2 == 0
            self.set_fill_color(*(COLOR_ROW_ODD if fill else COLOR_ROW_EVEN))
            self.set_text_color(0, 0, 0)
            for i, cell_txt in enumerate(row):
                raw   = str(cell_txt).strip()
                align = "C" if raw in ("-", "Yes", "No") else "L"
                self.cell(widths[i], row_h, self._fit_text(raw, widths[i]),
                          border=1, align=align, fill=fill)
            self.cell(0, row_h, "", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.ln(2)


# ─── Collecte & mise en forme des données ─────────────────────────────────────
def get_cluster_summary(api: ProxmoxAPI) -> Dict:
    status = api.cluster_status()
    out    = {"name": "-", "quorum": "-", "nodes_total": 0, "nodes_online": 0, "version": "-"}
    for item in status:
        t = item.get("type")
        if t == "cluster":
            out["name"]   = item.get("name") or "-"
            q = item.get("quorate")
            out["quorum"] = "Yes" if q in (1, True, "1") else "No"
        elif t == "node":
            out["nodes_total"] += 1
            if item.get("online"):
                out["nodes_online"] += 1
    try:
        v = api.version()
        out["version"] = v.get("version", "-")
    except Exception:
        pass
    return out

def get_nodes_rows(api: ProxmoxAPI) -> List[List[str]]:
    rows = []
    for node in api.nodes():
        name   = node.get("node", "-")
        status = node.get("status", "-")
        try:
            ns     = api.node_status(name)
            cpu_p  = f"{(ns.get('cpu', 0) * 100):.1f}%"
            mem_u  = ns.get("memory", {}).get("used", 0)
            mem_t  = ns.get("memory", {}).get("total", 0)
            mem_p  = f"{pair_gib(mem_u, mem_t)}"
            disk_u = ns.get("rootfs", {}).get("used", 0)
            disk_t = ns.get("rootfs", {}).get("total", 0)
            disk_p = f"{pair_gib(disk_u, disk_t)}"
            uptime = secs_to_hms(ns.get("uptime", 0))
            kver   = ns.get("kversion", "-")
            pve_ver = ns.get("pveversion", "-")
        except Exception:
            cpu_p = mem_p = disk_p = uptime = kver = pve_ver = "-"
        rows.append([name, status, cpu_p, mem_p, disk_p, uptime, pve_ver])
    return rows

def get_vm_rows(resources: List[Dict]) -> Tuple[List[List[str]], List[List[str]]]:
    """Retourne (liste_vms, liste_lxc)"""
    vms, lxc = [], []
    for r in resources:
        vmid   = str(r.get("vmid", "-"))
        name   = r.get("name") or f"VM {vmid}"
        node   = r.get("node", "-")
        status = r.get("status", "-")
        vcpu   = _fmt_vcpu(r.get("maxcpu") or r.get("cpus"))
        mem    = format_gib(r.get("maxmem", 0))
        disk   = format_gib(r.get("maxdisk", 0))
        cpu_p  = f"{(r.get('cpu', 0) * 100):.1f}%"
        mem_p  = f"{pct(r.get('mem', 0), r.get('maxmem', 1)):.1f}%"
        uptime = secs_to_hms(r.get("uptime", 0)) if r.get("status") == "running" else "-"
        row    = [vmid, name, node, status, vcpu, mem, disk, cpu_p, mem_p, uptime]
        if r.get("type") == "qemu":
            vms.append(row)
        elif r.get("type") == "lxc":
            lxc.append(row)
    return vms, lxc

def get_storage_rows(resources: List[Dict]) -> List[List[str]]:
    """
    - Stockages partagés (shared=Yes) : une seule ligne, noeud = "Cluster"
    - Stockages locaux  (shared=No)   : une ligne par noeud
    """
    rows = []
    seen = set()
    for r in resources:
        sid    = r.get("storage", "-")
        shared = r.get("shared", False)
        node   = r.get("node", "-")
        # Clé de déduplication : pour shared → sid seul ; pour local → sid + node
        key = sid if shared else f"{sid}:{node}"
        if key in seen:
            continue
        seen.add(key)
        stype  = r.get("plugintype", "-")
        status = r.get("status", "-")
        disk_u = r.get("disk", 0)
        disk_t = r.get("maxdisk", 0)
        usage  = pair_gib(disk_u, disk_t) if disk_t else "-"
        display_node = "Cluster" if shared else node
        rows.append([sid, display_node, stype, "Yes" if shared else "No", status, usage])
    return sorted(rows, key=lambda x: (x[2], x[0]))  # tri par type puis nom

def get_network_rows(networks: List[Dict]) -> Tuple[List[List[str]], List[List[str]], List[List[str]]]:
    """Retourne (bridges, bonds, interfaces_std)"""
    bridges, bonds, ifaces = [], [], []
    for n in networks:
        t      = (n.get("type") or "").lower()
        name   = n.get("iface") or n.get("ifname") or "-"
        active = "Yes" if n.get("active") else "No"
        auto   = "Yes" if n.get("autostart") else "No"
        addr   = n.get("cidr") or join_nonempty([n.get("address", ""), n.get("netmask", "")], "/") or "-"
        gw     = n.get("gateway") or "-"

        if t == "bridge":
            ports      = n.get("bridge_ports") or "-"
            vlan_aware = "Yes" if n.get("bridge_vlan_aware") else "No"
            bridges.append([name, ports if isinstance(ports, str) else " ".join(ports),
                             addr, gw, active, auto, vlan_aware])
        elif t == "bond":
            slaves = n.get("slaves") or n.get("bond_slaves") or "-"
            mode   = n.get("bond_mode") or n.get("mode") or "-"
            bonds.append([name,
                          slaves if isinstance(slaves, str) else " ".join(slaves),
                          mode, addr, active, auto])
        elif t in ("eth", "vlan", "") and name not in ("lo",):
            ifaces.append([name, t or "eth", addr, gw, active, auto])
    return bridges, bonds, ifaces


# ─── Génération du rapport ─────────────────────────────────────────────────────
def build_report(api: ProxmoxAPI, site: str, logo_path: Optional[str],
                 ssh_enabled: bool, ssh_auth: Optional[Dict],
                 org_name: Optional[str] = None, author: Optional[str] = None) -> bytes:

    print(f"\n[INFO] Collecte des données pour le site {site}...")

    # Collecte
    cluster_summary  = get_cluster_summary(api)
    nodes_list       = api.nodes()
    vm_resources     = api.cluster_resources_vm()
    storage_resources= api.cluster_resources_storage()

    print(f"  ✓ Cluster : {cluster_summary['name']} — {len(nodes_list)} nœud(s)")

    # Résumé VMs
    vm_rows, lxc_rows = get_vm_rows(vm_resources)
    print(f"  ✓ VMs QEMU : {len(vm_rows)} | Conteneurs LXC : {len(lxc_rows)}")

    storage_rows = get_storage_rows(storage_resources)
    print(f"  ✓ Stockages : {len(storage_rows)}")

    # Réseau par nœud
    node_networks: Dict[str, List] = {}
    for node in nodes_list:
        name = node.get("node", "")
        try:
            node_networks[name] = api.node_network(name)
        except Exception:
            node_networks[name] = []

    # Vitesses NIC via SSH (optionnel)
    ssh_speeds: Dict[str, Dict[str, float]] = {}
    if ssh_enabled and ssh_auth:
        print(f"  ✓ Collecte vitesses NIC via SSH...")
        for node in nodes_list:
            name = node.get("node", "")
            # On prend l'IP du premier bridge actif comme cible SSH
            nets    = node_networks.get(name, [])
            node_ip = api.host  # fallback : IP du cluster
            for n in nets:
                if n.get("type") == "bridge" and n.get("active") and n.get("address"):
                    node_ip = n["address"]
                    break
            speeds = collect_nic_speeds_ssh(node_ip, ssh_auth)
            if speeds:
                ssh_speeds[name] = speeds
                print(f"    → {name}: {len(speeds)} interfaces détectées")

    # ── PDF ──
    pdf = ReportPDF(site=site, org_name=org_name, author=author, orientation="L", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.set_margins(15, 15, 15)
    pdf.alias_nb_pages()

    # Logo — conversion fond transparent/noir → fond blanc pour fpdf2
    if logo_path and os.path.isfile(logo_path):
        try:
            from PIL import Image
            img = Image.open(logo_path).convert("RGBA")
            bg  = Image.new("RGBA", img.size, (255, 255, 255, 255))
            bg.paste(img, mask=img.split()[3])
            buf = io.BytesIO()
            bg.convert("RGB").save(buf, format="PNG")
            pdf.set_logo(buf.getvalue())
            print(f"  ✓ Logo chargé : {logo_path}")
        except Exception as e:
            print(f"[WARN] Impossible de charger le logo : {e}")
    else:
        if logo_path:
            print(f"[WARN] Logo introuvable : {logo_path}")
        else:
            print("[INFO] Aucun logo configuré — rapport généré sans logo")

    # ── Page 1 : Cluster Overview ──
    pdf.add_page()
    pdf.section_title(f"Vue d'ensemble — Cluster {cluster_summary['name']}")
    pdf.key_value_block([
        ("Site",          site),
        ("Cluster",       cluster_summary["name"]),
        ("Version PVE",   cluster_summary["version"]),
        ("Quorum",        cluster_summary["quorum"]),
        ("Nœuds total",   str(cluster_summary["nodes_total"])),
        ("Nœuds en ligne",str(cluster_summary["nodes_online"])),
        ("VMs QEMU",      str(len(vm_rows))),
        ("Conteneurs LXC",str(len(lxc_rows))),
        ("Stockages",     str(len(storage_rows))),
        ("Date rapport",  dt.datetime.now().strftime("%d/%m/%Y %H:%M")),
    ], cols=2)

    # ── Nœuds ──
    pdf.section_title("Nœuds Proxmox")
    nodes_rows = get_nodes_rows(api)
    pdf.table(
        headers=["Nœud", "Statut", "CPU %", "RAM (utilisé/total)", "Disk Root", "Uptime", "Version PVE"],
        rows=nodes_rows,
        weights=[2, 1.2, 1.2, 3, 3, 2, 2],
    )

    # ── VMs QEMU ──
    if vm_rows:
        pdf.section_title(f"Machines Virtuelles QEMU ({len(vm_rows)})")
        pdf.table(
            headers=["VMID", "Nom", "Nœud", "Statut", "vCPU", "RAM", "Disk", "CPU %", "RAM %", "Uptime"],
            rows=vm_rows,
            weights=[1, 3, 2, 1.5, 1.5, 1.5, 1.5, 1.2, 1.2, 2],
        )

    # ── LXC ──
    if lxc_rows:
        pdf.section_title(f"Conteneurs LXC ({len(lxc_rows)})")
        pdf.table(
            headers=["CTID", "Nom", "Nœud", "Statut", "vCPU", "RAM", "Disk", "CPU %", "RAM %", "Uptime"],
            rows=lxc_rows,
            weights=[1, 3, 2, 1.5, 1.5, 1.5, 1.5, 1.2, 1.2, 2],
        )

    # ── Stockage ──
    pdf.section_title(f"Stockage ({len(storage_rows)})")
    pdf.table(
        headers=["Storage ID", "Nœud", "Type", "Partagé", "Statut", "Utilisation"],
        rows=storage_rows,
        weights=[2.5, 2, 1.5, 1, 1.2, 3],
    )

    # ── Réseau par nœud ──
    for node in nodes_list:
        node_name = node.get("node", "")
        nets      = node_networks.get(node_name, [])
        if not nets:
            continue

        bridges, bonds, ifaces = get_network_rows(nets)

        pdf.add_page()
        pdf.section_title(f"Réseau — Nœud : {node_name}")

        if bridges:
            pdf.set_font("Helvetica", "B", 10)
            pdf.set_text_color(*COLOR_ACCENT)
            pdf.cell(0, 6, pdf._latin1("  Bridges"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            pdf.set_text_color(0, 0, 0)
            pdf.table(
                headers=["Interface", "Ports", "Adresse IP/CIDR", "Passerelle", "Actif", "Auto", "VLAN Aware"],
                rows=bridges,
                weights=[2, 2.5, 2.5, 2, 1, 1, 1.5],
            )

        if bonds:
            pdf.set_font("Helvetica", "B", 10)
            pdf.set_text_color(*COLOR_ACCENT)
            pdf.cell(0, 6, pdf._latin1("  Bonds"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            pdf.set_text_color(0, 0, 0)
            # Enrichissement vitesse SSH si dispo
            if node_name in ssh_speeds:
                speed_map = ssh_speeds[node_name]
                for row in bonds:
                    slaves    = row[1].split()
                    spds      = [speed_map.get(s) for s in slaves if speed_map.get(s)]
                    row_speed = _mbps_to_text(sum(spds)) if spds else "-"
                    row.append(row_speed)
                bond_headers  = ["Interface", "Slaves", "Mode", "Adresse", "Actif", "Auto", "Vitesse agrégée"]
                bond_weights  = [2, 2.5, 2, 2, 1, 1, 2]
            else:
                bond_headers  = ["Interface", "Slaves", "Mode", "Adresse", "Actif", "Auto"]
                bond_weights  = [2, 2.5, 2, 2, 1, 1]
            pdf.table(headers=bond_headers, rows=bonds, weights=bond_weights)

        if ifaces:
            pdf.set_font("Helvetica", "B", 10)
            pdf.set_text_color(*COLOR_ACCENT)
            pdf.cell(0, 6, pdf._latin1("  Interfaces standard"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            pdf.set_text_color(0, 0, 0)
            # Ajout vitesse SSH si dispo
            if node_name in ssh_speeds:
                speed_map = ssh_speeds[node_name]
                for row in ifaces:
                    row.append(_mbps_to_text(speed_map.get(row[0])))
                iface_headers  = ["Interface", "Type", "Adresse", "Passerelle", "Actif", "Auto", "Vitesse"]
                iface_weights  = [2, 1.5, 2.5, 2, 1, 1, 2]
            else:
                iface_headers  = ["Interface", "Type", "Adresse", "Passerelle", "Actif", "Auto"]
                iface_weights  = [2, 1.5, 2.5, 2, 1, 1]
            pdf.table(headers=iface_headers, rows=ifaces, weights=iface_weights)

    print(f"\n[INFO] PDF généré — {pdf.page} page(s)")
    return bytes(pdf.output())


# ─── CLI ───────────────────────────────────────────────────────────────────────
def parse_args():
    p = argparse.ArgumentParser(
        description="Proxmox Report Generator — générique multi-sites\n"
                    "Auth : variables d'env PVE_TOKEN_* (CI/CD) ou getpass interactif",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--host",    required=True, help="IP ou hostname Proxmox (ex: 192.0.2.10)")
    p.add_argument("--site",    required=True, help="Nom du site (ex: SITE1) — utilisé dans le titre et le nom du fichier")
    p.add_argument("--logo",    default=None,  help="Chemin vers le logo PNG/JPG")
    p.add_argument("--outdir",  default=".",   help="Dossier de sortie (défaut: répertoire courant)")
    p.add_argument("--outfile", default=None,  help="Nom du fichier PDF (défaut: Proxmox_<SITE>_<DATE>.pdf)")
    p.add_argument("--org",     default=None,  help="Nom de l'organisation affiché dans l'en-tête du rapport (défaut: variable PVE_REPORT_ORG ou générique)")
    p.add_argument("--author",  default=None,  help="Nom affiché en pied de page (défaut: variable PVE_REPORT_AUTHOR)")
    p.add_argument("--insecure",action="store_true", default=True,
                   help="Désactiver la vérification TLS (défaut: True pour lab)")
    p.add_argument("--debug",   action="store_true", help="Activer les logs debug API")

    # Auth ticket (fallback getpass si absent)
    p.add_argument("--username", default=None, help="Username Proxmox (ex: root@pam) — sinon prompt interactif")

    # Auth token (optionnel — sinon env vars ou getpass)
    p.add_argument("--token-user",   default=None, help="Token user (ex: root@pam)")
    p.add_argument("--token-id",     default=None, help="Token ID")
    p.add_argument("--token-secret", default=None, help="Token secret (déconseillé en arg — préférer env var)")

    # SSH
    p.add_argument("--ssh",       action="store_true", help="Activer la collecte SSH des vitesses NIC")
    p.add_argument("--ssh-user",  default=None, help="User SSH (défaut: root, sinon prompt)")
    p.add_argument("--ssh-key",   default=None, help="Chemin clé privée SSH")
    p.add_argument("--ssh-port",  type=int, default=22)

    return p.parse_args()


def main():
    args = parse_args()

    print("=" * 60)
    print(f"  Proxmox Report Generator")
    print(f"  Site : {args.site}  |  Host : {args.host}")
    print("=" * 60)

    # Résolution auth
    auth = resolve_auth(args)

    # SSH
    ssh_auth = None
    if args.ssh:
        print("\n[SSH] Collecte vitesses NIC activée")
        ssh_auth = resolve_ssh_auth(args)

    # Connexion API
    api = ProxmoxAPI(
        host=args.host,
        auth=auth,
        verify_ssl=not args.insecure,
        debug=args.debug,
    )
    api.login()

    # Logo
    logo_path = args.logo

    # Génération PDF
    pdf_bytes = build_report(api, args.site, logo_path, args.ssh, ssh_auth,
                              org_name=args.org, author=args.author)

    # Sauvegarde
    date_str  = dt.datetime.now().strftime("%Y%m%d_%H%M")
    filename  = args.outfile or f"Proxmox_{args.site}_{date_str}.pdf"
    outpath   = os.path.join(args.outdir, filename)
    os.makedirs(args.outdir, exist_ok=True)
    with open(outpath, "wb") as f:
        f.write(pdf_bytes)

    print(f"\n[OK] Rapport sauvegardé : {outpath}")
    print("=" * 60)


if __name__ == "__main__":
    main()
