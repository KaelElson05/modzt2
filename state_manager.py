import json
from typing import Callable, Dict, Any, Optional
import os, time, threading
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

_UI_CALLBACK: Optional[Callable[[Dict[str, Any]], None]] = None
_ZOO_STATE_CACHE: Dict[str, Any] = {}
_SESSION_PASSWORD: Optional[str] = None

_RELOAD_CALLBACK = None
_RELOAD_OBSERVER = None
_SAVE_DIR = None

def set_ui_callback(callback: Callable[[Dict[str, Any]], None]):
    global _UI_CALLBACK
    _UI_CALLBACK = callback
    print("[State] UI callback registered.")


def _update_ui():
    if _UI_CALLBACK:
        try:
            _UI_CALLBACK(dict(_ZOO_STATE_CACHE))
        except Exception as e:
            print(f"[State] UI callback failed: {e}")

def apply_state_diff(diff: Dict[str, Any]):
    global _ZOO_STATE_CACHE

    try:
        if not isinstance(diff, dict):
            print("[ZooState] Invalid diff type; expected dict.")
            return

        _ZOO_STATE_CACHE.update(diff)
        print(f"[ZooState] Applied diff: {json.dumps(diff, indent=2)}")

        _update_ui()

    except Exception as e:
        print(f"[ZooState] Error applying state diff: {e}")


def get_cached_state() -> Dict[str, Any]:
    return dict(_ZOO_STATE_CACHE)

def get_session_password() -> str:
    global _SESSION_PASSWORD

    if not _SESSION_PASSWORD:
        # TODO: integrate with password
        _SESSION_PASSWORD = "changeme"
        print("[State] Warning: using default session password (test only).")

    return _SESSION_PASSWORD


def set_session_password(pw: str):
    global _SESSION_PASSWORD
    _SESSION_PASSWORD = pw
    print("[State] Session password set.")

def notify_incoming_save(path: str, sha256_hex: str):
    try:
        filename = os.path.basename(path)
        print(f"[State] Incoming save ready: {filename} (SHA-256 {sha256_hex[:12]}...)")

        if _UI_CALLBACK:
            _UI_CALLBACK({
                "incoming_save": {
                    "path": path,
                    "hash": sha256_hex,
                    "filename": filename,
                }
            })
    except Exception as e:
        print(f"[State] notify_incoming_save failed: {e}")

def set_reload_callback(cb):
    global _RELOAD_CALLBACK
    _RELOAD_CALLBACK = cb

class _ReloadHandler(FileSystemEventHandler):
    def on_modified(self, event):
        if event.is_directory or not event.src_path.endswith(".z2s"):
            return
        if _RELOAD_CALLBACK:
            _RELOAD_CALLBACK(event.src_path)

def start_auto_reload_watcher(save_dir):
    global _RELOAD_OBSERVER, _SAVE_DIR
    _SAVE_DIR = save_dir
    observer = Observer()
    handler = _ReloadHandler()
    observer.schedule(handler, save_dir, recursive=False)
    observer.start()
    _RELOAD_OBSERVER = observer
    print(f"[ZooState] Watching {save_dir} for incoming saves.")

def stop_auto_reload_watcher():
    global _RELOAD_OBSERVER
    if _RELOAD_OBSERVER:
        _RELOAD_OBSERVER.stop()
        _RELOAD_OBSERVER.join()
        _RELOAD_OBSERVER = None
