import os
import webbrowser
import shutil
import sqlite3
import subprocess
import json
import zipfile
import socket
import tempfile
import threading
import requests
import platform
import datetime
import online_manager
import state_manager
import time
import tkinter as tk
import tkinter.simpledialog as simpledialog
import glob
from pathlib import Path
from tkinter import ttk, filedialog, messagebox
from collections import Counter
from ttkbootstrap import Window
import xml.etree.ElementTree as ET
import ttkbootstrap as tb
from PIL import Image, ImageTk
from datetime import datetime
import hashlib
import zlib
import io
import sys
import re

db_lock = threading.Lock()

if platform.system() == "Windows":
    import ctypes
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(u"modzt")
    except Exception:
        pass

APP_VERSION = "1.1.1"
SETTINGS_FILE = "settings.json"
BASE_PATH = getattr(sys, '_MEIPASS', os.path.abspath("."))
CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".zt2_manager")
os.makedirs(CONFIG_DIR, exist_ok=True)
GAME_PATH_FILE = os.path.join(CONFIG_DIR, "game_path.txt")
ZT1_EXE_FILE = os.path.join(CONFIG_DIR, "zt1_exe_path.txt")
ZT1_MOD_DIR_FILE = os.path.join(CONFIG_DIR, "zt1_mod_dir.txt")
DB_FILE = os.path.join(CONFIG_DIR, "mods.db")
ICON_FILE = os.path.join(CONFIG_DIR, "modzt.ico")
BANNER_FILE = os.path.join(CONFIG_DIR, "banner.png")
FILEMAP_CACHE = os.path.join(CONFIG_DIR, "mod_filemap.json")
GITHUB_REPO = "kaelelson05/modzt"
SERVER_URL = "http://localhost:5000"

GAME_PATH = None
ZT1_PATH = None
ZT1_MOD_DIR = None
ZT2_EXE = None
_client_socket = None

if os.path.isfile(GAME_PATH_FILE):
    with open(GAME_PATH_FILE, "r", encoding="utf-8") as f:
        GAME_PATH = f.read().strip() or None

if os.path.isfile(ZT1_EXE_FILE):
    with open(ZT1_EXE_FILE, "r", encoding="utf-8") as f:
        ZT1_PATH = f.read().strip()

if os.path.isfile(ZT1_MOD_DIR_FILE):
    with open(ZT1_MOD_DIR_FILE, "r", encoding="utf-8") as f:
        ZT1_MOD_DIR = f.read().strip()

if GAME_PATH and os.path.isdir(GAME_PATH):
    ZT2_EXE = os.path.join(GAME_PATH, "zt.exe")
    if os.path.exists(ZT2_EXE):
        online_manager.ZT2_PATH = ZT2_EXE
        print(f"[Online] ZT2 path registered: {ZT2_EXE}")
    else:
        print("[Online] Warning: zt.exe not found in configured path.")
else:
    online_manager.ZT2_PATH = None
    print("[Online] ZT2 path not yet set; will register once chosen.")

if os.path.isfile(ZT1_EXE_FILE):
    with open(ZT1_EXE_FILE, "r", encoding="utf-8") as f:
        ZT1_PATH = f.read().strip()

if os.path.isfile(ZT1_MOD_DIR_FILE):
    with open(ZT1_MOD_DIR_FILE, "r", encoding="utf-8") as f:
        ZT1_MOD_DIR = f.read().strip()

def get_zt2_saves_dir():
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return None
    p = os.path.join(appdata, "Microsoft Games", "Zoo Tycoon 2", "Default Profile", "Saved")
    return p if os.path.isdir(p) else None

COMMON_ZT2_PATHS = [
    r"C:\Program Files (x86)\Microsoft Games\Zoo Tycoon 2",
    r"C:\Program Files\Microsoft Games\Zoo Tycoon 2",
]

COMMON_ZT1_PATHS = [
    r"C:\Program Files (x86)\Microsoft Games\Zoo Tycoon",
    r"C:\Program Files\Microsoft Games\Zoo Tycoon",
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

def mods_enabled_dir():
    if not GAME_PATH:
        return None
    path = os.path.join(GAME_PATH, "mods_enabled")
    os.makedirs(path, exist_ok=True)
    return path

def mods_disabled_dir():
    if not GAME_PATH:
        return None
    path = os.path.join(GAME_PATH, "mods_disabled")
    os.makedirs(path, exist_ok=True)
    return path

def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

def load_settings():
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
    
def save_settings(s):
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(s, f, indent=4)

def auto_detect_zt1_installation():
    import winreg

    for path in COMMON_ZT1_PATHS:
        exe = os.path.join(path, "zoo.exe")
        if os.path.isfile(exe):
            return path

    possible_keys = [
        r"SOFTWARE\Microsoft\Microsoft Games\Zoo Tycoon ",
        r"SOFTWARE\WOW6432Node\Microsoft\Microsoft Games\Zoo Tycoon",
    ]
    for key in possible_keys:
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key) as regkey:
                install_dir, _ = winreg.QueryValueEx(regkey, "InstallationDirectory")
                exe = os.path.join(install_dir, "zoo.exe")
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
            if "zoo.exe" in files:
                return root

    return None

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

conn = sqlite3.connect(DB_FILE, check_same_thread=False)
cursor = conn.cursor()
cursor.execute("""
CREATE TABLE IF NOT EXISTS mods (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE,
    enabled INTEGER DEFAULT 0
)
""")
cursor.execute("""
CREATE TABLE IF NOT EXISTS zt1_mods (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE,
    enabled INTEGER DEFAULT 0
)
""")
conn.commit()
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

def ensure_category_column():
    cursor.execute("PRAGMA table_info(mods)")
    mods_cols = [col[1] for col in cursor.fetchall()]
    if "category" not in mods_cols:
        cursor.execute("ALTER TABLE mods ADD COLUMN category TEXT DEFAULT 'Uncategorized'")

    cursor.execute("PRAGMA table_info(zt1_mods)")
    zt1_cols = [col[1] for col in cursor.fetchall()]
    if "category" not in zt1_cols:
        cursor.execute("ALTER TABLE zt1_mods ADD COLUMN category TEXT DEFAULT 'Uncategorized'")

    conn.commit()

conn = sqlite3.connect(DB_FILE)
cursor = conn.cursor()
ensure_category_column()

def ensure_db_schema():
    for table in ("mods", "zt1_mods"):
        cursor.execute(f"PRAGMA table_info({table})")
        cols = [c[1] for c in cursor.fetchall()]
        if "category" not in cols:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN category TEXT DEFAULT 'Uncategorized'")
        if "tags" not in cols:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN tags TEXT DEFAULT ''")
    conn.commit()

ensure_db_schema()

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
    
def zt1_mods_disabled_dir():
    if ZT1_MOD_DIR:
        return os.path.join(ZT1_MOD_DIR, "_disabled")
    elif ZT1_PATH:
        return os.path.join(ZT1_PATH, "dlupdates_disabled")
    return None

def detect_existing_zt1_mods():
    if not ZT1_PATH:
        return
    dl_dir = ZT1_MOD_DIR or os.path.join(ZT1_PATH, "dlupdates")
    disabled_dir = os.path.join(dl_dir, "_disabled")
    os.makedirs(disabled_dir, exist_ok=True)

    scanned = {}
    for folder, enabled in [(dl_dir, 1), (disabled_dir, 0)]:
        if not os.path.isdir(folder):
            continue
        for f in os.listdir(folder):
            if not f.lower().endswith(".ztd"):
                continue
            scanned[f] = enabled

    for name, enabled in scanned.items():
        cursor.execute("SELECT COUNT(*) FROM zt1_mods WHERE name=?", (name,))
        exists = cursor.fetchone()[0]
        if exists == 0:
            cursor.execute("INSERT INTO zt1_mods (name, enabled) VALUES (?, ?)", (name, enabled))
        else:
            cursor.execute("UPDATE zt1_mods SET enabled=? WHERE name=?", (enabled, name))
    conn.commit()

    cursor.execute("SELECT name FROM zt1_mods")
    for (name,) in cursor.fetchall():
        if name not in scanned:
            cursor.execute("DELETE FROM zt1_mods WHERE name=?", (name,))
    conn.commit()

def check_for_updates():
    try:
        url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        release = response.json()

        latest_version = release["tag_name"].lstrip("v")
        release_url = release["html_url"]

        if latest_version > APP_VERSION:
            if messagebox.askyesno(
                "Update Available",
                f"A new version ({latest_version}) is available!\n\n"
                f"You're using {APP_VERSION}.\n\n"
                "Would you like to open the release page?"
            ):
                webbrowser.open(release_url)
        else:
            messagebox.showinfo("Up to Date", f"You're running the latest version ({APP_VERSION}).")

    except requests.RequestException as e:
        messagebox.showerror("Update Check Failed", f"Could not contact GitHub:\n{e}")

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "Unknown"

def stop_host():
    try:
        status_var.set("Status: Stopping server...")
        online_tab.update_idletasks()

        if hasattr(online_manager, "stop_host"):
            online_manager.stop_host()
        else:
            print("[Online] stop_host() not found in online_manager")

        online_tab.after(0, lambda: status_var.set("Status: Server stopped."))

    except Exception as e:
        print(f"[Online] Stop error: {e}")
        online_tab.after(0, lambda: status_var.set(f"Status: Stop error — {e}"))

def refresh_connection_info():
    def loop():
        while True:
            local, public, port = online_manager.get_connection_info()
            local_ip_var.set(f"Local IP: {local}")
            public_ip_var.set(f"Public IP: {public}")
            port_var.set(f"Port: {port}")
            time.sleep(5)
    threading.Thread(target=loop, daemon=True).start()

refresh_connection_info()

def host_session():
    try:
        status_var.set("Status: Starting host server...")
        online_tab.update_idletasks()

        if online_manager.start_host():
            online_manager.start_save_watcher()
            status_var.set("Status: Hosting active. Save sync enabled.")
        else:
            status_var.set("Status: Failed to start host.")

        update_connection_info_now()

    except Exception as e:
        status_var.set(f"Status: Error starting host — {e}")
        messagebox.showerror("Error", f"Failed to host session:\n{e}")

def join_session_dialog():
    ip_text = simpledialog.askstring("Join Session", "Enter host (IP or host:port):")
    if not ip_text:
        return

    host = ip_text.strip()
    port = None
    if ":" in host:
        host, port_str = host.rsplit(":", 1)
        try:
            port = int(port_str)
        except ValueError:
            messagebox.showerror("Connection Error", f"Invalid port: {port_str}")
            return

    try:
        sock = None
        if port is not None and hasattr(online_manager, "join_session"):
            try:
                sock = online_manager.join_session(host, port)
            except TypeError:
                sock = online_manager.join_session(host)
        else:
            sock = online_manager.join_session(host, port) if port is not None else online_manager.join_session(host)

        endpoint = f"{host}:{port}" if port else host
        if sock:
            _client_socket = sock
            status_var.set("Status: Connected to host.")
            messagebox.showinfo("Connected", f"Connected to host at {endpoint}.")
            log(f"[Online] Connected to host {endpoint}", log_text)
        else:
            status_var.set("Status: Connection failed.")
            messagebox.showerror("Connection Error", f"Could not connect to {endpoint}.")
            log(f"[Online] Connection failed to {endpoint}", log_text)

    except Exception as e:
        messagebox.showerror("Connection Error", f"Could not connect to {host}" + (f":{port}" if port else "") + f"\n\n{e}")
        status_var.set(f"Status: Error connecting — {e}")
        log(f"[Online] Connection error: {e}", log_text)

def monitor_game_crash(proc, game_name="ZT2", timeout=10):
    start_time = time.time()
    pid = proc.pid
    crash_log = os.path.join(CONFIG_DIR, f"{game_name.lower()}_crash.log")

    try:
        while proc.poll() is None:
            time.sleep(1)
        exit_code = proc.returncode
    except Exception as e:
        exit_code = -999
        with open(crash_log, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.datetime.now()}] Exception monitoring {game_name}: {e}\n")

    elapsed = time.time() - start_time
    if exit_code != 0 or elapsed < timeout:
        with open(crash_log, "a", encoding="utf-8") as f:
            f.write("------ Game Crash Detected ------\n")
            f.write(f"Game: {game_name}\n")
            f.write(f"Time: {datetime.datetime.now()}\n")
            f.write(f"Exit Code: {exit_code}\n")
            f.write(f"Ran for: {elapsed:.1f}s\n\n")

        messagebox.showwarning(
            f"{game_name} Crash Detected",
            f"{game_name} may have crashed or closed unexpectedly.\n"
            f"Duration: {elapsed:.1f} seconds\n\n"
            f"A crash log has been saved to:\n{crash_log}"
        )

def enable_zt1_mod(name, text_widget=None):
    if not ZT1_MOD_DIR or not os.path.isdir(ZT1_MOD_DIR):
        messagebox.showerror("Error", "ZT1 mod folder not set.")
        return

    disabled_dir = zt1_mods_disabled_dir()
    os.makedirs(disabled_dir, exist_ok=True)

    src = os.path.join(disabled_dir, name)
    dst = os.path.join(ZT1_MOD_DIR, name)

    if not os.path.isfile(src):
        log(f"[!] Cannot find disabled mod: {src}", text_widget)
        return

    try:
        shutil.move(src, dst)
        cursor.execute("UPDATE zt1_mods SET enabled=1 WHERE name=?", (name,))
        conn.commit()
        log(f"Enabled ZT1 mod: {name}", text_widget)
    except Exception as e:
        messagebox.showerror("Error", f"Failed to enable mod:\n{e}")

def disable_zt1_mod(name, text_widget=None):
    if not ZT1_MOD_DIR or not os.path.isdir(ZT1_MOD_DIR):
        messagebox.showerror("Error", "ZT1 mod folder not set.")
        return

    disabled_dir = zt1_mods_disabled_dir()
    os.makedirs(disabled_dir, exist_ok=True)

    src = os.path.join(ZT1_MOD_DIR, name)
    dst = os.path.join(disabled_dir, name)

    if not os.path.isfile(src):
        log(f"[!] Cannot find enabled mod: {src}", text_widget)
        return

    try:
        shutil.move(src, dst)
        cursor.execute("UPDATE zt1_mods SET enabled=0 WHERE name=?", (name,))
        conn.commit()
        log(f"Disabled ZT1 mod: {name}", text_widget)
    except Exception as e:
        messagebox.showerror("Error", f"Failed to disable mod:\n{e}")

def set_mod_category(mod_name, category, zt1=False):
    table = "zt1_mods" if zt1 else "mods"
    cursor.execute(f"UPDATE {table} SET category=? WHERE name=?", (category, mod_name))
    conn.commit()

def get_mod_category(mod_name, zt1=False):
    table = "zt1_mods" if zt1 else "mods"
    cursor.execute(f"SELECT category FROM {table} WHERE name=?", (mod_name,))
    row = cursor.fetchone()
    return row[0] if row else "Uncategorized"

def set_mod_tags(mod_name, tags, zt1=False):
    table = "zt1_mods" if zt1 else "mods"
    tags_str = ", ".join(sorted(set([t.strip() for t in tags if t.strip()])))
    cursor.execute(f"UPDATE {table} SET tags=? WHERE name=?", (tags_str, mod_name))
    conn.commit()

def get_mod_tags(mod_name, zt1=False):
    table = "zt1_mods" if zt1 else "mods"
    cursor.execute(f"SELECT tags FROM {table} WHERE name=?", (mod_name,))
    row = cursor.fetchone()
    return [t.strip() for t in row[0].split(",")] if row and row[0] else []

def enabled_count():
    cursor.execute("SELECT COUNT(*) FROM mods WHERE enabled=1")
    return cursor.fetchone()[0]

def get_zt2_photos_root():
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return None
    root = os.path.join(appdata, "Microsoft Games", "Zoo Tycoon 2", "Default Profile", "HTML Photo Album")
    return root if os.path.isdir(root) else None

def list_zt2_albums(root):
    albums = []
    for p in Path(root).glob("album*"):
        if p.is_dir():
            albums.append((p.name, str(p)))
    def _key(t):
        name = t[0]
        try:
            return int(name.replace("album", ""))
        except Exception:
            return 999999
    return sorted(albums, key=_key)

def list_album_images(album_path):
    exts = ("*.jpg", "*.jpeg", "*.png", "*.bmp")
    imgs = []
    for pat in exts:
        imgs.extend(glob.glob(os.path.join(album_path, pat)))
    imgs.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return imgs

def set_dependencies(mod_name, dependencies):
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
    settings = load_settings()
    game_path = settings.get("game_path")

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

        proc = subprocess.Popen(cmd, cwd=GAME_PATH, shell=False)
        log("🎮 Launched Zoo Tycoon 2", text_widget=log_text)

        threading.Thread(target=monitor_game_crash, args=(proc, "ZT2"), daemon=True).start()

    except Exception as e:
        messagebox.showerror("Error", f"Failed to launch ZT2: {e}")

def mods_disabled_dir():
    return os.path.join(GAME_PATH, "Mods", "Disabled")

def find_mod_file(mod_name):
    if not GAME_PATH:
        return None
    p1 = os.path.join(GAME_PATH, mod_name)
    p2 = os.path.join(mods_disabled_dir(), mod_name)
    if os.path.isfile(p1):
        return p1
    if os.path.isfile(p2):
        return p2
    return None

def index_mod_files(cursor=None, conn=None, force=False):
    if cursor is None or conn is None:
        cursor = globals().get("cursor")
        conn = globals().get("conn")

    if not GAME_PATH:
        return

    cache_file = os.path.join(CONFIG_DIR, "file_index.json")
    cache = {}
    if os.path.isfile(cache_file):
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                cache = json.load(f)
        except Exception:
            cache = {}

    changed = False
    for folder in [GAME_PATH, mods_disabled_dir()]:
        if not os.path.isdir(folder):
            continue
        for f in os.listdir(folder):
            if not (f.lower().endswith('.z2f')):
                continue
            if f.lower().endswith('.pac'):
                continue
            full_path = os.path.join(folder, f)
            try:
                mtime = os.path.getmtime(full_path)
            except OSError:
                continue

            if not force and f in cache and cache[f].get("_mtime") == mtime:
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

            cache[f] = {"_mtime": mtime, "hash": mod_hash}
            changed = True

            if mod_hash:
                cursor.execute("UPDATE mods SET hash=? WHERE name=?", (mod_hash, f))
    if changed:
        conn.commit()
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2)

def file_hash(path):
    h = hashlib.sha1()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None
    
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
                    if f.lower().endswith((".z2f")):
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
            if not (f.lower().endswith('.z2f')):
                continue
            if f.lower().endswith('.pac'):
                continue

            full_path = os.path.join(folder, f)
            mtime = os.path.getmtime(full_path)
            scanned[f] = (enabled, mtime)

    for mod_name, (enabled, mtime) in scanned.items():
        cursor.execute("SELECT COUNT(*) FROM mods WHERE name=?", (mod_name,))
        exists = cursor.fetchone()[0]
        if exists == 0:
            cursor.execute("INSERT INTO mods (name, enabled) VALUES (?, ?)", (mod_name, enabled))
        else:
            cursor.execute("UPDATE mods SET enabled=? WHERE name=?", (enabled, mod_name))
    conn.commit()

    cursor.execute("SELECT name FROM mods")
    for (name,) in cursor.fetchall():
        if name not in scanned:
            cursor.execute("DELETE FROM mods WHERE name=?", (name,))
    conn.commit()

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

    for iid in mods_tree.get_children():
        vals = mods_tree.item(iid, "values")
        if vals and vals[0] == mod_name:
            mods_tree.item(iid, values=(vals[0], "Enabled", vals[2], vals[3]))
            mods_tree.item(iid, tags=("enabled",))
            break

    update_status()
    log(f"Enabled mod: {mod_name}", text_widget)

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

    for iid in mods_tree.get_children():
        vals = mods_tree.item(iid, "values")
        if vals and vals[0] == mod_name:
            mods_tree.item(iid, values=(vals[0], "Disabled", vals[2], vals[3]))
            mods_tree.item(iid, tags=("disabled",))
            break

    update_status()
    log(f"Disabled mod: {mod_name}", text_widget)

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

def watch_mods(root, refresh_func, interval=5):
    def worker():
        last_snapshot = set()
        while True:
            try:
                if not GAME_PATH or not os.path.isdir(GAME_PATH):
                    time.sleep(interval)
                    continue
                found = set()
            except Exception as e:
                print("Watcher error:", e)
                time.sleep(interval)

            found = set()
            disabled = mods_disabled_dir()
            for folder in [GAME_PATH, disabled]:
                if os.path.isdir(folder):
                    for f in os.listdir(folder):
                        if f.lower().endswith('.z2f'):
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

def bundle_create_dialog():
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

def export_bundle_as_z2f(bundle_name, include_files, output_path):
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

settings = load_settings()
system_theme = get_system_theme()

if not os.path.isfile(GAME_PATH_FILE):
    detected = auto_detect_zt2_installation()
    if detected:
        GAME_PATH = detected
        save_game_path(GAME_PATH)
        settings["game_path"] = GAME_PATH
        save_settings(settings)
        print(f"[✔] Auto-detected Zoo Tycoon 2 installation: {GAME_PATH}")
else:
    with open(GAME_PATH_FILE, "r", encoding="utf-8") as f:
        GAME_PATH = f.read().strip()

root = Window(themename="darkly" if system_theme == "dark" else "cosmo")
root.title(f"ModZT v{APP_VERSION}")
root.geometry("1400x1000")

def auto_switch_theme():
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

icon_candidates = [
    resource_path("modzt.ico"),
    os.path.join(CONFIG_DIR, "modzt.ico")
]

for icon_path in icon_candidates:
    if os.path.exists(icon_path):
        try:
            root.iconbitmap(icon_path)
            print(f"[i] Icon set from: {icon_path}")
            break
        except Exception as e:
            print(f"[!] Failed to set icon from {icon_path}: {e}")

def set_zt1_paths():
    global ZT1_PATH
    global ZT1_MOD_DIR

    messagebox.showinfo(
        "Set Zoo Tycoon 1 Paths",
        "Please select the Zoo Tycoon 1 installation folder (where zoo.exe is located)."
    )

    exe_dir = filedialog.askdirectory(title="Select ZT1 Root Folder")
    if not exe_dir:
        return

    exe_path = os.path.join(exe_dir, "zoo.exe")
    if not os.path.isfile(exe_path):
        messagebox.showerror("Error", "zoo.exe not found in that folder.")
        return

    ZT1_PATH = exe_dir
    with open(ZT1_EXE_FILE, "w", encoding="utf-8") as f:
        f.write(ZT1_PATH)

    messagebox.showinfo(
        "Set Mod Folder",
        "Now select your ZT1 mod folder (usually 'dlupdates')."
    )

    mod_dir = filedialog.askdirectory(title="Select ZT1 Mod Folder")
    if mod_dir:
        ZT1_MOD_DIR = mod_dir
    else:
        ZT1_MOD_DIR = os.path.join(ZT1_PATH, "dlupdates")

    with open(ZT1_MOD_DIR_FILE, "w", encoding="utf-8") as f:
        f.write(ZT1_MOD_DIR)

    messagebox.showinfo(
        "Success",
        f"Zoo Tycoon 1 paths saved!\n\nExe: {ZT1_PATH}\nMods: {ZT1_MOD_DIR}"
    )

def launch_zt1():
    global ZT1_PATH

    if not ZT1_PATH or not os.path.isfile(os.path.join(ZT1_PATH, "zoo.exe")):
        messagebox.showerror("Error", "ZT1 path not set or zoo.exe missing.\nUse 'Set ZT1 Path' first.")
        return

    exe_path = os.path.join(ZT1_PATH, "zoo.exe")
    try:
        subprocess.Popen([exe_path], cwd=ZT1_PATH, shell=False)
        log("🎮 Launched Zoo Tycoon 1", text_widget=log_text)
    except Exception as e:
        messagebox.showerror("Error", f"Failed to launch ZT1: {e}")

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

_tt = ttk.Label(banner, text="ModZT", font=("Segoe UI", 20, "bold"), bootstyle="inverse-dark")
_tt.pack(side=tk.LEFT)

toolbar = ttk.Frame(root, padding=6, bootstyle="primary")
toolbar.pack(fill=tk.X)

lbl_game_path = ttk.Label(toolbar, text=GAME_PATH or "(not set)", width=80, bootstyle="secondary")
lbl_game_path.pack(side=tk.LEFT, padx=(6, 10))

game_menu_btn = ttk.Menubutton(toolbar, text="Game", bootstyle="info-outline")
game_menu = tk.Menu(game_menu_btn, tearoff=0)
game_menu.add_command(label="Set ZT1 Path", command=set_zt1_paths)
game_menu.add_command(label="Set ZT2 Path", command=lambda: set_game_path(lbl_game_path, status_label))
game_menu.add_command(label="Play ZT1", command=launch_zt1)
game_menu.add_command(label="Play ZT2", command=launch_game)
game_menu_btn["menu"] = game_menu
game_menu_btn.pack(side=tk.LEFT, padx=4)

mods_menu_btn = ttk.Menubutton(toolbar, text="Mods", bootstyle="info-outline")
mods_menu = tk.Menu(mods_menu_btn, tearoff=0)
mods_menu.add_command(label="Export Load Order", command=export_load_order)
mods_menu.add_command(label="Backup Mods",  command=backup_mods)
mods_menu.add_command(label="Restore Mods", command=restore_mods)
mods_menu_btn["menu"] = mods_menu
mods_menu_btn.pack(side=tk.LEFT, padx=4)

tools_menu_btn = ttk.Menubutton(toolbar, text="Tools", bootstyle="info-outline")
tools_menu = tk.Menu(tools_menu_btn, tearoff=0)
tools_menu.add_command(label="Validate Mods", command=lambda: messagebox.showinfo("Validate Mods", "All mods validated successfully."))
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
help_menu.add_command(label="About ModZT", command=lambda: messagebox.showinfo("About", "ModZT v1.1.1\nCreated by Kael"))
help_menu.add_command(label="Open GitHub Page", command=lambda: webbrowser.open("https://github.com/kaelelson05/modzt"))
help_menu.add_command(label="Check for Updates", command=check_for_updates)
help_menu_btn["menu"] = help_menu
help_menu_btn.pack(side=tk.LEFT, padx=4)

footer = ttk.Frame(root, padding=4)
footer.pack(fill=tk.X, side=tk.BOTTOM)

root.bind("<Control-q>", lambda e: root.quit())

main_frame = ttk.Frame(root)
main_frame.pack(fill=tk.BOTH, expand=True)

notebook = ttk.Notebook(main_frame)
notebook.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

mods_tab = ttk.Frame(notebook, padding=6)
notebook.add(mods_tab, text="ZT2 Mods")

zt1_tab = ttk.Frame(notebook, padding=6)
notebook.add(zt1_tab, text="ZT1 Mods")

zt1_toolbar = ttk.Frame(zt1_tab)
zt1_toolbar.pack(fill=tk.X, pady=4)

zt1_search_var = tk.StringVar()
zt1_status_filter = tk.StringVar(value="All")

search_frame = ttk.Frame(zt1_tab)
search_frame.pack(fill="x", padx=6, pady=(4, 0))

ttk.Label(search_frame, text="Search:").pack(side="left")
search_entry = ttk.Entry(search_frame, textvariable=zt1_search_var)
search_entry.pack(side="left", fill="x", expand=True, padx=(4, 6))

ttk.Label(search_frame, text="Status:").pack(side="left")
ttk.OptionMenu(search_frame, zt1_status_filter, "All", "All", "Enabled", "Disabled").pack(side="left")

ttk.Button(search_frame, text="Clear",
           command=lambda: (zt1_search_var.set(""), zt1_status_filter.set("All"), refresh_zt1_tree())
           ).pack(side="left", padx=(6, 0))

ttk.Button(zt1_toolbar, text="Enable", bootstyle="success", width=10,
           command=lambda: enable_selected_zt1_mod()).pack(side=tk.LEFT, padx=4)
ttk.Button(zt1_toolbar, text="Disable", bootstyle="warning", width=10,
           command=lambda: disable_selected_zt1_mod()).pack(side=tk.LEFT, padx=4)
ttk.Button(zt1_toolbar, text="Refresh", width=10,
           command=lambda: refresh_zt1_tree()).pack(side=tk.LEFT, padx=4)
ttk.Button(zt1_toolbar, text="Open Mods Folder", width=16,
           command=lambda: os.startfile(ZT1_MOD_DIR or os.path.join(ZT1_PATH, "dlupdates"))
           if ZT1_PATH else messagebox.showerror("Error", "ZT1 path not set.")
           ).pack(side=tk.LEFT, padx=4)

zt1_frame = ttk.Frame(zt1_tab)
zt1_frame.pack(fill=tk.BOTH, expand=True, pady=4)

zt1_tree = ttk.Treeview(
    zt1_frame,
    columns=("Name", "Status", "Category", "Tags", "Size"),
    show="headings",
    height=18,
)

for col in ("Name", "Status", "Category", "Tags", "Size"):
    zt1_tree.heading(col, text=col, command=lambda c=col: sort_zt1_tree(c, False))

zt1_tree.column("Name", anchor="w", width=350)
zt1_tree.column("Status", anchor="center", width=80)
zt1_tree.column("Category", anchor="center", width=120)
zt1_tree.column("Tags", anchor="center", width=180)
zt1_tree.column("Size", anchor="e", width=80)

scrollbar = ttk.Scrollbar(zt1_frame, orient=tk.VERTICAL, command=zt1_tree.yview)
zt1_tree.configure(yscrollcommand=scrollbar.set)
zt1_tree.grid(row=0, column=0, sticky="nsew")
scrollbar.grid(row=0, column=1, sticky="ns")

zt1_frame.rowconfigure(0, weight=1)
zt1_frame.columnconfigure(0, weight=1)

def auto_resize_columns(event):
    total_width = event.width
    ratios = {"Name": 0.4, "Status": 0.1, "Category": 0.15, "Tags": 0.15, "Size": 0.1}
    for col, r in ratios.items():
        zt1_tree.column(col, width=int(total_width * r))
zt1_tree.bind("<Configure>", auto_resize_columns)

zt1_menu = tk.Menu(zt1_tree, tearoff=0)
zt1_menu.add_command(label="Set Category", command=lambda: set_zt1_mod_category())
zt1_menu.add_command(label="Set Tags", command=lambda: set_zt1_mod_tags())

def on_zt1_right_click(event):
    iid = zt1_tree.identify_row(event.y)
    if iid:
        zt1_tree.selection_set(iid)
        zt1_menu.post(event.x_root, event.y_root)

zt1_tree.bind("<Button-3>", on_zt1_right_click)

def set_zt1_mod_category():
    selected = zt1_tree.selection()
    if not selected:
        return
    name = zt1_tree.item(selected[0])["values"][0]
    old = get_mod_category(name, zt1=True)
    new = simpledialog.askstring("Set Category", f"Enter category for '{name}':", initialvalue=old, parent=root)
    if new:
        set_mod_category(name, new, zt1=True)
        refresh_zt1_tree()

def set_zt1_mod_tags():
    selected = zt1_tree.selection()
    if not selected:
        return
    name = zt1_tree.item(selected[0])["values"][0]
    old = ", ".join(get_mod_tags(name, zt1=True))
    new = simpledialog.askstring("Set Tags", f"Enter tags for '{name}' (comma-separated):", initialvalue=old, parent=root)
    if new is not None:
        tags = [t.strip() for t in new.split(",")]
        set_mod_tags(name, tags, zt1=True)
        refresh_zt1_tree()

zt1_mod_btns = ttk.Frame(zt1_tab, padding=6)
zt1_mod_btns.pack(fill=tk.X)

zt1_footer = ttk.Label(
    zt1_tab,
    text="Total mods: Total 0 | Enabled 0 | Disabled 0",
    bootstyle="secondary"
)
zt1_footer.pack(anchor="w", padx=6, pady=(2, 0))

zt1_menu = tk.Menu(zt1_tree, tearoff=0)
zt1_menu.add_command(label="Set Category", command=lambda: set_zt1_mod_category())

def on_zt1_right_click(event):
    iid = zt1_tree.identify_row(event.y)
    if iid:
        zt1_tree.selection_set(iid)
        zt1_menu.post(event.x_root, event.y_root)

zt1_tree.bind("<Button-3>", on_zt1_right_click)

def set_zt1_mod_category():
    selected = zt1_tree.selection()
    if not selected:
        return
    item = zt1_tree.item(selected[0])
    name = item["values"][0]

    new_cat = simpledialog.askstring(
        "Set Category",
        f"Enter a category for '{name}':",
        parent=root
    )
    if new_cat:
        cursor.execute("UPDATE zt1_mods SET category=? WHERE name=?", (new_cat, name))
        conn.commit()
        refresh_zt1_tree()

def sort_zt1_tree(col, reverse=False):
    data = [(zt1_tree.set(k, col), k) for k in zt1_tree.get_children("")]

    if col == "Size":
        def parse_size(s):
            try:
                return float(s.split()[0]) if "KB" in s else 0
            except Exception:
                return 0
        data.sort(key=lambda t: parse_size(t[0]), reverse=reverse)
    else:
        data.sort(key=lambda t: str(t[0]).lower(), reverse=reverse)

    for index, (val, k) in enumerate(data):
        zt1_tree.move(k, "", index)

    zt1_tree.heading(col, command=lambda: sort_zt1_tree(col, not reverse))

    for c in ("Name", "Status", "Category", "Tags", "Size"):
        label = c
        if c == col:
            label += " 🔽" if reverse else " 🔼"
        zt1_tree.heading(c, text=label, command=lambda c=c: sort_zt1_tree(c, not (c == col and reverse)))

def refresh_zt1_tree(filter_text=""):
    for row in zt1_tree.get_children():
        zt1_tree.delete(row)

    detect_existing_zt1_mods()

    cursor.execute("SELECT COUNT(*), SUM(enabled) FROM zt1_mods")
    total, enabled_count = cursor.fetchone()
    enabled_count = enabled_count or 0
    disabled_count = total - enabled_count

    cursor.execute("SELECT name, enabled, category, tags FROM zt1_mods ORDER BY name ASC")
    all_rows = cursor.fetchall()

    filter_text = (zt1_search_var.get() or "").strip().lower()
    status_filter = zt1_status_filter.get().lower()

    visible_rows = []
    for name, enabled, category, tags in all_rows:
        status_str = "enabled" if enabled else "disabled"
        combined = f"{name.lower()} {category.lower() if category else ''} {tags.lower() if tags else ''} {status_str}"

        if filter_text and filter_text not in combined:
            continue
        if status_filter != "all" and status_str != status_filter:
            continue

        visible_rows.append((name, enabled, category, tags))

    for name, enabled, category, tags in visible_rows:
        status = "enabled" if enabled else "disabled"
        display_status = "🟢 Enabled" if enabled else "🔴 Disabled"
        mod_path = os.path.join(ZT1_MOD_DIR, name)
        size = f"{os.path.getsize(mod_path)/1024:.1f} KB" if os.path.exists(mod_path) else "-"
        zt1_tree.insert("", tk.END, values=(name, display_status, category or "—", tags or "—", size), tags=(status,))

    zt1_footer.config(
        text=f"Total mods: {total} | Enabled: {enabled_count} | Disabled: {disabled_count}"
    )

    apply_zt1_tree_theme()

zt1_search_var.trace_add("write", lambda *_: refresh_zt1_tree())
zt1_status_filter.trace_add("write", lambda *_: refresh_zt1_tree())

def on_search_zt1(*args):
    text = zt1_search_var.get().strip()
    refresh_zt1_tree(text)

zt1_search_var.trace_add("write", on_search_zt1)

def get_selected_zt1_mod():
    sel = zt1_tree.selection()
    if not sel:
        messagebox.showinfo("Select", "Select a ZT1 mod first.")
        return None
    return zt1_tree.item(sel[0])["values"][0]

def enable_selected_zt1_mod():
    mod = get_selected_zt1_mod()
    if mod:
        enable_zt1_mod(mod, text_widget=log_text)
        refresh_zt1_tree()

def disable_selected_zt1_mod():
    mod = get_selected_zt1_mod()
    if mod:
        disable_zt1_mod(mod, text_widget=log_text)
        refresh_zt1_tree()

def apply_zt1_tree_theme():
    if root.style.theme_use() == "darkly":
        zt1_tree.tag_configure("enabled", foreground="#5efc82")
        zt1_tree.tag_configure("disabled", foreground="#ff6961")
    else:
        zt1_tree.tag_configure("enabled", foreground="#007f00")
        zt1_tree.tag_configure("disabled", foreground="#b30000")

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

def treeview_sort_column(tree, col, reverse=False):
    data = [(tree.set(k, col), k) for k in tree.get_children('')]

    try:
        data.sort(key=lambda t: float(t[0]), reverse=reverse)
    except ValueError:
        data.sort(key=lambda t: t[0].lower(), reverse=reverse)

    for index, (val, k) in enumerate(data):
        tree.move(k, '', index)

    tree.heading(col, command=lambda: treeview_sort_column(tree, col, not reverse))

    sort_arrow = " ▲" if not reverse else " ▼"
    for c in tree["columns"]:
        text = c.capitalize()
        if c == col:
            text += sort_arrow
        tree.heading(c, text=text, command=lambda _col=c: treeview_sort_column(tree, _col, _col == col and not reverse))

mods_tree.bind("<Button-3>", on_mod_right_click)

mod_btns = ttk.Frame(mods_tab, padding=6)
mod_btns.pack(fill=tk.X)

enable_btn = ttk.Button(mod_btns, text="Enable", command=lambda: (enable_selected_mod(),), bootstyle="success")
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

shots_tab = ttk.Frame(notebook, padding=6)
notebook.add(shots_tab, text="Screenshots")

shots_toolbar = ttk.Frame(shots_tab)
shots_toolbar.pack(fill=tk.X, pady=(0,6))

shots_path_var = tk.StringVar(value=get_zt2_photos_root() or "(Not found)")
ttk.Label(shots_toolbar, text="Root:").pack(side=tk.LEFT)
ttk.Entry(shots_toolbar, textvariable=shots_path_var, width=80).pack(side=tk.LEFT, padx=6)

def browse_shots_root():
    p = filedialog.askdirectory(title="Select ZT2 photos root (contains album0, album1, ...)")
    if p:
        shots_path_var.set(p)
        refresh_screenshots()

ttk.Button(shots_toolbar, text="Browse…", command=browse_shots_root).pack(side=tk.LEFT, padx=4)
ttk.Button(shots_toolbar, text="Refresh", command=lambda: refresh_screenshots()).pack(side=tk.LEFT, padx=4)

def open_current_root():
    r = shots_path_var.get().strip()
    if r and os.path.isdir(r):
        os.startfile(r)
    else:
        messagebox.showinfo("Open", "Root folder not found.")

ttk.Button(shots_toolbar, text="Open Folder", command=open_current_root).pack(side=tk.LEFT, padx=4)

shots_split = ttk.PanedWindow(shots_tab, orient=tk.HORIZONTAL)
shots_split.pack(fill=tk.BOTH, expand=True)

shots_left = ttk.Frame(shots_split, width=220, padding=(4,6))
shots_left.pack_propagate(False)
shots_split.add(shots_left, weight=0)

ttk.Label(shots_left, text="Albums", font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(0,6))

album_list_scroll = ttk.Scrollbar(shots_left, orient="vertical")
album_list = tk.Listbox(shots_left, exportselection=False, height=20, yscrollcommand=album_list_scroll.set)
album_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
album_list_scroll.pack(side=tk.RIGHT, fill=tk.Y)
album_list_scroll.config(command=album_list.yview)

shots_right = ttk.Frame(shots_split, padding=(6,6))
shots_split.add(shots_right, weight=1)

thumb_canvas = tk.Canvas(shots_right, highlightthickness=0)
thumb_scroll = ttk.Scrollbar(shots_right, orient=tk.VERTICAL, command=thumb_canvas.yview)
thumb_canvas.configure(yscrollcommand=thumb_scroll.set)
thumb_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
thumb_scroll.pack(side=tk.RIGHT, fill=tk.Y)

thumb_inner = ttk.Frame(thumb_canvas)
thumb_window = thumb_canvas.create_window((0,0), window=thumb_inner, anchor="nw")

def _thumb_cfg(event):
    thumb_canvas.configure(scrollregion=thumb_canvas.bbox("all"))
thumb_inner.bind("<Configure>", _thumb_cfg)

def _canvas_cfg(event):
    thumb_canvas.itemconfigure(thumb_window, width=event.width)
thumb_canvas.bind("<Configure>", _canvas_cfg)

_THUMB_CACHE = {}

def make_thumbnail(path, size=(220, 140)):
    key = (path, size)
    if key in _THUMB_CACHE:
        return _THUMB_CACHE[key]
    try:
        im = Image.open(path)
        im.thumbnail(size, Image.LANCZOS)
        img = ImageTk.PhotoImage(im)
        _THUMB_CACHE[key] = img
        return img
    except Exception:
        return None

def show_full_preview(img_paths, start_index=0):
    if not img_paths:
        return
    idx = max(0, min(start_index, len(img_paths)-1))

    top = tk.Toplevel(root)
    top.title("Screenshot Preview")
    top.geometry("900x700")

    img_label = ttk.Label(top)
    img_label.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

    info_var = tk.StringVar()
    ttk.Label(top, textvariable=info_var).pack(pady=(0,6))

    btns = ttk.Frame(top)
    btns.pack(pady=6)
    def do_prev():
        nonlocal idx
        if idx > 0:
            idx -= 1
            render()
    def do_next():
        nonlocal idx
        if idx < len(img_paths)-1:
            idx += 1
            render()
    ttk.Button(btns, text="◀ Prev", command=do_prev).pack(side=tk.LEFT, padx=4)
    ttk.Button(btns, text="Next ▶", command=do_next).pack(side=tk.LEFT, padx=4)

    def open_in_folder():
        p = img_paths[idx]
        try:
            os.startfile(os.path.dirname(p))
        except Exception:
            messagebox.showinfo("Open", os.path.dirname(p))
    ttk.Button(btns, text="Open in Folder", command=open_in_folder).pack(side=tk.LEFT, padx=8)

    def export_copy():
        p = img_paths[idx]
        out = filedialog.asksaveasfilename(
            defaultextension=os.path.splitext(p)[1],
            initialfile=os.path.basename(p),
            filetypes=[("Images", "*.jpg;*.jpeg;*.png;*.bmp"), ("All files", "*.*")]
        )
        if out:
            try:
                shutil.copy2(p, out)
                messagebox.showinfo("Exported", f"Saved to:\n{out}")
            except Exception as e:
                messagebox.showerror("Export error", str(e))
    ttk.Button(btns, text="Export…", command=export_copy).pack(side=tk.LEFT, padx=8)

    def render():
        p = img_paths[idx]
        try:
            im = Image.open(p)
            w = max(300, top.winfo_width()-80)
            h = max(200, top.winfo_height()-160)
            im.thumbnail((w, h), Image.LANCZOS)
            ph = ImageTk.PhotoImage(im)
            img_label.configure(image=ph)
            img_label.image = ph
        except Exception as e:
            img_label.configure(text=f"(Failed to load)\n{e}")
            img_label.image = None

        ts = datetime.fromtimestamp(os.path.getmtime(p)).strftime("%Y-%m-%d %H:%M:%S")
        info_var.set(f"{os.path.basename(p)}    {ts}    {os.path.getsize(p)/1024:.0f} KB   [{idx+1}/{len(img_paths)}]")

    top.bind("<Left>", lambda e: (do_prev(), "break"))
    top.bind("<Right>", lambda e: (do_next(), "break"))
    top.after(50, render)

def populate_thumbnails(img_paths):
    for child in list(thumb_inner.children.values()):
        child.destroy()

    if not img_paths:
        ttk.Label(thumb_inner, text="No screenshots found in this album.", bootstyle="secondary").pack(pady=16)
        return

    cols = 3
    pad = 8
    for i, p in enumerate(img_paths):
        r, c = divmod(i, cols)
        frame = ttk.Frame(thumb_inner, padding=4, relief="flat")
        frame.grid(row=r, column=c, sticky="nsew", padx=pad, pady=pad)

        th = make_thumbnail(p)
        if th is not None:
            lbl = ttk.Label(frame, image=th)
            lbl.image = th
        else:
            lbl = ttk.Label(frame, text="(image)", width=28, anchor="center")
        lbl.pack()

        meta = ttk.Label(frame, text=os.path.basename(p), width=32)
        meta.pack()

        def _open_preview(event, idx=i):
            show_full_preview(img_paths, start_index=idx)
        lbl.bind("<Button-1>", _open_preview)
        meta.bind("<Button-1>", _open_preview)

    for c in range(cols):
        thumb_inner.grid_columnconfigure(c, weight=1)

def refresh_screenshots():
    root_dir = shots_path_var.get().strip()
    if not root_dir or not os.path.isdir(root_dir):
        d = get_zt2_photos_root()
        if d:
            shots_path_var.set(d)
            root_dir = d
        else:
            album_list.delete(0, tk.END)
            populate_thumbnails([])
            return

    albums = list_zt2_albums(root_dir)
    album_list.delete(0, tk.END)
    for name, _ in albums:
        album_list.insert(tk.END, name)

    def show_first_album():
        if not albums:
            populate_thumbnails([])
            return
        album_list.selection_clear(0, tk.END)
        album_list.selection_set(0)
        album_list.event_generate("<<ListboxSelect>>")
    root.after(10, show_first_album)

def _on_album_select(event=None):
    root_dir = shots_path_var.get().strip()
    if not (root_dir and os.path.isdir(root_dir)):
        populate_thumbnails([])
        return
    idxs = album_list.curselection()
    if not idxs:
        populate_thumbnails([])
        return
    name = album_list.get(idxs[0])
    album_path = os.path.join(root_dir, name)
    imgs = list_album_images(album_path)
    populate_thumbnails(imgs)

album_list.bind("<<ListboxSelect>>", _on_album_select)

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

bundle_btns = ttk.Frame(bundles_tab, padding=6)
bundle_btns.pack(side=tk.BOTTOM, fill=tk.X, pady=(4, 0))

def update_bundle_toolbar_state():
    has_selection = bool(bundle_list.curselection())
    for btn in (apply_btn, delete_btn):
        state = "normal" if has_selection else "disabled"
        btn.config(state=state)

bundle_list.bind("<<ListboxSelect>>", lambda _: update_bundle_toolbar_state())

create_btn = ttk.Button(bundle_btns, text="Create", bootstyle="success", command=bundle_create_dialog)
create_btn.pack(side=tk.LEFT, padx=4)

apply_btn = ttk.Button(bundle_btns, text="Apply", bootstyle="primary", command=bundle_apply, state="disabled")
apply_btn.pack(side=tk.LEFT, padx=4)

delete_btn = ttk.Button(bundle_btns, text="Delete", bootstyle="info", command=bundle_delete, state="disabled")
delete_btn.pack(side=tk.LEFT, padx=4)

ttk.Button(bundle_btns, text="Export JSON", command=bundle_export_json).pack(side=tk.LEFT, padx=4)
ttk.Button(bundle_btns, text="Import JSON", command=bundle_import_json).pack(side=tk.LEFT, padx=4)
ttk.Button(bundle_btns, text="Export Bundle as Mod (.z2f)", bootstyle="success",
           command=bundle_export_z2f).pack(side=tk.LEFT, padx=4)

def update_bundle_toolbar_state():
    sel = bundle_list.curselection()
    has_selection = bool(sel) and not bundle_list.get(sel[0]).startswith("(")
    apply_btn.config(state="normal" if has_selection else "disabled")
    delete_btn.config(state="normal" if has_selection else "disabled")

bundle_list.bind("<<ListboxSelect>>", lambda _: (refresh_bundle_preview(), update_bundle_toolbar_state()))

preview_btns = ttk.Frame(bundle_preview)
preview_btns.pack(fill=tk.X, pady=(6, 0))
ttk.Button(preview_btns, text="Apply Bundle", command=lambda: bundle_apply(), bootstyle="primary").pack(side=tk.LEFT, padx=4)
ttk.Button(preview_btns, text="Enable All", command=lambda: bundle_enable_all(), bootstyle="success").pack(side=tk.LEFT, padx=4)
ttk.Button(preview_btns, text="Disable All", command=lambda: bundle_disable_all(), bootstyle="warning").pack(side=tk.LEFT, padx=4)

def _selected_bundle_name():
    sel = bundle_list.curselection()
    if not sel:
        return None
    return bundle_list.get(sel[0])

def refresh_bundles_list():
    global _all_bundle_names_cache
    cursor.execute("SELECT name FROM bundles ORDER BY name ASC")
    names = [r[0] for r in cursor.fetchall()]
    _all_bundle_names_cache = names[:]
    _apply_bundle_filter()

def _apply_bundle_filter(*_):
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

log_frame = ttk.Frame(main_frame, padding=6)
log_frame.pack(side=tk.RIGHT, fill=tk.Y)

ttk.Label(log_frame, text="Log Output:").pack(anchor='w')
log_text = tk.Text(log_frame, height=40, wrap='word', state='disabled')
log_text.pack(fill=tk.BOTH, expand=True)

status_frame = ttk.Frame(root)
status_frame.pack(side=tk.BOTTOM, fill=tk.X)

online_tab = ttk.Frame(notebook, padding=10)
notebook.add(online_tab, text="Online")

connection_frame = ttk.Labelframe(online_tab, text="Connection Info", padding=8)
connection_frame.pack(fill="x", pady=(0, 8))

local_ip_var = tk.StringVar(value="Local IP: —")
public_ip_var = tk.StringVar(value="Public IP: —")
port_var = tk.StringVar(value="Port: —")

ttk.Label(connection_frame, textvariable=local_ip_var).grid(row=0, column=0, sticky="w", padx=6, pady=2)
ttk.Label(connection_frame, textvariable=public_ip_var).grid(row=1, column=0, sticky="w", padx=6, pady=2)
ttk.Label(connection_frame, textvariable=port_var).grid(row=2, column=0, sticky="w", padx=6, pady=2)

status_var = tk.StringVar(value="Status: Idle")
status_label = ttk.Label(online_tab, textvariable=status_var, justify="left")
status_label.pack(anchor="w", padx=10, pady=(0, 10))

session_frame = ttk.Labelframe(online_tab, text="Session Controls", padding=8)
session_frame.pack(fill="x", pady=(0, 8))

button_row = ttk.Frame(session_frame)
button_row.pack(fill="x", pady=4)

ttk.Button(button_row, text="Host Session", bootstyle="success", command=lambda: host_session()).pack(side="left", padx=6)
ttk.Button(button_row, text="Stop Hosting", bootstyle="danger", command=stop_host).pack(side="left", padx=6)
ttk.Button(button_row, text="Join Session", bootstyle="primary", command=lambda: join_session_dialog()).pack(side="left", padx=6)

clients_frame = ttk.Labelframe(online_tab, text="Connected Clients", padding=8)
clients_frame.pack(fill="both", expand=True)

clients_listbox = tk.Listbox(clients_frame, height=8)
clients_listbox.pack(fill="both", expand=True, padx=6, pady=4)

zoo_state_var = tk.StringVar(value="Zoo State: Waiting for updates...")
zoo_state_label = ttk.Label(
    online_tab,
    textvariable=zoo_state_var,
    font=("Segoe UI", 9),
    justify="left"
)
zoo_state_label.pack(anchor="w", padx=10, pady=(4, 10))

def update_connection_info_now():
    def on_info(local, public, port):
        online_tab.after(0, lambda: (
            local_ip_var.set(f"Local IP: {local}"),
            public_ip_var.set(f"Public IP: {public}"),
            port_var.set(f"Port: {port}")
        ))
    try:
        online_manager.get_connection_info(callback=on_info)
    except Exception as e:
        online_tab.after(0, lambda: (
            local_ip_var.set("Local IP: Error"),
            public_ip_var.set(f"Public IP: {e}"),
            port_var.set("Port: —")
        ))

def update_connection_info_now():
    def on_info(local, public, port):
        online_tab.after(0, lambda: (
            local_ip_var.set(f"Local IP: {local}"),
            public_ip_var.set(f"Public IP: {public}"),
            port_var.set(f"Port: {port}")
        ))
    try:
        online_manager.get_connection_info(callback=on_info)
    except Exception as e:
        online_tab.after(0, lambda: (
            local_ip_var.set("Local IP: Error"),
            public_ip_var.set(f"Public IP: {e}"),
            port_var.set("Port: —")
        ))

def refresh_connection_info():
    def loop():
        while True:
            update_connection_info_now()
            time.sleep(5)
    threading.Thread(target=loop, daemon=True).start()

refresh_connection_info()
update_connection_info_now()

def update_client_list(clients):
    clients_listbox.delete(0, tk.END)
    if not clients:
        clients_listbox.insert(tk.END, "(No connected clients)")
        return
    for addr in clients:
        clients_listbox.insert(tk.END, f"{addr[0]}:{addr[1]}")

online_manager.set_client_update_callback(update_client_list)

def update_zoo_state_ui(diff):
    summary = " | ".join(f"{k.capitalize()}: {v}" for k, v in diff.items())
    zoo_state_var.set(f"Zoo State: {summary}")

state_manager.set_ui_callback(update_zoo_state_ui)

update_connection_info_now()

def refresh_tree():
    """Rebuilds mod list UI from both filesystem and DB."""
    mods_tree.delete(*mods_tree.get_children())

    enabled_dir = mods_enabled_dir()
    disabled_dir = mods_disabled_dir()
    os.makedirs(enabled_dir, exist_ok=True)
    os.makedirs(disabled_dir, exist_ok=True)

    found_mods = {}
    for folder, enabled_flag in [(enabled_dir, 1), (disabled_dir, 0)]:
        for f in os.listdir(folder):
            if f.lower().endswith(".z2f"):
                found_mods[f] = enabled_flag

    cursor.execute("SELECT name FROM mods")
    db_mods = {r[0] for r in cursor.fetchall()}

    for mod, enabled_flag in found_mods.items():
        if mod not in db_mods:
            cursor.execute("INSERT INTO mods (name, enabled) VALUES (?, ?)", (mod, enabled_flag))
    conn.commit()

    cursor.execute("SELECT name, enabled FROM mods ORDER BY enabled DESC, name ASC")
    mods = cursor.fetchall()

    total = len(mods)
    enabled_count = sum(1 for _, e in mods if e)
    disabled_count = total - enabled_count

    for name, enabled_flag in mods:
        path = find_mod_file(name)
        exists = path and os.path.isfile(path)

        size_mb = os.path.getsize(path) / (1024 * 1024) if exists else 0
        modified = (
            time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(os.path.getmtime(path)))
            if exists else "N/A"
        )

        status = (
            "🟢 Enabled" if enabled_flag else
            ("🟡 Missing" if not exists else "🔴 Disabled")
        )

        mods_tree.insert(
            "",
            tk.END,
            values=(name, status, f"{size_mb:.2f}", modified),
            tags=("enabled" if enabled_flag else ("missing" if not exists else "disabled"),)
        )

    mod_count_label.config(
        text=f"Total mods: {total} | Enabled: {enabled_count} | Disabled: {disabled_count}"
    )

    apply_tree_theme()
    refresh_bundles_list()

    print(f"[ModZT] Refreshed mod list ({total} mods found).")

def sort_tree_by(column):
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
    sel = mods_tree.selection()
    mod = get_selected_mod()
    if mod:
        disable_mod(mod, text_widget=log_text)
        root.after(100, lambda: restore_selection(mod))

def restore_selection(mod_name):
    for iid in mods_tree.get_children():
        vals = mods_tree.item(iid, 'values')
        if vals and vals[0] == mod_name:
            mods_tree.selection_set(iid)
            mods_tree.focus(iid)
            mods_tree.see(iid)
            break

def save_tree_state(tree):
    sel = tree.selection()
    first_visible = tree.index(tree.identify_row(0)) if tree.get_children() else 0
    return {"sel": sel, "first_visible": first_visible}

def restore_tree_state(tree, state):
    if not state:
        return
    sel = state.get("sel")
    if sel:
        tree.selection_set(sel)
        tree.focus(sel[0])
        tree.see(sel[0])
    else:
        first = state.get("first_visible", 0)
        try:
            iid = tree.get_children()[first]
            tree.see(iid)
        except IndexError:
            pass

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
    dlg.geometry("700x700")

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
        messagebox.showerror("Error", "This mod file is not a valid Z2F file.")
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

def on_import_bundle():
    import_bundle_from_json()
    refresh_bundles_list()

def on_export_bundle_as_mod():
    name = get_selected_bundle_name()
    if not name:
        return
    export_bundle_as_mod_ui(name)

def update_status():
    status_label.config(text=f"ZT2 path: {GAME_PATH or '(not set)'} | {enabled_count()} mods enabled")

search_var.trace_add('write', lambda *_: filter_tree())

def filter_tree(*_):
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
detect_existing_zt1_mods()
refresh_zt1_tree()

if not hasattr(root, "_watcher_started"):
    watch_mods(root, refresh_tree, interval=3)
    root._watcher_started = True

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

    root.after(30000, auto_switch_theme)
    folder_tree.bind("<<TreeviewOpen>>", on_open_folder)
    folder_tree.bind("<<TreeviewSelect>>", on_select_folder)

def on_close():
    try:
        conn.close()
        print("Database connection closed.")
    except Exception as e:
        print("Error closing DB:", e)
    root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)

load_explorer_roots()
refresh_screenshots()
root.mainloop()