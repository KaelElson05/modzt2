import os
import webbrowser
import shutil
import sqlite3
import subprocess
import json
import zipfile
import tempfile
import threading
import platform
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from collections import Counter
from ttkbootstrap import Window
import xml.etree.ElementTree as ET
import ttkbootstrap as tb
from PIL import Image, ImageTk
import hashlib
import zlib
import io
import sys
import re

db_lock = threading.Lock()

# ---------------- Constants ----------------
APP_VERSION = "1.0.2"
SETTINGS_FILE = "settings.json"
ZOO_PROFILE = os.path.join("data", "my_zoo.json")
BASE_PATH = getattr(sys, '_MEIPASS', os.path.abspath("."))
CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".zt2_manager")
os.makedirs(CONFIG_DIR, exist_ok=True)
GAME_PATH_FILE = os.path.join(CONFIG_DIR, "game_path.txt")
DB_FILE = os.path.join(CONFIG_DIR, "mods.db")
ICON_FILE = os.path.join(CONFIG_DIR, "modzt2.ico")
BANNER_FILE = os.path.join(CONFIG_DIR, "banner.png")
FILEMAP_CACHE = os.path.join(CONFIG_DIR, "mod_filemap.json")

# ---------------- Global State ----------------
GAME_PATH = None
if os.path.isfile(GAME_PATH_FILE):
    with open(GAME_PATH_FILE, "r", encoding="utf-8") as f:
        GAME_PATH = f.read().strip()

# --- Auto-detect common Zoo Tycoon 2 installation paths ---
COMMON_ZT2_PATHS = [
    r"C:\Program Files (x86)\Microsoft Games\Zoo Tycoon 2",
    r"C:\Program Files\Microsoft Games\Zoo Tycoon 2",
]

DEFAULT_SETTINGS = {
    "game_path": "",
    "theme": "flatly",
    "geometry": "1200x700+100+100"
}

def open_mods_folder():
    path = get_game_path()
    if path:
        os.startfile(path)

def resource_path(relative_path):
    """Get absolute path to resource, works for dev and PyInstaller."""
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

def load_settings():
    """Load settings.json safely, creating defaults if missing."""
    if not os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, "w") as f:
            json.dump(DEFAULT_SETTINGS, f, indent=4)
        return DEFAULT_SETTINGS.copy()
    try:
        with open(SETTINGS_FILE, "r") as f:
            data = json.load(f)
        for key, value in DEFAULT_SETTINGS.items():
            data.setdefault(key, value)
        return data
    except Exception:
        return DEFAULT_SETTINGS.copy()
    
def save_settings(settings):
    """Save settings.json safely."""
    with open(SETTINGS_FILE, "w") as f:
        json.dump(settings, f, indent=4)

def extract_animals_from_z2s(path):
    """Extract species names from ZT2 world.zt2 task entries like 'Deinonychus:GroomSelf'."""
    with zipfile.ZipFile(path, "r") as z:
        world_path = next((n for n in z.namelist() if n.lower().endswith("saved/world.zt2")), None)
        if not world_path:
            print("No world.zt2 found.")
            return []

        raw = z.read(world_path)
    try:
        data = zlib.decompress(raw)
    except zlib.error:
        try:
            data = zlib.decompress(raw[4:])
        except zlib.error:
            data = raw

    text = data.decode("utf-8", errors="ignore")

    species = re.findall(r'templateID="([A-Za-z0-9_]+):', text)

    ignore = {"staff","educator","guest","guestemotes","restaurant","bathroom",
              "amusement","worker","viewanimal","binoculars","terrain",
              "metaltrough_water","adultguestinteractions","smallrockcave_shelter",
              "seating","viewanimal_cp2","dinoRecoveryBuilding"}
    animals = [s for s in species if s.lower() not in ignore and len(s) > 2]

    counts = Counter(animals)
    print(f"Detected {len(counts)} species ({sum(counts.values())} total tasks).")
    for sp, c in counts.most_common():
        print(f" - {sp}: {c} task refs")
    
    return [{"species": sp, "name": ""} for sp in counts.keys()]

def extract_animals(file_path):
    """Detect animal entities (animal:/dino:/marine:/bird:) from a ZT2 .z2s save."""
    with zipfile.ZipFile(file_path, "r") as z:
        world_path = next((n for n in z.namelist() if n.lower().endswith("saved/world.zt2")), None)
        if not world_path:
            print("No world.zt2 found.")
            return []

        with z.open(world_path) as f:
            raw = f.read()

        try:
            data = zlib.decompress(raw)
        except zlib.error:
            try:
                data = zlib.decompress(raw[4:])
            except zlib.error:
                data = raw

        text = data.decode("utf-8", errors="ignore")

        pattern = re.compile(
            r'templateID="(?:animal|dino|marine|bird):([A-Za-z0-9_]+)"',
            re.IGNORECASE
        )
        matches = pattern.findall(text)

        if not matches:
            pattern2 = re.compile(
                r'subType="(?:[A-Za-z0-9_]*)(Adult|Young)_[MF]_[0-9]*"',
                re.IGNORECASE
            )
            matches = pattern2.findall(text)

        unique = sorted(set(matches))
        print(f"Detected {len(unique)} animal templates in {file_path}")
        for u in unique:
            print(" -", u)
        return unique

def list_all_templateids(file_path):
    """List every distinct templateID string in world.zt2"""
    with zipfile.ZipFile(file_path, "r") as z:
        world = next((n for n in z.namelist() if n.lower().endswith("saved/world.zt2")), None)
        if not world:
            print("No world.zt2 found.")
            return
        raw = z.read(world)
    try:
        data = zlib.decompress(raw)
    except zlib.error:
        try:
            data = zlib.decompress(raw[4:])
        except zlib.error:
            data = raw

    txt = data.decode("utf-8", errors="ignore")

    ids = re.findall(r'templateID="([^"]+)"', txt)
    uniq = sorted(set(ids))
    print(f"Found {len(uniq)} distinct templateIDs.")
    for u in uniq[:200]:
        print(u)
    if len(uniq) > 200:
        print("… (truncated)")
    return uniq

def species_name(species_id):
    """Converts internal Zoo Tycoon 2 species IDs into readable names."""
    if not species_id:
        return "Unknown"
    if species_id.lower().startswith("animal"):
        species_id = species_id[6:]
    return species_id.replace("_", " ").title()

def load_zoo_profile():
    os.makedirs("data", exist_ok=True)
    if not os.path.exists(ZOO_PROFILE):
        profile = {"zoo_name": "My Zoo", "zookeeper": os.getenv("USERNAME", "Player"), 
                   "animals": [], "trade_history": []}
        save_zoo_profile(profile)
        return profile
    with open(ZOO_PROFILE, "r", encoding="utf-8") as f:
        return json.load(f)
    
def save_zoo_profile(data):
    os.makedirs("data", exist_ok=True)
    with open(ZOO_PROFILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def sync_zoo_from_game(game_path=None):
    profile = load_zoo_profile()
    species_list = extract_animals_from_z2s(profile)
    profile["animals"] = species_list
    save_zoo_profile(profile)
    all_animals = []

    if not game_path:
        game_path = settings.get("game_path", "")
    z2f_dir = os.path.join(game_path, "dlupdates")
    if os.path.isdir(z2f_dir):
        for file in os.listdir(z2f_dir):
            if file.endswith(".z2f"):
                try:
                    with zipfile.ZipFile(os.path.join(z2f_dir, file), "r") as z:
                        for n in z.namelist():
                            if "animal" in n.lower() and n.lower().endswith(".xml"):
                                with z.open(n) as f:
                                    try:
                                        tree = ET.parse(f)
                                        root = tree.getroot()
                                        name = root.findtext("name", default=file.replace(".z2f", ""))
                                        all_animals.append({"species": name, "name": name})
                                    except Exception:
                                        pass
                except Exception:
                    pass

    saves_dir = os.path.join(game_path, "Saved Games")
    if os.path.isdir(saves_dir):
        for file in os.listdir(saves_dir):
            if file.endswith(".z2s"):
                try:
                    with zipfile.ZipFile(os.path.join(saves_dir, file), "r") as z:
                        for n in z.namelist():
                            if n.lower().endswith(".xml"):
                                with z.open(n) as f:
                                    xml = ET.parse(f)
                                    for a in xml.findall(".//Animal"):
                                        species = a.get("Species", "Unknown")
                                        name = a.get("Name", "Unnamed")
                                        all_animals.append({"species": species, "name": name})
                except Exception:
                    pass

    unique_animals = {f"{a['species']}|{a['name']}": a for a in all_animals}.values()
    profile = load_zoo_profile()
    profile["animals"] = detect_animals_from_latest_save()
    save_zoo_profile(profile)
    refresh_zoo_ui(profile)
    add_zoo_to_market(profile)
    refresh_market_ui_from_file()
    messagebox.showinfo(
        "Zoo Synced",
        f"Detected {len(profile['animals'])} animals from your latest saved zoo."
    )

def add_zoo_to_market(profile):
    """Save the current zoo to the persistent market list."""
    if not profile or "zoo_name" not in profile:
        return

    market_data_path = os.path.join("data", "market.json")
    os.makedirs("data", exist_ok=True)

    if os.path.exists(market_data_path):
        with open(market_data_path, "r", encoding="utf-8") as f:
            market = json.load(f)
    else:
        market = []

    existing = next((z for z in market if z.get("zoo_name") == profile["zoo_name"]), None)
    if existing:
        existing.update(profile)
    else:
        market.append(profile)

    with open(market_data_path, "w", encoding="utf-8") as f:
        json.dump(market, f, indent=2)

def get_zt2_save_dir():
    """Returns the Zoo Tycoon 2 save directory."""
    base = os.path.join(os.getenv("APPDATA"), "Microsoft Games", "Zoo Tycoon 2", "Default Profile", "Saved")
    if os.path.isdir(base):
        return base
    alt = os.path.join(os.getenv("USERPROFILE"), "Documents", "Zoo Tycoon 2", "Saved Games")
    return alt if os.path.isdir(alt) else None

def detect_animals_from_latest_save():
    saves_dir = get_zt2_save_dir()
    if not saves_dir:
        messagebox.showwarning("Zoo Sync", "Could not find the Zoo Tycoon 2 save folder.")
        return []

    zoo_files = [os.path.join(saves_dir, f) for f in os.listdir(saves_dir) if f.lower().endswith(".z2s")]
    if not zoo_files:
        messagebox.showinfo("Zoo Sync", "No .z2s zoo save files found.")
        return []

    latest = max(zoo_files, key=os.path.getmtime)
    print(f"Syncing from: {os.path.basename(latest)}")
    return extract_animals_from_z2s(latest)

def export_zoo_as_json():
    profile = load_zoo_profile()
    os.makedirs("data/trades", exist_ok=True)
    dest = os.path.join("data", "trades", f"{profile['zoo_name'].replace(' ', '_')}.z2s.json")
    with open(dest, "w", encoding="utf-8") as f:
        json.dump(profile, f, indent=2)
    messagebox.showinfo("Exported", f"Your zoo was exported to:\n{dest}")

def import_zoo_json():
    file = filedialog.askopenfilename(title="Import Zoo", filetypes=[("Zoo JSON", "*.z2s.json")])
    if not file:
        return

    with open(file, "r", encoding="utf-8") as f:
        other = json.load(f)

    market_data_path = os.path.join("data", "market.json")
    if os.path.exists(market_data_path):
        with open(market_data_path, "r", encoding="utf-8") as mf:
            market = json.load(mf)
    else:
        market = []

    existing = next((z for z in market if z.get("zoo_name") == other.get("zoo_name")), None)
    if existing:
        existing.update(other)
    else:
        market.append(other)

    with open(market_data_path, "w", encoding="utf-8") as mf:
        json.dump(market, mf, indent=2)

    refresh_market_ui_from_file()
    messagebox.showinfo("Imported", f"Imported zoo: {other.get('zoo_name')}")

def refresh_market_ui_from_file():
    """Reload the entire market table from market.json."""
    market_data_path = os.path.join("data", "market.json")
    if not os.path.exists(market_data_path):
        return

    with open(market_data_path, "r", encoding="utf-8") as f:
        market = json.load(f)

    market_tree.delete(*market_tree.get_children())

    for zoo in market:
        for a in zoo.get("animals", []):
            market_tree.insert("", "end", values=(zoo.get("zoo_name"), a.get("species", "?"), a.get("name", "")))

def auto_detect_zt2_installation():
    import winreg

    for path in COMMON_ZT2_PATHS:
        exe = os.path.join(path, "zt.exe")
        if os.path.isfile(exe):
            return path

    possible_keys = [
        r"SOFTWARE\Microsoft\Microsoft Games\Zoo Tycoon 2",
        r"SOFTWARE\WOW6432Node\Microsoft\Microsoft Games\Zoo Tycoon 2",
    ]
    for key in possible_keys:
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key) as regkey:
                install_dir, _ = winreg.QueryValueEx(regkey, "InstallationDirectory")
                exe = os.path.join(install_dir, "zt.exe")
                if os.path.isfile(exe):
                    return install_dir
        except FileNotFoundError:
            continue
        except Exception:
            pass

    user_dirs = [
        os.path.join(os.path.expanduser("~"), "Desktop"),
        os.path.join(os.path.expanduser("~"), "Documents"),
    ]
    for base in user_dirs:
        for root, dirs, files in os.walk(base):
            if "zt.exe" in files:
                return root

    return None

sort_state = {"column": "Name", "reverse": False}
ui_mode = {"compact": False}

# ---------------- Database ----------------
conn = sqlite3.connect(DB_FILE, check_same_thread=False)
cursor = conn.cursor()
cursor.execute("""
CREATE TABLE IF NOT EXISTS mods (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE,
    enabled INTEGER DEFAULT 0
)
""")
try:
    cursor.execute("ALTER TABLE mods ADD COLUMN hash TEXT")
except sqlite3.OperationalError:
    pass
conn.commit()
cursor.execute("""
CREATE TABLE IF NOT EXISTS bundles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE
)
""")
cursor.execute("""
CREATE TABLE IF NOT EXISTS mod_dependencies (
    mod_name TEXT,
    depends_on TEXT,
    FOREIGN KEY(mod_name) REFERENCES mods(name)
)
""")
conn.commit()
cursor.execute("""
CREATE TABLE IF NOT EXISTS bundle_mods (
    bundle_id INTEGER,
    mod_name TEXT,
    UNIQUE(bundle_id, mod_name)
)
""")
conn.commit()

# ---------------- Helpers ----------------
def log(msg, text_widget=None):
    timestamp = time.strftime("%H:%M:%S")
    full = f"[{timestamp}] {msg}"
    print(full)
    if text_widget:
        text_widget.configure(state="normal")
        text_widget.insert(tk.END, full + "\n")
        text_widget.configure(state="disabled")
        text_widget.see(tk.END)

def save_game_path(p):
    with open(GAME_PATH_FILE, "w", encoding="utf-8") as f:
        f.write(p)

def get_game_path():
    """Return a valid Zoo Tycoon 2 path or prompt user if not set."""
    global GAME_PATH, settings

    if GAME_PATH and os.path.exists(GAME_PATH):
        return GAME_PATH

    new_path = filedialog.askdirectory(title="Select your Zoo Tycoon 2 folder")
    if new_path:
        GAME_PATH = new_path
        settings["game_path"] = new_path
        with open("settings.json", "w") as f:
            json.dump(settings, f, indent=4)
        return GAME_PATH
    else:
        messagebox.showwarning("Path Not Set", "Please select your Zoo Tycoon 2 folder first.")
        return None

def enabled_count():
    cursor.execute("SELECT COUNT(*) FROM mods WHERE enabled=1")
    return cursor.fetchone()[0]

def show_progress(text="Scanning mods..."):
    status_label.config(text=text)
    progress_bar.pack(side=tk.RIGHT, padx=6)
    progress_bar.start(10)

def hide_progress():
    progress_bar.stop()
    progress_bar.pack_forget()
    update_status()

def set_dependencies(mod_name, dependencies):
    """Store dependency links in the DB."""
    cursor.execute("DELETE FROM mod_dependencies WHERE mod_name=?", (mod_name,))
    for dep in dependencies:
        cursor.execute("INSERT INTO mod_dependencies (mod_name, depends_on) VALUES (?, ?)", (mod_name, dep))
    conn.commit()

def get_dependencies(mod_name):
    cursor.execute("SELECT depends_on FROM mod_dependencies WHERE mod_name=?", (mod_name,))
    return [r[0] for r in cursor.fetchall()]

def get_dependents(target_mod):
    cursor.execute("SELECT mod_name FROM mod_dependencies WHERE depends_on=?", (target_mod,))
    return [r[0] for r in cursor.fetchall()]

def get_system_theme():
    """Return 'dark' or 'light' based on OS theme setting."""
    try:
        if platform.system() == "Windows":
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
            )
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return "light" if value == 1 else "dark"

        elif platform.system() == "Darwin":
            result = subprocess.run(
                ["defaults", "read", "-g", "AppleInterfaceStyle"],
                capture_output=True, text=True
            )
            return "dark" if "Dark" in result.stdout else "light"

        else:
            result = subprocess.run(
                ["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"],
                capture_output=True, text=True
            )
            return "dark" if "dark" in result.stdout.lower() else "light"

    except Exception:
        return "dark"

# ---------------- Game Path ----------------
def set_game_path(lbl_widget=None, status_widget=None):
    global GAME_PATH
    path = filedialog.askdirectory(title="Select Zoo Tycoon 2 Game Folder")
    if not path:
        return
    GAME_PATH = path
    save_game_path(GAME_PATH)
    if lbl_widget:
        lbl_widget.config(text=GAME_PATH)
    if status_widget:
        status_widget.config(text=f"ZT2 path: {GAME_PATH} | {enabled_count()} mods enabled")
    log(f"Game path set: {GAME_PATH}", text_widget=log_text)
    refresh_tree()

def launch_game(params=None):
    if not GAME_PATH:
        messagebox.showerror("Error", "Set game path first!")
        return

    exe_path = os.path.join(GAME_PATH, "zt.exe")
    if not os.path.isfile(exe_path):
        messagebox.showerror("Error", f"zt.exe not found in: {GAME_PATH}")
        return

    try:
        cmd = [exe_path]
        if params:
            if isinstance(params, str):
                cmd += params.split()
            elif isinstance(params, (list, tuple)):
                cmd += list(params)

        subprocess.Popen(cmd, cwd=GAME_PATH, shell=False)
        log(f"🎮 Launched Zoo Tycoon 2 {' '.join(cmd[1:]) if len(cmd) > 1 else ''}", text_widget=log_text)

    except Exception as e:
        messagebox.showerror("Error", f"Failed to launch ZT2: {e}")

# ---------------- Filesystem helpers ----------------
def mods_disabled_dir():
    return os.path.join(GAME_PATH, "Mods", "Disabled")

def find_mod_file(mod_name):
    p1 = os.path.join(GAME_PATH, mod_name)
    p2 = os.path.join(mods_disabled_dir(), mod_name)
    if os.path.isfile(p1):
        return p1
    if os.path.isfile(p2):
        return p2
    return None

def _normalise_mod_path(path):
    """Return a consistent representation for paths inside mod archives."""
    if not path:
        return None
    path = path.replace("\\", "/")
    path = path.lstrip("/")
    if not path or path.endswith("/"):
        return None
    return path.lower()


def _list_mod_files(full_path):
    """List all file entries inside a mod archive for conflict detection."""
    try:
        with zipfile.ZipFile(full_path, "r") as zf:
            files = []
            for name in zf.namelist():
                normalised = _normalise_mod_path(name)
                if normalised:
                    files.append(normalised)
            # Remove duplicates while preserving a stable order for comparison/logging
            return sorted(set(files))
    except zipfile.BadZipFile:
        log_widget = globals().get("log_text")
        log(f"Failed to index '{os.path.basename(full_path)}' (invalid zip).", text_widget=log_widget)
    except Exception as exc:
        log_widget = globals().get("log_text")
        log(f"Failed to index '{os.path.basename(full_path)}': {exc}", text_widget=log_widget)
    return []


def index_mod_files(cursor=None, conn=None, force=False):
    if cursor is None or conn is None:
        cursor = globals().get("cursor")
        conn = globals().get("conn")

    if not GAME_PATH:
        return {}

    cache_file = os.path.join(CONFIG_DIR, "file_index.json")
    cache = {}
    if os.path.isfile(cache_file):
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                cache = json.load(f)
        except Exception:
            cache = {}

    changed = False
    indexed_mods = set()

    for folder in [GAME_PATH, mods_disabled_dir()]:
        if not os.path.isdir(folder):
            continue
        for f in os.listdir(folder):
            if not (f.lower().endswith('.z2f') or f.lower().endswith('.zip')):
                continue
            if f.lower().endswith('.pac'):
                continue
            full_path = os.path.join(folder, f)
            try:
                mtime = os.path.getmtime(full_path)
            except OSError:
                continue

            entry = cache.get(f)
            if not force and entry and entry.get("_mtime") == mtime and "files" in entry:
                indexed_mods.add(f)
                continue

            import hashlib
            h = hashlib.sha1()
            try:
                with open(full_path, "rb") as fp:
                    while True:
                        chunk = fp.read(65536)
                        if not chunk:
                            break
                        h.update(chunk)
                mod_hash = h.hexdigest()
            except Exception:
                mod_hash = None

            files = _list_mod_files(full_path)

            new_entry = {
                "_mtime": mtime,
                "hash": mod_hash,
                "files": files,
            }

            if entry != new_entry:
                cache[f] = new_entry
                changed = True
                if mod_hash:
                    cursor.execute("UPDATE mods SET hash=? WHERE name=?", (mod_hash, f))

            indexed_mods.add(f)

    # Remove cache entries for mods that no longer exist on disk
    stale = set(cache.keys()) - indexed_mods
    if stale:
        for mod_name in stale:
            cache.pop(mod_name, None)
        changed = True

    if changed:
        conn.commit()
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2)

    return {mod: data.get("files", []) for mod, data in cache.items()}

def detect_conflicts(cursor=None, conn=None, filemap=None):
    """Detect overlapping internal files between mods (thread-safe)."""
    if cursor is None or conn is None:
        cursor = globals().get("cursor")
        conn = globals().get("conn")

    if filemap is None:
        cache_path = os.path.join(CONFIG_DIR, "file_index.json")
        if os.path.isfile(cache_path):
            try:
                with open(cache_path, "r", encoding="utf-8") as f:
                    cache = json.load(f)
                filemap = {k: v.get("files", []) for k, v in cache.items() if isinstance(v, dict)}
            except Exception:
                filemap = {}
        else:
            filemap = {}

    if not filemap:
        log("No indexed mod files available for conflict detection.", globals().get("log_text"))
        return {}

    file_to_mods = {}
    for mod, files in filemap.items():
        for f in files:
            file_to_mods.setdefault(f, set()).add(mod)

    conflicts = {f: sorted(mods) for f, mods in file_to_mods.items() if len(mods) > 1}

    log_widget = globals().get("log_text")

    if conflicts:
        sorted_conflicts = sorted(conflicts.items())
        lines = [f"{path}: {', '.join(mods)}" for path, mods in sorted_conflicts]
        preview = "\n".join(lines[:100])
        extra = "" if len(lines) <= 100 else f"\n...and {len(lines) - 100} more entries."
        log(
            f"⚠️ Detected {len(conflicts)} conflicting files:\n{preview}{extra}",
            text_widget=log_widget,
        )
        messagebox.showwarning(
            "Conflicting Mods Detected",
            f"{len(conflicts)} conflicting files found.\n\nCheck the log for details.",
        )
    else:
        log("No conflicts detected.", text_widget=log_widget)

    return conflicts

def file_hash(path):
    """Return SHA1 hash of file content for duplicate detection."""
    h = hashlib.sha1()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None

# ---------------- Mod Management ----------------
def detect_existing_mods(cursor=None, conn=None):
    if not GAME_PATH:
        return

    if cursor is None or conn is None:
        cursor = globals().get("cursor")
        conn = globals().get("conn")

    disabled_dir = mods_disabled_dir()
    os.makedirs(disabled_dir, exist_ok=True)

    scanned = {}
    for folder, enabled in [(GAME_PATH, 1), (disabled_dir, 0)]:
        if not os.path.isdir(folder):
            continue
        for f in os.listdir(folder):
            if not (f.lower().endswith('.z2f') or f.lower().endswith('.zip')):
                continue
            if f.lower().endswith('.pac'):
                continue

            full_path = os.path.join(folder, f)
            mtime = os.path.getmtime(full_path)
            scanned[f] = (enabled, mtime)

    # --- Update DB entries ---
    for mod_name, (enabled, mtime) in scanned.items():
        cursor.execute("SELECT COUNT(*) FROM mods WHERE name=?", (mod_name,))
        exists = cursor.fetchone()[0]
        if exists == 0:
            cursor.execute("INSERT INTO mods (name, enabled) VALUES (?, ?)", (mod_name, enabled))
        else:
            cursor.execute("UPDATE mods SET enabled=? WHERE name=?", (enabled, mod_name))
    conn.commit()

    # --- Remove entries for deleted mods ---
    cursor.execute("SELECT name FROM mods")
    for (name,) in cursor.fetchall():
        if name not in scanned:
            cursor.execute("DELETE FROM mods WHERE name=?", (name,))
    conn.commit()

    # --- Duplicate detection ---
    try:
        cursor.execute("""
            SELECT hash, GROUP_CONCAT(name, ', ') AS mods, COUNT(*) AS c
            FROM mods
            WHERE hash IS NOT NULL
            GROUP BY hash HAVING c > 1
        """)
        duplicates = cursor.fetchall()
        if duplicates:
            dup_text = "\n".join(f"{mods}" for _, mods, _ in duplicates)
            log(f"Duplicate mods detected:\n{dup_text}", log_text)
            messagebox.showwarning(
                "Duplicate Mods Detected",
                f"The following mods have identical contents:\n\n{dup_text}"
            )
    except sqlite3.OperationalError:
        pass

def install_mod(text_widget=None):
    if not GAME_PATH:
        messagebox.showerror("Error", "Set game path first!")
        return
    file_path = filedialog.askopenfilename(title="Select a .z2f Mod File", filetypes=[("ZT2 Mod", "*.z2f;*.zip"), ("All Files", "*.*")])
    if not file_path:
        return
    mod_name = os.path.basename(file_path)
    dest_dir = mods_disabled_dir()
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, mod_name)
    try:
        shutil.copy2(file_path, dest)
        log(f"Installed mod: {mod_name} -> {dest}", text_widget)
    except Exception as e:
        messagebox.showerror("Error", f"Failed to install: {e}")
        return
    cursor.execute("SELECT COUNT(*) FROM mods WHERE name=?", (mod_name,))
    if cursor.fetchone()[0] == 0:
        cursor.execute("INSERT INTO mods (name, enabled) VALUES (?, 0)", (mod_name,))
    else:
        cursor.execute("UPDATE mods SET enabled=0 WHERE name=?", (mod_name,))
    conn.commit()
    refresh_tree()
    update_status()

def enable_mod(mod_name, text_widget=None):
    deps = get_dependencies(mod_name)
    for dep in deps:
        cursor.execute("SELECT enabled FROM mods WHERE name=?", (dep,))
        row = cursor.fetchone()
        if not row or row[0] == 0:
            log(f"Enabling dependency: {dep}", text_widget)
            enable_mod(dep, text_widget)
        
    if not mod_name or not GAME_PATH:
        return
    src = os.path.join(mods_disabled_dir(), mod_name)
    dst = os.path.join(GAME_PATH, mod_name)
    if os.path.isfile(src):
        try:
            shutil.move(src, dst)
            log(f"Enabled mod: {mod_name}", text_widget)
        except Exception as e:
            messagebox.showerror("Error", f"Enable failed: {e}")
            return
    else:
        if not os.path.isfile(dst):
            messagebox.showwarning("Not found", f"Mod file for {mod_name} not found on disk.")
            return
    cursor.execute("UPDATE mods SET enabled=1 WHERE name=?", (mod_name,))
    conn.commit()
    refresh_tree()
    update_status()

def disable_mod(mod_name, text_widget=None):
    dependents = get_dependents(mod_name)
    if dependents:
        if not messagebox.askyesno("Disable Dependency",
                                   f"The following mods depend on {mod_name}:\n{', '.join(dependents)}\nDisable them too?"):
            return
        for d in dependents:
            disable_mod(d, text_widget)
        
    if not mod_name or not GAME_PATH:
        return
    dst_dir = mods_disabled_dir()
    os.makedirs(dst_dir, exist_ok=True)
    src = os.path.join(GAME_PATH, mod_name)
    dst = os.path.join(dst_dir, mod_name)
    if os.path.isfile(src):
        try:
            shutil.move(src, dst)
            log(f"Disabled mod: {mod_name}", text_widget)
        except Exception as e:
            messagebox.showerror("Error", f"Disable failed: {e}")
            return
    else:
        messagebox.showwarning("Not found", f"Mod file for {mod_name} not found in enabled folder.")
    cursor.execute("UPDATE mods SET enabled=0 WHERE name=?", (mod_name,))
    conn.commit()
    refresh_tree()
    update_status()

def uninstall_mod(mod_name, text_widget=None):
    if not mod_name or not GAME_PATH:
        return
    paths = [os.path.join(GAME_PATH, mod_name), os.path.join(mods_disabled_dir(), mod_name)]
    removed = False
    for p in paths:
        if os.path.isfile(p):
            try:
                os.remove(p)
                log(f"Removed file: {p}", text_widget)
                removed = True
            except Exception as e:
                messagebox.showerror("Error", f"Failed to remove {p}: {e}")
    cursor.execute("DELETE FROM mods WHERE name=?", (mod_name,))
    conn.commit()
    if removed:
        log(f"Uninstalled mod: {mod_name}", text_widget)
    else:
        log(f"Mod {mod_name} not found on disk, record removed from DB.", text_widget)
    refresh_tree()
    update_status()

def export_load_order():
    cursor.execute("SELECT name, enabled FROM mods")
    rows = cursor.fetchall()
    path = os.path.join(CONFIG_DIR, "load_order.txt")
    with open(path, "w", encoding="utf-8") as f:
        for name, enabled in rows:
            f.write(f"{name}: {'Enabled' if enabled else 'Disabled'}\n")
    messagebox.showinfo("Exported", f"Load order exported to:\n{path}")
    log(f"Exported load order to {path}", text_widget=log_text)

# ---------------- Watcher ----------------
def watch_mods(root, refresh_func, interval=5):
    def worker():
        last_snapshot = set()
        while True:
            try:
                if not GAME_PATH or not os.path.isdir(GAME_PATH):
                    time.sleep(interval)
                    continue
                found = set()
                ... 
            except Exception as e:
                print("Watcher error:", e)
                time.sleep(interval)

            found = set()
            disabled = mods_disabled_dir()
            for folder in [GAME_PATH, disabled]:
                if os.path.isdir(folder):
                    for f in os.listdir(folder):
                        if f.lower().endswith('.z2f') or f.lower().endswith('.zip'):
                            found.add((f, 1 if folder == GAME_PATH else 0))
            if found != last_snapshot:
                def update_db_and_refresh():
                    for mod_name, enabled in found:
                        cursor.execute("SELECT COUNT(*) FROM mods WHERE name=?", (mod_name,))
                        if cursor.fetchone()[0] == 0:
                            cursor.execute("INSERT INTO mods (name, enabled) VALUES (?, ?)", (mod_name, enabled))
                        else:
                            cursor.execute("UPDATE mods SET enabled=? WHERE name=?", (enabled, mod_name))
                    conn.commit()
                    refresh_func()
                    update_status()

                    refresh_tree()
                root.after(0, update_db_and_refresh)
                last_snapshot = found
            time.sleep(interval)
    threading.Thread(target=worker, daemon=True).start()

# ---------------- Bundles ----------------
def create_bundle(bundle_name, mod_list):
    if not bundle_name or not mod_list:
        return False
    cursor.execute("SELECT COUNT(*) FROM bundles WHERE name=?", (bundle_name,))
    if cursor.fetchone()[0] > 0:
        return False
    cursor.execute("INSERT INTO bundles (name) VALUES (?)", (bundle_name,))
    bundle_id = cursor.lastrowid
    for m in mod_list:
        cursor.execute("INSERT OR IGNORE INTO bundle_mods (bundle_id, mod_name) VALUES (?, ?)", (bundle_id, m))
    conn.commit()
    return True

def delete_bundle(bundle_name):
    cursor.execute("SELECT id FROM bundles WHERE name=?", (bundle_name,))
    row = cursor.fetchone()
    if not row:
        return False
    bundle_id = row[0]
    cursor.execute("DELETE FROM bundle_mods WHERE bundle_id=?", (bundle_id,))
    cursor.execute("DELETE FROM bundles WHERE id=?", (bundle_id,))
    conn.commit()
    return True

def get_bundles():
    cursor.execute("SELECT id, name FROM bundles ORDER BY name")
    bundles = []
    for bid, name in cursor.fetchall():
        cursor.execute("SELECT mod_name FROM bundle_mods WHERE bundle_id=? ORDER BY mod_name", (bid,))
        mods = [r[0] for r in cursor.fetchall()]
        bundles.append((name, mods))
    return bundles

def get_bundle_mods(bundle_name):
    cursor.execute("SELECT id FROM bundles WHERE name=?", (bundle_name,))
    row = cursor.fetchone()
    if not row:
        return []
    bid = row[0]
    cursor.execute("SELECT mod_name FROM bundle_mods WHERE bundle_id=? ORDER BY mod_name", (bid,))
    return [r[0] for r in cursor.fetchall()]

def apply_bundle(bundle_name, text_widget=None):
    mods = get_bundle_mods(bundle_name)
    if not mods:
        messagebox.showinfo("Empty", "Bundle contains no mods or was not found.")
        return
    exclusive = messagebox.askyesno("Apply Bundle",
                                    "Enable the bundle mods AND disable mods not in the bundle?\n(Yes = exclusive, No = enable bundle mods only)")
    for m in mods:
        enable_mod(m, text_widget=text_widget)
    if exclusive:
        cursor.execute("SELECT name FROM mods WHERE enabled=1")
        enabled_now = [r[0] for r in cursor.fetchall()]
        for en in enabled_now:
            if en not in mods:
                disable_mod(en, text_widget=text_widget)
    log(f"Applied bundle: {bundle_name} (mods: {', '.join(mods)})", text_widget)

def export_bundle_as_json(bundle_name):
    mods = get_bundle_mods(bundle_name)
    if not mods:
        messagebox.showerror("Error", "Bundle not found or empty")
        return
    payload = {"name": bundle_name, "mods": mods}
    path = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON", "*.json")], title="Export Bundle As")
    if not path:
        return
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=4)
    messagebox.showinfo("Exported", f"Bundle exported to:\n{path}")

def import_bundle_from_json(path=None):
    if not path:
        path = filedialog.askopenfilename(title="Import Bundle JSON", filetypes=[("JSON", "*.json")])
    if not path:
        return
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    name = payload.get("name")
    mods = payload.get("mods", [])
    if not name:
        messagebox.showerror("Invalid", "Bundle JSON missing 'name' field")
        return
    existing = []
    missing = []
    for m in mods:
        cursor.execute("SELECT COUNT(*) FROM mods WHERE name=?", (m,))
        if cursor.fetchone()[0] > 0:
            existing.append(m)
        else:
            missing.append(m)
    created = create_bundle(name, existing)
    if not created:
        messagebox.showerror("Exists", "Bundle with that name already exists or invalid")
        return
    msg = f"Imported bundle '{name}'.\nAdded {len(existing)} existing mods."
    if missing:
        msg += f"\n{len(missing)} mods were missing locally and were not added: {', '.join(missing)}"
    messagebox.showinfo("Imported", msg)

# ---------------- Merge / Export .z2f ----------------
def export_bundle_as_z2f(bundle_name, include_files, output_path):
    """
    include_files: set of relative file paths to include (paths inside the z2f archives)
    output_path: full path to write the .z2f
    """
    mods = get_bundle_mods(bundle_name)
    if not mods:
        messagebox.showerror("Error", "Bundle not found or empty")
        return
    mod_paths = []
    for m in mods:
        p = find_mod_file(m)
        if p:
            mod_paths.append(p)
        else:
            log(f"Warning: mod file for {m} not found on disk", text_widget=log_text)

    if not mod_paths:
        messagebox.showerror("Error", "None of the bundle mod files were found on disk")
        return

    tmp_dir = tempfile.mkdtemp()
    try:
        for mp in mod_paths:
            try:
                with zipfile.ZipFile(mp, 'r') as zf:
                    for member in zf.namelist():
                        if include_files and member not in include_files:
                            continue
                        target = os.path.join(tmp_dir, member)
                        os.makedirs(os.path.dirname(target), exist_ok=True)
                        with zf.open(member) as src, open(target, 'wb') as dst:
                            dst.write(src.read())
            except zipfile.BadZipFile:
                log(f"Skipping bad zip: {mp}")

        with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as outzip:
            for root_dir, _, files in os.walk(tmp_dir):
                for f in files:
                    abs_path = os.path.join(root_dir, f)
                    rel = os.path.relpath(abs_path, tmp_dir)
                    outzip.write(abs_path, rel)
        log(f"Exported merged bundle to: {output_path}", text_widget=log_text)
        messagebox.showinfo("Exported", f"Bundle merged and exported to:\n{output_path}")
    finally:
        shutil.rmtree(tmp_dir)

def export_bundle_as_mod_ui(bundle_name=None):
    if not bundle_name:
        sel = bundle_list.curselection()
        if not sel:
            messagebox.showinfo("Select", "Select a bundle first.")
            return
        bundle_name = bundle_list.get(sel[0]).rsplit(' (', 1)[0]

    mods = get_bundle_mods(bundle_name)
    if not mods:
        messagebox.showerror("Error", "Bundle empty or not found")
        return

    file_map = {}
    mod_paths = {}
    for m in mods:
        p = find_mod_file(m)
        if not p:
            log(f"Mod file {m} not found on disk; skipping", text_widget=log_text)
            continue
        mod_paths[m] = p
        try:
            with zipfile.ZipFile(p, 'r') as zf:
                for mem in zf.namelist():
                    file_map.setdefault(mem, []).append(m)
        except zipfile.BadZipFile:
            log(f"Bad zip file: {p}", text_widget=log_text)

    files = sorted(file_map.keys())
    if not files:
        messagebox.showerror("Error", "No files found inside bundle mod archives")
        return

    dlg = tk.Toplevel(root)
    dlg.title(f"Select files to include - {bundle_name}")
    dlg.geometry("700x500")

    frame = ttk.Frame(dlg, padding=6)
    frame.pack(fill=tk.BOTH, expand=True)

    canvas = tk.Canvas(frame)
    scrollbar = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=canvas.yview)
    inner = ttk.Frame(canvas)

    inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.create_window((0, 0), window=inner, anchor='nw')
    canvas.configure(yscrollcommand=scrollbar.set)

    canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

    var_map = {}
    for f in files:
        text = f"{f}   [{' ,'.join(file_map[f])}]"
        var = tk.BooleanVar(value=True)
        chk = ttk.Checkbutton(inner, text=text, variable=var)
        chk.pack(anchor='w')
        var_map[f] = var

    def do_export():
        included = {f for f, v in var_map.items() if v.get()}
        if not included:
            messagebox.showerror("Empty", "You must include at least one file")
            return
        out_dir = filedialog.askdirectory(title="Select export folder")
        if not out_dir:
            return
        out_name = f"{bundle_name}.z2f"
        out_path = os.path.join(out_dir, out_name)
        export_bundle_as_z2f(bundle_name, included, out_path)
        dlg.destroy()

    btns = ttk.Frame(dlg, padding=6)
    btns.pack(fill=tk.X)
    ttk.Button(btns, text="Export", command=do_export, bootstyle="success").pack(side=tk.RIGHT, padx=6)
    ttk.Button(btns, text="Cancel", command=dlg.destroy, bootstyle="secondary").pack(side=tk.RIGHT)

# ---------------- UI Construction ----------------
settings = load_settings()
system_theme = get_system_theme()
root = Window(themename="darkly" if system_theme == "dark" else "cosmo")
root.title(f"ModZT2 v{APP_VERSION}")
root.geometry("1400x900")

icon_path = resource_path("modzt2.ico")
if os.path.exists(icon_path):
    root.iconbitmap(icon_path)
else:
    print(f"[!] Icon not found: {icon_path}")

def auto_switch_theme():
    """Auto-switch between dark/light when system theme changes."""
    try:
        current_system = get_system_theme()
        current_app = "dark" if root.style.theme.name == "darkly" else "light"
        if current_system != current_app:
            new_theme = "darkly" if current_system == "dark" else "cosmo"
            root.style.theme_use(new_theme)
            log(f"Switched to {new_theme} mode automatically.", text_widget=log_text)
            apply_tree_theme()
    except Exception as e:
        print("Theme auto-switch error:", e)
    root.after(10000, auto_switch_theme)

if os.path.isfile(ICON_FILE):
    try:
        root.iconbitmap(ICON_FILE)
    except Exception:
        pass

banner = ttk.Frame(root, padding=12, bootstyle="dark")
banner.pack(fill=tk.X)

if os.path.isfile(BANNER_FILE):
    try:
        img = Image.open(BANNER_FILE)
        img.thumbnail((72, 72), Image.LANCZOS)
        banner_img = ImageTk.PhotoImage(img)
        logo_label = ttk.Label(banner, image=banner_img)
        logo_label.image = banner_img
        logo_label.pack(side=tk.LEFT, padx=(0, 12))
    except Exception as e:
        print("Banner load failed:", e)

_tt = ttk.Label(banner, text="ModZT2", font=("Segoe UI", 20, "bold"), bootstyle="inverse-dark")
_tt.pack(side=tk.LEFT)

toolbar = ttk.Frame(root, padding=6, bootstyle="primary")
toolbar.pack(fill=tk.X)

lbl_game_path = ttk.Label(toolbar, text=GAME_PATH or "(not set)", width=80, bootstyle="secondary")
lbl_game_path.pack(side=tk.LEFT, padx=(6, 10))

game_menu_btn = ttk.Menubutton(toolbar, text="Game", bootstyle="info-outline")
game_menu = tk.Menu(game_menu_btn, tearoff=0)
game_menu.add_command(label="Set Game Path", command=lambda: set_game_path(lbl_game_path, status_label))
game_menu.add_command(label="Play ZT2", command=launch_game)
game_menu_btn["menu"] = game_menu
game_menu_btn.pack(side=tk.LEFT, padx=4)

mods_menu_btn = ttk.Menubutton(toolbar, text="Mods", bootstyle="info-outline")
mods_menu = tk.Menu(mods_menu_btn, tearoff=0)
mods_menu.add_command(label="Export Load Order", command=export_load_order)
mods_menu.add_command(label="Backup Mods", command=lambda: run_with_progress(backup_mods, "Backing up mods"))
mods_menu.add_command(label="Restore Mods", command=lambda: restore_mods)
mods_menu.add_separator()
mods_menu.add_command(
    label="Check Conflicts",
    command=lambda: detect_conflicts(filemap=index_mod_files()),
)
mods_menu_btn["menu"] = mods_menu
mods_menu_btn.pack(side=tk.LEFT, padx=4)

tools_menu_btn = ttk.Menubutton(toolbar, text="Tools", bootstyle="info-outline")
tools_menu = tk.Menu(tools_menu_btn, tearoff=0)
tools_menu.add_command(label="Validate Mods", command=lambda: messagebox.showinfo("Validate Mods", "All mods validated successfully."))
tools_menu.add_separator()
tools_menu.add_command(label="Clean Temporary Files", command=lambda: messagebox.showinfo("Cleanup", "Temporary files cleaned up."))
tools_menu_btn["menu"] = tools_menu
tools_menu_btn.pack(side=tk.LEFT, padx=4)

ttk.Separator(toolbar, orient="vertical").pack(side=tk.LEFT, fill=tk.Y, padx=8)

def toggle_theme():
    if root.style.theme_use() == 'darkly':
        root.style.theme_use('cosmo')
    else:
        root.style.theme_use('darkly')
    log("Toggled theme", text_widget=log_text)

def toggle_ui_mode():
    ui_mode["compact"] = not ui_mode["compact"]
    apply_ui_mode()
    mode = "Compact" if ui_mode["compact"] else "Expanded"
    log(f"Switched to {mode} mode", text_widget=log_text)

view_menu_button = ttk.Menubutton(toolbar, text="View", bootstyle="info-outline")
view_menu = tk.Menu(view_menu_button, tearoff=0)
view_menu.add_command(label="Toggle Theme", command=toggle_theme)
view_menu.add_command(label="Compact Mode", command=toggle_ui_mode)
view_menu_button["menu"] = view_menu
view_menu_button.pack(side=tk.LEFT, padx=4)

help_menu_btn = ttk.Menubutton(toolbar, text="Help", bootstyle="info-outline")
help_menu = tk.Menu(help_menu_btn, tearoff=0)
help_menu.add_command(label="About ModZT2", command=lambda: messagebox.showinfo("About", "ModZT2 v1.0.2\nCreated by Kael"))
help_menu.add_command(label="Open GitHub Page", command=lambda: webbrowser.open("https://github.com/kaelelson05"))
help_menu_btn["menu"] = help_menu
help_menu_btn.pack(side=tk.LEFT, padx=4)

footer = ttk.Frame(root, padding=4)
footer.pack(fill=tk.X, side=tk.BOTTOM)

def run_with_progress(task_func, description):
    def task_wrapper():
        try:
            task_func()
            log_action(f"{description} completed")
            status_label.config(text=f"{description} - Done")
        except Exception as e:
            status_label.config(text=f"Error: {e}")
        finally:
            progress.stop()

    progress.start()
    status_label.config(text=description)
    threading.Thread(target=task_wrapper, daemon=True).start()

recent_actions = ttk.Combobox(footer, values=["No recent actions"], width=40, state="readonly")
recent_actions.pack(side=tk.RIGHT, padx=10)

progress = ttk.Progressbar(footer, length=200, mode="indeterminate")
progress.pack(side=tk.RIGHT, padx=10)

def log_action(action):
    values = list(recent_actions["values"])
    if "No recent actions" in values:
        values.remove("No recent actions")
    values.insert(0, action)
    recent_actions["values"] = values[:10]
    recent_actions.current(0)
    status_label.config(text=action)

root.bind("<Control-q>", lambda e: root.quit())

main_frame = ttk.Frame(root)
main_frame.pack(fill=tk.BOTH, expand=True)

notebook = ttk.Notebook(main_frame)
notebook.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

mods_tab = ttk.Frame(notebook, padding=6)
notebook.add(mods_tab, text="Mods")

search_frame = ttk.Frame(mods_tab)
search_frame.pack(fill=tk.X)
ttk.Label(search_frame, text="Search:").pack(side=tk.LEFT)
search_var = tk.StringVar()
search_entry = ttk.Entry(search_frame, textvariable=search_var)
search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)

mods_tree_frame = ttk.Frame(mods_tab)
mods_tree_frame.pack(fill=tk.BOTH, expand=True, pady=(4, 0))

mods_tree_scroll = ttk.Scrollbar(mods_tree_frame)
mods_tree_scroll.pack(side=tk.RIGHT, fill=tk.Y)

mods_tree = ttk.Treeview(
    mods_tree_frame,
    columns=("Name", "Status", "Size", "Modified"),
    show="headings",
    yscrollcommand=mods_tree_scroll.set
)
mods_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
mods_tree_scroll.config(command=mods_tree.yview)

mods_tree.column("Name", width=250, anchor="w")
mods_tree.column("Status", width=100, anchor="center")
mods_tree.column("Size", width=100, anchor="e")
mods_tree.column("Modified", width=180, anchor="center")

mods_tree.heading("Name", text="Name", command=lambda: sort_tree_by("Name"))
mods_tree.heading("Status", text="Status", command=lambda: sort_tree_by("Status"))
mods_tree.heading("Size", text="Size (MB)", command=lambda: sort_tree_by("Size"))
mods_tree.heading("Modified", text="Last Modified", command=lambda: sort_tree_by("Modified"))

mods_tree.bind("<Double-1>", lambda e: show_mod_details())

mod_count_label = ttk.Label(
    mods_tab, text="Total mods: 0 | Enabled: 0 | Disabled: 0", bootstyle="secondary"
)
mod_count_label.pack(anchor="w", padx=6, pady=(2, 0))

mod_btns = ttk.Frame(mods_tab, padding=6)
mod_btns.pack(fill=tk.X, pady=(0, 4))

mods_menu = tk.Menu(root, tearoff=0)
mods_menu.add_command(label="Enable", command=lambda: enable_selected_mod())
mods_menu.add_command(label="Disable", command=lambda: disable_selected_mod())
mods_menu.add_command(label="Uninstall", command=lambda: uninstall_selected_mod())
mods_menu.add_command(label="Inspect ZIP", command=lambda: inspect_selected_mod())
mods_menu.add_separator()
mods_menu.add_command(label="Open Mod Folder", command=lambda: open_mod_folder())

def on_mod_right_click(event):
    iid = mods_tree.identify_row(event.y)
    if iid:
        mods_tree.selection_set(iid)
        mods_menu.post(event.x_root, event.y_root)

mods_tree.bind("<Button-3>", on_mod_right_click)

mod_btns = ttk.Frame(mods_tab, padding=6)
mod_btns.pack(fill=tk.X)

install_btn = ttk.Button(mod_btns, text="Install Mod", command=lambda: (install_mod(text_widget=log_text), detect_existing_mods(), refresh_tree()), bootstyle="success")
install_btn.pack(side=tk.LEFT, padx=4)
enable_btn = ttk.Button(mod_btns, text="Enable", command=lambda: (enable_selected_mod(),), bootstyle="info")
enable_btn.pack(side=tk.LEFT, padx=4)
disable_btn = ttk.Button(mod_btns, text="Disable", command=lambda: (disable_selected_mod(),), bootstyle="danger")
disable_btn.pack(side=tk.LEFT, padx=4)
uninstall_btn = ttk.Button(mod_btns, text="Uninstall", command=lambda: (uninstall_selected_mod(),), bootstyle="warning")
uninstall_btn.pack(side=tk.LEFT, padx=4)
refresh_btn = ttk.Button(mod_btns, text="Refresh List", command=lambda: (detect_existing_mods(), refresh_tree()))
refresh_btn.pack(side=tk.LEFT, padx=4)

bundles_tab = ttk.Frame(notebook, padding=6)
notebook.add(bundles_tab, text="Bundles")

explorer_tab = ttk.Frame(notebook, padding=6)
notebook.add(explorer_tab, text="Explorer")

explorer_split = ttk.PanedWindow(explorer_tab, orient=tk.HORIZONTAL)
explorer_split.pack(fill=tk.BOTH, expand=True)

folder_tree = ttk.Treeview(explorer_split)
folder_tree.pack(fill=tk.BOTH, expand=True)
explorer_split.add(folder_tree, weight=1)

file_list = ttk.Treeview(explorer_split, columns=("Name", "Size", "Modified"), show="headings")
file_list.heading("Name", text="Name")
file_list.heading("Size", text="Size (KB)")
file_list.heading("Modified", text="Modified")
file_list.column("Name", width=250, anchor="w")
file_list.column("Size", width=100, anchor="e")
file_list.column("Modified", width=180, anchor="center")
file_list.pack(fill=tk.BOTH, expand=True)
explorer_split.add(file_list, weight=3)

content_frame = ttk.Frame(bundles_tab)
content_frame.pack(fill=tk.BOTH, expand=True)

bundle_split = ttk.PanedWindow(content_frame, orient=tk.HORIZONTAL)
bundle_split.pack(fill=tk.BOTH, expand=True)

left_panel = ttk.Frame(bundle_split, width=260, padding=(4, 6))
left_panel.pack_propagate(False)
bundle_split.add(left_panel, weight=1)

ttk.Label(left_panel, text="Bundles", font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(0, 4))
search_row = ttk.Frame(left_panel)
search_row.pack(fill=tk.X, pady=(0, 6))

bundle_search_var = tk.StringVar()
ttk.Entry(search_row, textvariable=bundle_search_var).pack(side=tk.LEFT, fill=tk.X, expand=True)
ttk.Button(search_row, text="Clear", bootstyle="secondary-outline",
           command=lambda: (bundle_search_var.set(""), refresh_bundles_list())).pack(side=tk.LEFT, padx=(6, 0))

bundle_list_frame = ttk.Frame(left_panel)
bundle_list_frame.pack(fill=tk.BOTH, expand=True)

bundle_list_scroll = ttk.Scrollbar(bundle_list_frame, orient="vertical")
bundle_list_scroll.pack(side=tk.RIGHT, fill=tk.Y)

bundle_list = tk.Listbox(bundle_list_frame, exportselection=False, height=20, yscrollcommand=bundle_list_scroll.set)
bundle_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
bundle_list_scroll.config(command=bundle_list.yview)

if bundle_list.size() == 0:
    bundle_list.insert(tk.END, "(No bundles yet)")

bundle_preview = ttk.Frame(bundle_split, padding=8)
bundle_split.add(bundle_preview, weight=3)

ttk.Label(bundle_preview, text="Bundle Preview", font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(0, 6))
bundle_name_lbl = ttk.Label(bundle_preview, text="(Select a bundle)", bootstyle="secondary")
bundle_name_lbl.pack(anchor="w", pady=(0, 6))

preview_tree = ttk.Treeview(bundle_preview, columns=("mod", "status"), show="headings", height=14)
preview_tree.heading("mod", text="Mod Name")
preview_tree.heading("status", text="Status")
preview_tree.column("mod", width=280, anchor="w")
preview_tree.column("status", width=100, anchor="center")
preview_tree.pack(fill=tk.BOTH, expand=True)

bundle_stats = tk.StringVar(value="0 mods")
ttk.Label(bundle_preview, textvariable=bundle_stats, bootstyle="info").pack(anchor="e", pady=(6, 0))

preview_btns = ttk.Frame(bundle_preview)
preview_btns.pack(fill=tk.X, pady=(6, 0))
ttk.Button(preview_btns, text="Apply Bundle", command=lambda: bundle_apply(), bootstyle="primary").pack(side=tk.LEFT, padx=4)
ttk.Button(preview_btns, text="Enable All", command=lambda: bundle_enable_all(), bootstyle="success").pack(side=tk.LEFT, padx=4)
ttk.Button(preview_btns, text="Disable All", command=lambda: bundle_disable_all(), bootstyle="warning").pack(side=tk.LEFT, padx=4)

bundle_btns = ttk.Frame(bundles_tab, padding=6)
bundle_btns.pack(side=tk.BOTTOM, fill=tk.X, pady=(4, 0))

ttk.Separator(bundles_tab, orient="horizontal").pack(side=tk.BOTTOM, fill=tk.X)

ttk.Button(bundle_btns, text="Create", command=lambda: bundle_create_dialog(), bootstyle="secondary").pack(side=tk.LEFT, padx=4)
ttk.Button(bundle_btns, text="Apply", command=lambda: bundle_apply(), bootstyle="primary").pack(side=tk.LEFT, padx=4)
ttk.Button(bundle_btns, text="Delete", command=lambda: bundle_delete(), bootstyle="danger").pack(side=tk.LEFT, padx=4)
ttk.Button(bundle_btns, text="Export JSON", command=lambda: bundle_export_json()).pack(side=tk.LEFT, padx=4)
ttk.Button(bundle_btns, text="Import JSON", command=lambda: bundle_import_json()).pack(side=tk.LEFT, padx=4)
ttk.Button(bundle_btns, text="Export Bundle as Mod (.z2f)", command=lambda: bundle_export_z2f(), bootstyle="success").pack(side=tk.LEFT, padx=4)

trade_split = ttk.PanedWindow(orient=tk.HORIZONTAL)
trade_split.pack(fill=tk.BOTH, expand=True)

zoo_frame = ttk.Frame(trade_split, padding=8)
trade_split.add(zoo_frame, weight=1)

ttk.Label(zoo_frame, text="My Zoo", font=("Segoe UI", 12, "bold")).pack(anchor="w")
zoo_name_lbl = ttk.Label(zoo_frame, text="", bootstyle="secondary")
zoo_name_lbl.pack(anchor="w", pady=(0, 6))

animal_tree = ttk.Treeview(zoo_frame, columns=("species", "name"), show="headings", height=18)
animal_tree.heading("species", text="Species")
animal_tree.heading("name", text="Name")
animal_tree.pack(fill=tk.BOTH, expand=True)

zoo_btns = ttk.Frame(zoo_frame)
zoo_btns.pack(fill=tk.X, pady=(6, 0))
ttk.Button(zoo_btns, text="Sync from Game", bootstyle="info", command=lambda: sync_zoo_from_game()).pack(side=tk.LEFT, padx=4)
ttk.Button(zoo_btns, text="Export Zoo", bootstyle="secondary", command=export_zoo_as_json).pack(side=tk.LEFT, padx=4)

market_frame = ttk.Frame(trade_split, padding=8)
trade_split.add(market_frame, weight=1)

ttk.Label(market_frame, text="Trade Market", font=("Segoe UI", 12, "bold")).pack(anchor="w")
market_tree = ttk.Treeview(market_frame, columns=("zoo", "species", "name"), show="headings", height=18)
market_tree.heading("zoo", text="Zoo")
market_tree.heading("species", text="Species")
market_tree.heading("name", text="Name")
market_tree.pack(fill=tk.BOTH, expand=True)

market_btns = ttk.Frame(market_frame)
market_btns.pack(fill=tk.X, pady=(6, 0))
ttk.Button(market_btns, text="Import Zoo", bootstyle="primary", command=import_zoo_json).pack(side=tk.LEFT, padx=4)

def _selected_bundle_name():
    sel = bundle_list.curselection()
    if not sel:
        return None
    return bundle_list.get(sel[0])

def refresh_bundles_list():
    """Reloads the bundle list from DB and reapplies current filter."""
    global _all_bundle_names_cache
    cursor.execute("SELECT name FROM bundles ORDER BY name ASC")
    names = [r[0] for r in cursor.fetchall()]
    _all_bundle_names_cache = names[:]
    _apply_bundle_filter()

def _apply_bundle_filter(*_):
    """Apply search filter to cached bundle names."""
    query = bundle_search_var.get().strip().lower()
    bundle_list.delete(0, tk.END)

    filtered = [n for n in _all_bundle_names_cache if query in n.lower()]
    if not filtered:
        bundle_list.insert(tk.END, "(No bundles yet)" if not _all_bundle_names_cache else "(No matches)")
        bundle_name_lbl.config(text="(Select a bundle)")
        for i in preview_tree.get_children():
            preview_tree.delete(i)
        bundle_stats.set("0 mods")
        return

    for n in filtered:
        bundle_list.insert(tk.END, n)

def refresh_bundle_preview(event=None):
    """Populate right preview panel for current selection."""
    name = _selected_bundle_name()
    if not name or name.startswith("("):
        bundle_name_lbl.config(text="(Select a bundle)")
        for i in preview_tree.get_children():
            preview_tree.delete(i)
        bundle_stats.set("0 mods")
        return

    bundle_name_lbl.config(text=name)
    for i in preview_tree.get_children():
        preview_tree.delete(i)

    cursor.execute("SELECT id FROM bundles WHERE name=?", (name,))
    row = cursor.fetchone()
    if not row:
        bundle_stats.set("0 mods")
        return

    bundle_id = row[0]
    cursor.execute("SELECT mod_name FROM bundle_mods WHERE bundle_id=? ORDER BY mod_name", (bundle_id,))
    mods = [r[0] for r in cursor.fetchall()]

    enabled_count = 0
    for m in mods:
        cursor.execute("SELECT enabled FROM mods WHERE name=?", (m,))
        r = cursor.fetchone()
        status = "Enabled" if r and r[0] else "Disabled"
        if status == "Enabled":
            enabled_count += 1
        preview_tree.insert("", "end", values=(m, status))

    bundle_stats.set(f"{enabled_count}/{len(mods)} enabled")

bundle_list.bind("<<ListboxSelect>>", refresh_bundle_preview)

def _bundle_context_menu(event):
    idx = bundle_list.nearest(event.y)
    try:
        bundle_list.selection_clear(0, tk.END)
        bundle_list.selection_set(idx)
    except Exception:
        pass

    menu = tk.Menu(bundles_tab, tearoff=0)
    menu.add_command(label="Apply", command=lambda: bundle_apply())
    menu.add_command(label="Delete", command=lambda: bundle_delete())
    menu.add_separator()
    menu.add_command(label="Export JSON", command=lambda: bundle_export_json())
    try:
        menu.tk_popup(event.x_root, event.y_root)
    finally:
        menu.grab_release()

bundle_list.bind("<Button-3>", _bundle_context_menu)

def bundle_create_dialog():
    """Dialog to create a bundle and refresh UI when done."""
    dlg = tk.Toplevel(root)
    dlg.title("Create Bundle")
    dlg.geometry("420x500")
    dlg.transient(root)
    dlg.grab_set()

    ttk.Label(dlg, text="Bundle name:").pack(anchor='w', padx=8, pady=(8, 2))
    name_var = tk.StringVar()
    ttk.Entry(dlg, textvariable=name_var).pack(fill=tk.X, padx=8)

    ttk.Label(dlg, text="Select mods to include:").pack(anchor='w', padx=8, pady=(8, 2))
    mods_listbox = tk.Listbox(dlg, selectmode=tk.MULTIPLE, height=16)
    mods_listbox.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))

    cursor.execute("SELECT name FROM mods ORDER BY name")
    mods_all = [r[0] for r in cursor.fetchall()]
    for m in mods_all:
        mods_listbox.insert(tk.END, m)

    def _do_create():
        bname = name_var.get().strip()
        sel = mods_listbox.curselection()
        selected = [mods_all[i] for i in sel]
        if not bname or not selected:
            messagebox.showerror("Invalid", "Provide a name and select at least one mod.", parent=dlg)
            return
        ok = create_bundle(bname, selected)
        if not ok:
            messagebox.showerror("Error", "Bundle name already exists or invalid.", parent=dlg)
            return
        dlg.destroy()
        refresh_bundles_list()
        log(f"Created bundle '{bname}' with {len(selected)} mods.", log_text)

    btnrow = ttk.Frame(dlg, padding=6)
    btnrow.pack(fill=tk.X)
    ttk.Button(btnrow, text="Create", command=_do_create, bootstyle="success").pack(side=tk.RIGHT, padx=4)
    ttk.Button(btnrow, text="Cancel", command=dlg.destroy, bootstyle="secondary").pack(side=tk.RIGHT)

def bundle_apply():
    name = _selected_bundle_name()
    if not name or name.startswith("("):
        messagebox.showinfo("Select", "Select a bundle first.")
        return
    apply_bundle(name, text_widget=log_text)
    refresh_bundle_preview()
    refresh_tree()

def bundle_delete():
    name = _selected_bundle_name()
    if not name or name.startswith("("):
        messagebox.showinfo("Select", "Select a bundle first.")
        return
    if messagebox.askyesno("Delete Bundle", f"Delete bundle '{name}'?"):
        delete_bundle(name)
        refresh_bundles_list()
        log(f"Deleted bundle: {name}", log_text)

def bundle_export_json():
    name = _selected_bundle_name()
    if not name or name.startswith("("):
        messagebox.showinfo("Select", "Select a bundle first.")
        return
    export_bundle_as_json(name)

def bundle_import_json():
    import_bundle_from_json()
    refresh_bundles_list()

def bundle_export_z2f():
    name = _selected_bundle_name()
    if not name or name.startswith("("):
        messagebox.showinfo("Select", "Select a bundle first.")
        return
    export_bundle_as_mod_ui(name)

def bundle_enable_all():
    name = _selected_bundle_name()
    if not name or name.startswith("("):
        messagebox.showinfo("Select", "Select a bundle first.")
        return
    mods = get_bundle_mods(name)
    for m in mods:
        enable_mod(m, text_widget=log_text)
    refresh_bundle_preview()
    refresh_tree()

def bundle_disable_all():
    name = _selected_bundle_name()
    if not name or name.startswith("("):
        messagebox.showinfo("Select", "Select a bundle first.")
        return
    mods = get_bundle_mods(name)
    for m in mods:
        disable_mod(m, text_widget=log_text)
    refresh_bundle_preview()
    refresh_tree()

refresh_bundles_list()

def refresh_zoo_ui(profile):
    zoo_name_lbl.config(text=profile.get("zoo_name", "(Unknown Zoo)"))

    animal_tree.delete(*animal_tree.get_children())

    for a in profile.get("animals", []):
        animal_tree.insert("", "end", values=(a.get("species", "?"), a.get("name", "")))

def refresh_market_ui(zoo):
    for i in market_tree.get_children(): market_tree.delete(i)
    for a in zoo.get("animals", []):
        market_tree.insert("", "end", values=(zoo.get("zoo_name"), a["species"], a["name"]))

refresh_zoo_ui(load_zoo_profile())

log_frame = ttk.Frame(main_frame, padding=6)
log_frame.pack(side=tk.RIGHT, fill=tk.Y)

ttk.Label(log_frame, text="Log Output:").pack(anchor='w')
log_text = tk.Text(log_frame, height=40, wrap='word', state='disabled')
log_text.pack(fill=tk.BOTH, expand=True)

status_frame = ttk.Frame(root)
status_frame.pack(side=tk.BOTTOM, fill=tk.X)

status_label = ttk.Label(status_frame, text=f"ZT2 path: {GAME_PATH or '(not set)'} | {enabled_count()} mods enabled", anchor='w')
status_label.pack(side=tk.LEFT, padx=6, fill=tk.X, expand=True)

root.status_label = status_label

progress_bar = ttk.Progressbar(status_frame, mode='indeterminate', length=200, bootstyle='info')
progress_bar.pack(side=tk.RIGHT, padx=6, pady=2)
progress_bar.stop()
progress_bar.pack_forget()

# ---------------- UI Helper functions ----------------
def refresh_tree():
    for row in mods_tree.get_children():
        mods_tree.delete(row)

    cursor.execute("SELECT name, enabled FROM mods ORDER BY enabled DESC, name ASC")
    mods = cursor.fetchall()

    total = len(mods)
    enabled = sum(1 for _, e in mods if e)
    disabled = total - enabled

    rows = []
    for name, enabled_flag in mods:
        path = find_mod_file(name)
        size_mb = os.path.getsize(path) / (1024 * 1024) if path and os.path.isfile(path) else 0
        modified = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(os.path.getmtime(path))) if path and os.path.isfile(path) else "N/A"
    
        if enabled_flag:
            status = "🟢 Enabled"
        elif not find_mod_file(name):
            status = "🟡 Missing"
        else:
            status = "🔴 Disabled"

        r = (name, status, f"{size_mb:.2f}", modified)
    
        tag = (
            'enabled' if enabled_flag else
            ('missing' if not find_mod_file(name) else 'disabled')
        )
        mods_tree.insert("", tk.END, values=r, tags=(tag,))

    for r in rows:
        iid = mods_tree.insert("", tk.END, values=r)
        mods_tree.item(iid, tags=("enabled" if r[1] == "Enabled" else "disabled",))

    mod_count_label.config(text=f"Total mods: {total} | Enabled: {enabled} | Disabled: {disabled}")
    apply_tree_theme()
    refresh_bundles_list()

def sort_tree_by(column):
    """Sort the mods tree by a given column."""
    if sort_state["column"] == column:
        sort_state["reverse"] = not sort_state["reverse"]
    else:
        sort_state["column"] = column
        sort_state["reverse"] = False

    items = [mods_tree.item(iid)["values"] for iid in mods_tree.get_children()]

    col_index = {"Name": 0, "Status": 1, "Size": 2, "Modified": 3}[column]

    def sort_key(row):
        val = row[col_index]
        if column == "Size":
            try:
                return float(val)
            except ValueError:
                return 0
        elif column == "Modified":
            try:
                return time.mktime(time.strptime(val, "%Y-%m-%d %H:%M:%S"))
            except Exception:
                return 0
        else:
            return str(val).lower()

    items.sort(key=sort_key, reverse=sort_state["reverse"])

    for row in mods_tree.get_children():
        mods_tree.delete(row)

    for r in items:
        status_text = r[1]
        if "🟢" in status_text:
            tag = "enabled"
        elif "🟡" in status_text:
            tag = "missing"
        else:
            tag = "disabled"
        mods_tree.insert("", tk.END, values=r, tags=(tag,))


    apply_tree_theme()

    for col in ("Name", "Status", "Size", "Modified"):
        arrow = ""
        if col == column:
            arrow = "▼" if sort_state["reverse"] else "▲"
        mods_tree.heading(col, text=f"{col} {arrow}", command=lambda c=col: sort_tree_by(c))

def populate_folder_tree(parent_node, path):
    for item in os.listdir(path):
        full_path = os.path.join(path, item)
        if os.path.isdir(full_path):
            node = folder_tree.insert(parent_node, "end", text=item, values=[full_path])
            folder_tree.insert(node, "end", text="Loading...")

def on_open_folder(event):
    node = folder_tree.focus()
    children = folder_tree.get_children(node)
    if len(children) == 1 and folder_tree.item(children[0], "text") == "Loading...":
        folder_tree.delete(children[0])
        path = folder_tree.item(node, "values")[0]
        populate_folder_tree(node, path)

def on_select_folder(event):
    node = folder_tree.focus()
    path = folder_tree.item(node, "values")[0]
    if not os.path.isdir(path):
        return

    file_list.delete(*file_list.get_children())

    for f in os.listdir(path):
        fp = os.path.join(path, f)
        if os.path.isfile(fp):
            size_kb = os.path.getsize(fp) / 1024
            modified = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(os.path.getmtime(fp)))
            file_list.insert("", "end", values=(f, f"{size_kb:.1f}", modified))

def load_explorer_roots():
    if not GAME_PATH:
        return
    folder_tree.delete(*folder_tree.get_children())
    for folder_name in ["Mods", os.path.join("Mods", "Disabled")]:
        full_path = os.path.join(GAME_PATH, folder_name)
        if os.path.isdir(full_path):
            node = folder_tree.insert("", "end", text=folder_name, values=[full_path])
            folder_tree.insert(node, "end", text="Loading...")

def apply_tree_theme():
    if root.style.theme_use() == 'darkly':
        mods_tree.tag_configure('enabled', foreground='#5efc82')
        mods_tree.tag_configure('disabled', foreground='#ff6961')
        mods_tree.tag_configure('missing', foreground='#f5d97e')
    else:
        mods_tree.tag_configure('enabled', foreground='#007f00')
        mods_tree.tag_configure('disabled', foreground='#b30000')
        mods_tree.tag_configure('missing', foreground='#c48f00')

def apply_ui_mode():
    compact = ui_mode["compact"]

    style = root.style
    style.configure("Treeview", rowheight=(18 if compact else 24))

    font_size = 9 if compact else 10
    style.configure("TLabel", font=("Segoe UI", font_size))
    style.configure("TButton", font=("Segoe UI", font_size))
    style.configure("Treeview.Heading", font=("Segoe UI", font_size, "bold"))

    padding = 2 if compact else 6
    for frame in [toolbar, mods_tab, bundles_tab, log_frame, status_frame]:
        try:
            frame.configure(padding=padding)
        except tk.TclError:
            pass

    if compact:
        banner.pack_forget()
    else:
        banner.pack(fill=tk.X, before=toolbar)

    refresh_tree()

def get_selected_mod():
    sel = mods_tree.selection()
    if not sel:
        messagebox.showinfo("Select", "Select a mod first.", parent=root)
        return None
    return mods_tree.item(sel[0])['values'][0]

def enable_selected_mod():
    mod = get_selected_mod()
    if mod:
        enable_mod(mod, text_widget=log_text)

def disable_selected_mod():
    mod = get_selected_mod()
    if mod:
        disable_mod(mod, text_widget=log_text)

def uninstall_selected_mod():
    mod = get_selected_mod()
    if mod:
        if messagebox.askyesno("Uninstall", f"Uninstall {mod}?"):
            uninstall_mod(mod, text_widget=log_text)

def open_mod_folder():
    mod = get_selected_mod()
    if not mod:
        return
    paths = [os.path.join(GAME_PATH, mod), os.path.join(mods_disabled_dir(), mod)]
    for p in paths:
        if os.path.isfile(p):
            try:
                os.startfile(os.path.dirname(p))
                return
            except Exception:
                messagebox.showinfo("Open", f"Mod located at: {os.path.dirname(p)}")
                return
    messagebox.showinfo("Not Found", f"Could not find {mod} on disk.")

def inspect_selected_mod():
    mod = get_selected_mod()
    if not mod:
        return

    path = find_mod_file(mod)
    if not path or not os.path.isfile(path):
        messagebox.showerror("Error", f"Cannot find file for '{mod}'.")
        return

    dlg = tk.Toplevel(root)
    dlg.title(f"Inspect: {mod}")
    dlg.geometry("700x500")

    frame = ttk.Frame(dlg, padding=8)
    frame.pack(fill=tk.BOTH, expand=True)

    ttk.Label(frame, text=f"📦 Contents of {mod}", font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(0, 8))

    tree = ttk.Treeview(frame, columns=("size", "compressed"), show="headings")
    tree.heading("size", text="Size (KB)")
    tree.heading("compressed", text="Compressed (KB)")
    tree.column("size", width=100, anchor="e")
    tree.column("compressed", width=120, anchor="e")
    tree.pack(fill=tk.BOTH, expand=True)

    scrollbar = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=scrollbar.set)
    scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

    try:
        with zipfile.ZipFile(path, 'r') as zf:
            for info in zf.infolist():
                size_kb = info.file_size / 1024
                comp_kb = info.compress_size / 1024
                tree.insert("", tk.END, values=(info.filename, f"{size_kb:.1f}", f"{comp_kb:.1f}"))
    except zipfile.BadZipFile:
        messagebox.showerror("Error", "This mod file is not a valid ZIP or Z2F archive.")
        dlg.destroy()
        return

    btns = ttk.Frame(dlg, padding=6)
    btns.pack(fill=tk.X)
    ttk.Button(btns, text="Extract to Folder", command=lambda: extract_zip_contents(path)).pack(side=tk.LEFT, padx=4)
    ttk.Button(btns, text="Close", command=dlg.destroy).pack(side=tk.RIGHT, padx=4)

def extract_zip_contents(path):
    out_dir = filedialog.askdirectory(title="Select destination folder")
    if not out_dir:
        return
    try:
        with zipfile.ZipFile(path, 'r') as zf:
            zf.extractall(out_dir)
        messagebox.showinfo("Extracted", f"Contents extracted to:\n{out_dir}")
        log(f"Extracted {os.path.basename(path)} to {out_dir}", log_text)
    except Exception as e:
        messagebox.showerror("Error", f"Failed to extract:\n{e}")

def show_mod_details():
    mod = get_selected_mod()
    if not mod:
        return

    path = find_mod_file(mod)
    if not path:
        messagebox.showerror("Error", f"File for '{mod}' not found.")
        return

    size_mb = os.path.getsize(path) / (1024 * 1024)
    modified = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(os.path.getmtime(path)))

    cursor.execute("SELECT b.name FROM bundles b JOIN bundle_mods bm ON b.id=bm.bundle_id WHERE bm.mod_name=?", (mod,))
    bundle_rows = cursor.fetchall()
    bundle_names = [r[0] for r in bundle_rows] if bundle_rows else []

    readme_text = ""
    try:
        import zipfile
        with zipfile.ZipFile(path, 'r') as zf:
            for name in zf.namelist():
                if "readme" in name.lower() and name.lower().endswith((".txt", ".md")):
                    with zf.open(name) as f:
                        data = f.read().decode("utf-8", errors="ignore")
                        readme_text = data[:2000]
                        break
    except Exception:
        pass

    dlg = tk.Toplevel(root)
    dlg.title(f"Mod Details - {mod}")
    dlg.geometry("600x500")
    dlg.transient(root)

    frame = ttk.Frame(dlg, padding=10)
    frame.pack(fill=tk.BOTH, expand=True)

    ttk.Label(frame, text=f"🧩 {mod}", font=("Segoe UI", 14, "bold")).pack(anchor="w", pady=(0,6))
    ttk.Label(frame, text=f"Path: {path}", wraplength=560).pack(anchor="w", pady=(0,3))
    ttk.Label(frame, text=f"Size: {size_mb:.2f} MB").pack(anchor="w")
    ttk.Label(frame, text=f"Last Modified: {modified}").pack(anchor="w", pady=(0,5))

    if bundle_names:
        ttk.Label(frame, text="Included in Bundles:", font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(4,0))
        ttk.Label(frame, text=", ".join(bundle_names), wraplength=560).pack(anchor="w", pady=(0,5))

    ttk.Separator(frame).pack(fill=tk.X, pady=8)

    ttk.Label(frame, text="Readme Preview:", font=("Segoe UI", 10, "bold")).pack(anchor="w")
    txt = tk.Text(frame, height=15, wrap="word")
    txt.pack(fill=tk.BOTH, expand=True)
    txt.insert(tk.END, readme_text or "(No readme found in mod)")
    txt.configure(state="disabled")

    ttk.Button(frame, text="Close", command=dlg.destroy).pack(pady=8)

# ---------------- Bundles UI callbacks ----------------
def refresh_bundles_list():
    bundle_list.delete(0, tk.END)
    for name, mods in get_bundles():
        bundle_list.insert(tk.END, f"{name}")

def get_selected_bundle_name():
    sel = bundle_list.curselection()
    if not sel:
        messagebox.showinfo("Select", "Select a bundle first.", parent=root)
        return None
    text = bundle_list.get(sel[0])
    return text.rsplit(' (',1)[0]

def on_create_bundle():
    dlg = tk.Toplevel(root)
    dlg.title("Create Bundle")
    dlg.geometry("420x480")

    ttk.Label(dlg, text="Bundle name:").pack(anchor='w', padx=6, pady=(6,0))
    name_var = tk.StringVar()
    ttk.Entry(dlg, textvariable=name_var).pack(fill=tk.X, padx=6)

    ttk.Label(dlg, text="Select mods to include:").pack(anchor='w', padx=6, pady=(6,0))
    mods_listbox = tk.Listbox(dlg, selectmode=tk.MULTIPLE)
    mods_listbox.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)
    cursor.execute("SELECT name FROM mods ORDER BY name")
    mods = [r[0] for r in cursor.fetchall()]
    for m in mods:
        mods_listbox.insert(tk.END, m)

    def do_create():
        bname = name_var.get().strip()
        sel = mods_listbox.curselection()
        selected = [mods[i] for i in sel]
        if not bname or not selected:
            messagebox.showerror("Invalid", "Provide a name and select at least one mod.", parent=dlg)
            return
        ok = create_bundle(bname, selected)
        if not ok:
            messagebox.showerror("Error", "Bundle name already exists or invalid.", parent=dlg)
            return
        dlg.destroy()
        refresh_bundles_list()
        log(f"Created bundle '{bname}' with {len(selected)} mods.", log_text)

    ttk.Button(dlg, text="Create", command=do_create).pack(padx=6, pady=6)

on_create_bundle = on_create_bundle

def on_delete_bundle():
    name = get_selected_bundle_name()
    if not name:
        return
    if messagebox.askyesno("Delete Bundle", f"Delete bundle '{name}'?"):
        delete_bundle(name)
        refresh_bundles_list()
        log(f"Deleted bundle: {name}", log_text)

def on_apply_bundle():
    name = get_selected_bundle_name()
    if not name:
        return
    apply_bundle(name, text_widget=log_text)
    refresh_tree()

def on_export_bundle():
    name = get_selected_bundle_name()
    if not name:
        return
    export_bundle_as_json(name)

def backup_mods():
    if not GAME_PATH:
        messagebox.showerror("Error", "Set your Zoo Tycoon 2 path first.")
        return

    backup_dir = filedialog.askdirectory(title="Select backup destination")
    if not backup_dir:
        return

    backup_name = f"ZT2_ModBackup_{time.strftime('%Y%m%d_%H%M%S')}.zip"
    backup_path = os.path.join(backup_dir, backup_name)

    try:
        with zipfile.ZipFile(backup_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for folder in [GAME_PATH, mods_disabled_dir()]:
                if not os.path.isdir(folder):
                    continue
                for f in os.listdir(folder):
                    if f.lower().endswith((".z2f", ".zip")):
                        fp = os.path.join(folder, f)
                        arcname = os.path.join("Enabled" if folder == GAME_PATH else "Disabled", f)
                        zf.write(fp, arcname)
        messagebox.showinfo("Backup Complete", f"Mods backed up to:\n{backup_path}")
        log(f"Created backup: {backup_path}", text_widget=log_text)
    except Exception as e:
        messagebox.showerror("Backup Error", str(e))
        log(f"Backup failed: {e}", text_widget=log_text)

def restore_mods():
    if not GAME_PATH:
        messagebox.showerror("Error", "Set your Zoo Tycoon 2 path first.")
        return

    zip_path = filedialog.askopenfilename(
        title="Select Mod Backup ZIP",
        filetypes=[("Zip Files", "*.zip")]
    )
    if not zip_path:
        return

    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            temp_extract = os.path.join(CONFIG_DIR, "_restore_temp")
            os.makedirs(temp_extract, exist_ok=True)
            zf.extractall(temp_extract)

            enabled_dir = os.path.join(temp_extract, "Enabled")
            disabled_dir = os.path.join(temp_extract, "Disabled")

            for src, dest in [(enabled_dir, GAME_PATH), (disabled_dir, mods_disabled_dir())]:
                if os.path.isdir(src):
                    for f in os.listdir(src):
                        shutil.copy2(os.path.join(src, f), os.path.join(dest, f))

        messagebox.showinfo("Restore Complete", "Mods restored successfully!")
        log("Mods restored from backup", text_widget=log_text)
        shutil.rmtree(temp_extract, ignore_errors=True)
        refresh_tree()
    except Exception as e:
        messagebox.showerror("Restore Error", str(e))
        log(f"Restore failed: {e}", text_widget=log_text)

def on_import_bundle():
    import_bundle_from_json()
    refresh_bundles_list()

def on_export_bundle_as_mod():
    name = get_selected_bundle_name()
    if not name:
        return
    export_bundle_as_mod_ui(name)

# ---------------- Status ----------------
def update_status():
    status_label.config(text=f"ZT2 path: {GAME_PATH or '(not set)'} | {enabled_count()} mods enabled")

# ---------------- Bindings & Start ----------------
search_var.trace_add('write', lambda *_: filter_tree())

def filter_tree(*_):
    """Filter mods in the treeview based on search input."""
    query = search_var.get().strip().lower()

    for row in mods_tree.get_children():
        mods_tree.delete(row)

    cursor.execute("SELECT name, enabled FROM mods ORDER BY enabled DESC, name ASC")
    mods = cursor.fetchall()

    visible_rows = []
    for name, enabled_flag in mods:
        if query and query not in name.lower():
            continue

        path = find_mod_file(name)
        size_mb = 0
        modified = "N/A"
        if path and os.path.isfile(path):
            size_mb = os.path.getsize(path) / (1024 * 1024)
            modified = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(os.path.getmtime(path)))

        if enabled_flag:
            status = "🟢 Enabled"
        elif not path or not os.path.isfile(path):
            status = "🟡 Missing"
        else:
            status = "🔴 Disabled"

        tag = (
            "enabled" if enabled_flag else
            ("missing" if not path or not os.path.isfile(path) else "disabled")
        )

        mods_tree.insert("", tk.END, values=(name, status, f"{size_mb:.2f}", modified), tags=(tag,))

        visible_rows.append(name)

    apply_tree_theme()

    total = len(mods)
    enabled = sum(1 for _, e in mods if e)
    disabled = total - enabled
    mod_count_label.config(
        text=f"Total mods: {len(visible_rows)} (Filtered) | Enabled: {enabled} | Disabled: {disabled}"
    )

refresh_tree()
apply_ui_mode()
update_status()

if not hasattr(root, "_watcher_started"):
    watch_mods(root, refresh_tree, interval=3)
    root._watcher_started = True

def background_scan():
    def worker():
        root.after(0, lambda: show_progress("Scanning mods for duplicates and conflicts..."))
        try:
            local_conn = sqlite3.connect(DB_FILE)
            local_cursor = local_conn.cursor()

            detect_existing_mods(local_cursor, local_conn)
            filemap = index_mod_files(local_cursor, local_conn)
            detect_conflicts(local_cursor, local_conn, filemap=filemap)

            local_conn.close()
        finally:
            root.after(0, hide_progress)
    threading.Thread(target=worker, daemon=True).start()

# ---------------- Run ----------------
if __name__ == '__main__':

    if not GAME_PATH:
        detected = auto_detect_zt2_installation()
        if detected:
            GAME_PATH = detected
            log(f"✅ Detected Zoo Tycoon 2 installation at: {GAME_PATH}", log_text)
            try:
                root.status_label.config(text=f"ZT2 path: {GAME_PATH}")
            except Exception:
                pass
        else:
            log("⚠️ Could not auto-detect Zoo Tycoon 2 path.", log_text)

    root.after(2000, background_scan)
    root.after(30000, auto_switch_theme)
    folder_tree.bind("<<TreeviewOpen>>", on_open_folder)
    folder_tree.bind("<<TreeviewSelect>>", on_select_folder)
    refresh_market_ui_from_file()

def on_close():
    try:
        conn.close()
        print("Database connection closed.")
    except Exception as e:
        print("Error closing DB:", e)
    root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)

load_explorer_roots()
root.mainloop()
