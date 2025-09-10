# ---------------- 1. Imports ----------------
import os, shutil, sqlite3, subprocess
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import ttkbootstrap as tb
import threading, time

# ---------------- 2. Constants & Globals ----------------
CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".zt2_manager")
os.makedirs(CONFIG_DIR, exist_ok=True)

GAME_PATH_FILE = os.path.join(CONFIG_DIR, "game_path.txt")
DB_FILE = os.path.join(CONFIG_DIR, "mods.db")

GAME_PATH = None
if os.path.isfile(GAME_PATH_FILE):
    with open(GAME_PATH_FILE, "r", encoding="utf-8") as f:
        GAME_PATH = f.read().strip()

# ---------------- 3. Database Setup ----------------
conn = sqlite3.connect(DB_FILE)
cursor = conn.cursor()
cursor.execute("""
CREATE TABLE IF NOT EXISTS mods (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    name TEXT,
    enabled INTEGER DEFAULT 0
)
""")
conn.commit()

# ---------------- 4. Helper Functions ----------------
def log(msg, text_widget=None):
    print(msg)
    if text_widget:
        text_widget.configure(state="normal")
        text_widget.insert(tk.END, msg + "\n")
        text_widget.configure(state="disabled")
        text_widget.see(tk.END)

# ---------------- 5. Game Path Functions ----------------
def set_game_path(lbl_widget=None):
    global GAME_PATH
    path = filedialog.askdirectory(title="Select Zoo Tycoon 2 Game Folder")
    if not path:
        return
    GAME_PATH = path
    with open(GAME_PATH_FILE, "w", encoding="utf-8") as f:
        f.write(GAME_PATH)
    if lbl_widget:
        lbl_widget.config(text=GAME_PATH)
    log(f"Game path set: {GAME_PATH}")

def launch_game():
    if not GAME_PATH:
        messagebox.showerror("Error", "Set game path first!")
        return
    exe_path = os.path.join(GAME_PATH, "zt.exe")
    if not os.path.isfile(exe_path):
        messagebox.showerror("Error", "zt.exe not found!")
        return
    subprocess.Popen([exe_path], cwd=GAME_PATH)

def backup_mod(mod_file):
    """Backup mod before enabling/disabling (optional)"""
    backup_dir = os.path.join(CONFIG_DIR, "backup")
    os.makedirs(backup_dir, exist_ok=True)
    src = os.path.join(GAME_PATH, mod_file)
    if os.path.isfile(src):
        shutil.copy2(src, os.path.join(backup_dir, mod_file))

# ---------------- 6. Mod Management ----------------
def detect_existing_mods():
    if not GAME_PATH:
        return

    disabled_dir = os.path.join(GAME_PATH, "Mods", "Disabled")
    os.makedirs(disabled_dir, exist_ok=True)

    # Scan both game root and Disabled folder
    mod_paths = []
    for folder in [GAME_PATH, disabled_dir]:
        for f in os.listdir(folder):
            if f.lower().endswith(".z2f"):
                enabled = 1 if folder == GAME_PATH else 0
                mod_paths.append((f, enabled))

    # Insert into DB if not already present
    for mod_name, enabled in mod_paths:
        cursor.execute("SELECT COUNT(*) FROM mods WHERE name=?", (mod_name,))
        if cursor.fetchone()[0] == 0:
            cursor.execute("INSERT INTO mods (name, enabled) VALUES (?, ?)", (mod_name, enabled))
    conn.commit()

def install_mod(text_widget=None):
    if not GAME_PATH:
        messagebox.showerror("Error", "Set game path first!")
        return
    file_path = filedialog.askopenfilename(title="Select a .z2f Mod File", filetypes=[("ZT2 Mod", "*.z2f"), ("All Files", "*.*")])
    if not file_path:
        return

    mod_name = os.path.basename(file_path)
    disabled_dir = os.path.join(GAME_PATH, "Mods", "Disabled")
    os.makedirs(disabled_dir, exist_ok=True)
    dest = os.path.join(disabled_dir, mod_name)
    shutil.copy2(file_path, dest)
    log(f"Installed mod: {mod_name} → {dest}", text_widget)

    cursor.execute("UPDATE mods SET enabled=1 WHERE name=?", (mod_name,))
    conn.commit()

def enable_mod(mod_name, text_widget=None):
    if not mod_name:
        return
    src = os.path.join(GAME_PATH, "Mods", "Disabled", mod_name)
    dst = os.path.join(GAME_PATH, mod_name)
    if os.path.isfile(src):
        shutil.move(src, dst)
        log(f"Enabled mod: {mod_name} → {dst}", text_widget)

    cursor.execute("UPDATE mods SET enabled=1 WHERE name=?", (mod_name,))
    conn.commit()

def disable_mod(mod_name, text_widget=None):
    if not mod_name:
        return
    dst_dir = os.path.join(GAME_PATH, "Mods", "Disabled")
    os.makedirs(dst_dir, exist_ok=True)
    src = os.path.join(GAME_PATH, mod_name)
    dst = os.path.join(dst_dir, mod_name)
    if os.path.isfile(src):
        shutil.move(src, dst)
        log(f"Disabled mod: {mod_name} → {dst}", text_widget)
    cursor.execute("UPDATE mods SET enabled=0 WHERE name=?", (mod_name,))
    conn.commit()

def uninstall_mod(mod_name, text_widget=None):
    if not mod_name or not GAME_PATH:
        return
    paths = [
        os.path.join(GAME_PATH, mod_name),
        os.path.join(GAME_PATH, "Mods", "Disabled", mod_name)
    ]
    removed = False
    for p in paths:
        if os.path.isfile(p):
            os.remove(p)
            log(f"Removed file: {p}", text_widget)
            removed = True
    cursor.execute("DELETE FROM mods WHERE name=?", (mod_name,))
    conn.commit()

    if removed:
        log(f"Uninstalled mod: {mod_name}", text_widget)
    else:
        log(f"Mod {mod_name} not found in filesystem, record removed from DB.", text_widget)

def export_load_order():
    cursor.execute("SELECT name, enabled FROM mods")
    rows = cursor.fetchall()

    path = os.path.join(CONFIG_DIR, "load_order.txt")
    with open(path, "w", encoding="utf-8") as f:
        for name, enabled in rows:
            f.write(f"{name}: {'Enabled' if enabled else 'Disabled'}\n")

    messagebox.showinfo("Exported", f"Load order exported to:\n{path}")

# ---------------- 6b. Auto Detection ----------------
def watch_mods(root, refresh_func, interval=5):
    """Background thread that checks for new/removed mods and notifies main thread."""
    def worker():
        last_snapshot = set()
        while True:
            if not GAME_PATH:
                time.sleep(interval)
                continue

            mods_dir = GAME_PATH
            disabled_dir = os.path.join(GAME_PATH, "Mods", "Disabled")

            found = set()
            for folder in [mods_dir, disabled_dir]:
                if os.path.isdir(folder):
                    for f in os.listdir(folder):
                        if f.lower().endswith(".z2f"):
                            found.add((f, 1 if folder == mods_dir else 0))

            if found != last_snapshot:
                def update_db_and_refresh():
                    for mod_name, enabled in found:
                        cursor.execute("SELECT COUNT(*) FROM mods WHERE name=?", (mod_name,))
                        if cursor.fetchone()[0] == 0:
                            cursor.execute("INSERT INTO mods (name, enabled) VALUES (?, ?)", (mod_name, enabled))
                    conn.commit()
                    refresh_func()

                # schedule safely in main thread
                root.after(0, update_db_and_refresh)
                last_snapshot = found

            time.sleep(interval)

    threading.Thread(target=worker, daemon=True).start()

# ---------------- 7. UI Builder ----------------
def make_ui():
    current_theme = {"name": "darkly"}
    root = tb.Window(themename=current_theme["name"])
    root.title("ModZT2")
    root.geometry("1000x650")
    style = ttk.Style()

    style.configure("Light.Treeview", background="white", foreground="black", fieldbackground="white")
    style.configure("Dark.Treeview", background="#222", foreground="white", fieldbackground="#222")

    # --- Top bar ---
    topbar = ttk.Frame(root, padding=8, bootstyle="primary")
    topbar.pack(fill=tk.X)

    ttk.Label(topbar, text="Game Path:", bootstyle="primary").pack(side=tk.LEFT)
    lbl_game_path = ttk.Label(topbar, text=GAME_PATH or "(not set)", width=80, bootstyle="secondary")
    lbl_game_path.pack(side=tk.LEFT, padx=(6, 10))

    ttk.Button(
        topbar, text="Set Game Path",
        command=lambda: (set_game_path(lbl_game_path), detect_existing_mods(), refresh_tree())
    ).pack(side=tk.LEFT, padx=4)
    ttk.Button(topbar, text="Play ZT2", command=launch_game).pack(side=tk.LEFT, padx=4)
    ttk.Button(topbar, text="Export Load Order", command=export_load_order).pack(side=tk.LEFT, padx=4)

    # --- Main area ---
    main = ttk.Frame(root, padding=6)
    main.pack(fill=tk.BOTH, expand=True)

    # Mod list
    left = ttk.Frame(main, padding=6)
    left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

    search_frame = ttk.Frame(left)
    search_frame.pack(fill=tk.X, pady=(0, 6))

    ttk.Label(search_frame, text="Search:").pack(side=tk.LEFT)
    search_var = tk.StringVar()

    def filter_tree(*args):
        query = search_var.get().lower()
        for row in tree.get_children():
            tree.delete(row)
        cursor.execute("SELECT name, enabled FROM mods ORDER BY enabled DESC, name ASC")
        for name, enabled in cursor.fetchall():
            if query in name.lower():
                iid = tree.insert("", tk.END, values=(name, "Enabled" if enabled else "Disabled"))
                tree.item(iid, tags=("enabled" if enabled else "disabled",))

        apply_log_theme()

    search_entry = ttk.Entry(search_frame, textvariable=search_var)
    search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)
    search_var.trace_add("write", filter_tree)

    columns = ("Name", "Value")
    tree = ttk.Treeview(left, columns=columns, show="headings", selectmode="extended")
    for col in columns:
        tree.heading(col, text=col)
        tree.column(col, width=300 if col=="Name" else 100, anchor=tk.W)
    tree.pack(fill=tk.BOTH, expand=True, side=tk.LEFT)

    def show_context_menu(event):
        iid = tree.identify_row(event.y)
        if iid:
            tree.selection_set(iid)
            context_menu.post(event.x_root, event.y_root)

    tree.bind("<Button-3>", show_context_menu)

    ysb = ttk.Scrollbar(left, orient=tk.VERTICAL, command=tree.yview)
    ysb.pack(side=tk.RIGHT, fill=tk.Y)
    tree.configure(yscroll=ysb.set)

    # --- Context menu (right click) ---
    context_menu = tk.Menu(root, tearoff=0)
    context_menu.add_command(label="Enable", command=lambda: enable_selected_mod())
    context_menu.add_command(label="Disable", command=lambda: disable_selected_mod())
    context_menu.add_command(label="Uninstall", command=lambda: uninstall_selected_mod())
    context_menu.add_separator()
    context_menu.add_command(label="Open Mod Folder", command=lambda: open_mod_folder())


    # --- Refresh function ---
    def refresh_tree():
        for row in tree.get_children():
            tree.delete(row)
        cursor.execute("SELECT name, enabled FROM mods ORDER BY enabled DESC, name ASC")
        for name, enabled in cursor.fetchall():
            iid = tree.insert("", tk.END, values=(name, "Enabled" if enabled else "Disabled"))
            tree.item(iid, tags=("enabled" if enabled else "disabled",))

    # --- Control buttons ---
    ctl = ttk.Frame(left, padding=6)
    ctl.pack(fill=tk.X, pady=4)

    def get_selected_mod():
        sel = tree.selection()
        if not sel:
            messagebox.showinfo("Select", "Select a mod first.", parent=root)
            return None
        return tree.item(sel[0])['values'][0]

    def enable_selected_mod():
        mod = get_selected_mod()
        if mod:
            enable_mod(mod, text_widget=log_text)
            refresh_tree()

    def disable_selected_mod():
        mod = get_selected_mod()
        if mod:
            disable_mod(mod, text_widget=log_text)
            refresh_tree()

    def uninstall_selected_mod():
        mod = get_selected_mod()
        if mod:
            uninstall_mod(mod, text_widget=log_text)
            refresh_tree()

    def open_mod_folder():
        mod = get_selected_mod()
        if not mod:
            return
        mod_paths = [
            os.path.join(GAME_PATH, mod),
            os.path.join(GAME_PATH, "Mods", "Disabled", mod)
        ]
        for p in mod_paths:
            if os.path.isfile(p):
                os.startfile(os.path.dirname(p))  # open containing folder
                return
        messagebox.showinfo("Not Found", f"Could not find {mod} on disk.")


    ttk.Button(ctl, text="Install Mod",
               command=lambda: (install_mod(text_widget=log_text), detect_existing_mods(), refresh_tree()), bootstyle="success-outline"
    ).pack(side=tk.LEFT, padx=4)
    ttk.Button(ctl, text="Enable", command=enable_selected_mod, bootstyle="info-outline").pack(side=tk.LEFT, padx=4)
    ttk.Button(ctl, text="Disable", command=disable_selected_mod, bootstyle="danger-outline").pack(side=tk.LEFT, padx=4)
    ttk.Button(ctl, text="Uninstall", command=uninstall_selected_mod, bootstyle="warning-outline").pack(side=tk.LEFT, padx=4)
    ttk.Button(ctl, text="Refresh List", command=refresh_tree, ).pack(side=tk.LEFT, padx=4)

    # --- Log panel ---
    right = ttk.Frame(main, padding=6)
    right.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
    ttk.Label(right, text="Log Output:").pack(anchor=tk.W)
    log_text = tk.Text(right, height=20, wrap="word", state="disabled",
                       background="#111", foreground="#0f0")
    log_text.pack(fill=tk.BOTH, expand=True)

    # --- Theme toggle ---
    def apply_log_theme():
        # Log panel colors
        if current_theme["name"] == "darkly":
            log_text.configure(bg="#1e1e1e", fg="white", insertbackground="white")
            style = ttk.Style()

            # Treeview dark style
            style.configure(
                "Dark.Treeview",
                background="#1e1e1e",
                fieldbackground="#1e1e1e",
                foreground="white",
                rowheight=22,
            )
            style.configure(
                "Dark.Treeview.Heading",
                background="#2d2d2d",
                foreground="white"
            )
            style.map(
                "Dark.Treeview",
                background=[("selected", "#3d3d3d")],
                foreground=[("selected", "white")]
            )

            tree.configure(style="Dark.Treeview")

        else:
            log_text.configure(bg="white", fg="black", insertbackground="black")
            style = ttk.Style()
            style.theme_use("clam")

            # Treeview light style
            style.configure(
                "Light.Treeview",
                background="white",
                fieldbackground="white",
                foreground="black",
                rowheight=22,
            )
            style.configure(
                "Light.Treeview.Heading",
                background="#f0f0f0d5",
                foreground="black"
            )
            style.map(
                "Light.Treeview",
                background=[("selected", "#cce5ff")],
                foreground=[("selected", "black")]
            )

            tree.configure(style="Light.Treeview")

    def toggle_theme():
        if current_theme["name"] == "darkly":
            root.style.theme_use("cosmo")
            current_theme["name"] = "cosmo"
            log("Switched to light mode", log_text)
        else:
            root.style.theme_use("darkly")
            current_theme["name"] = "darkly"
            log("Switched to dark mode", log_text)
        apply_log_theme()

    ttk.Button(topbar, text="Toggle Theme", command=toggle_theme).pack(side=tk.LEFT, padx=4)

    # Initialize mods + tree
    detect_existing_mods()
    refresh_tree()
    apply_log_theme()
    watch_mods(root, refresh_tree)

    return root, refresh_tree

# ---------------- 8. Main ----------------
if __name__ == "__main__":
    ui_root, ui_refresh = make_ui()
    ui_root.mainloop()
