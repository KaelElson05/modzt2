import os
import socket
import threading
import struct
import time
import requests
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

# ============================================================
#  Globals
# ============================================================

_RUNNING = False
_SERVER = None  # type: socket.socket | None
_OBSERVER = None  # type: Observer | None

_CLIENTS = set()  # type: set[tuple[socket.socket, tuple[str, int]]]
_CLIENTS_LOCK = threading.Lock()

CLIENT_UPDATE_CALLBACK = None  # type: callable | None
_PORT = 5000
_SAVE_DIR = None  # type: str | None


# ============================================================
#  Utility Functions
# ============================================================

def _detect_save_dir():
    """Detects the Zoo Tycoon 2 save directory automatically."""
    appdata = os.getenv("APPDATA")
    if not appdata:
        return None

    base = os.path.join(appdata, "Microsoft Games", "Zoo Tycoon 2")
    candidates = [
        os.path.join(base, "Default Profile", "Saved")
    ]

    for p in candidates:
        if os.path.isdir(p):
            return p
    return None


def _ensure_save_dir():
    """Ensures a valid ZT2 save directory path."""
    global _SAVE_DIR
    if _SAVE_DIR and os.path.isdir(_SAVE_DIR):
        return _SAVE_DIR
    _SAVE_DIR = _detect_save_dir()
    return _SAVE_DIR


def get_connection_info(callback=None):
    """
    Returns (local_ip, public_ip, PORT) synchronously,
    or calls callback(local, public, PORT) asynchronously.
    """
    def _work():
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            s.close()
        except Exception:
            local_ip = "Unavailable"

        try:
            public_ip = requests.get("https://api.ipify.org", timeout=3).text
        except Exception:
            public_ip = "Unavailable"

        if callback:
            callback(local_ip, public_ip, _PORT)
        else:
            return local_ip, public_ip, _PORT

    if callback:
        threading.Thread(target=_work, daemon=True).start()
        return None
    else:
        try:
            return _work()
        except Exception:
            return "Unavailable", "Unavailable", _PORT


# ============================================================
#  Hosting
# ============================================================

def start_host():
    """Start a TCP host server to accept clients."""
    global _SERVER, _RUNNING
    if _RUNNING:
        print("[Online] Server already running.")
        return True

    try:
        _RUNNING = True
        _SERVER = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        _SERVER.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        _SERVER.bind(("0.0.0.0", _PORT))
        _SERVER.listen(5)
        print(f"[Online] Hosting started on port {_PORT}")
        threading.Thread(target=_accept_loop, daemon=True).start()
        return True
    except Exception as e:
        print(f"[Online] Failed to start host: {e}")
        _RUNNING = False
        return False


def _accept_loop():
    """Accept incoming client connections."""
    global _RUNNING
    while _RUNNING:
        try:
            conn, addr = _SERVER.accept()
            with _CLIENTS_LOCK:
                _CLIENTS.add((conn, addr))
            print(f"[Online] Client connected: {addr}")
            _notify_ui_clients()
            threading.Thread(target=_client_handler, args=(conn, addr), daemon=True).start()
        except Exception as e:
            if _RUNNING:
                print(f"[Online] Accept error: {e}")
            break
    print("[Online] Accept loop stopped.")


def _client_handler(conn, addr):
    """Handle communication from a connected client."""
    try:
        while _RUNNING:
            data = conn.recv(1024)
            if not data:
                break
            msg = data.decode(errors="ignore").strip()
            print(f"[Online] Message from {addr}: {msg}")
    except Exception as e:
        if _RUNNING:
            print(f"[Online] Client handler error {addr}: {e}")
    finally:
        with _CLIENTS_LOCK:
            _CLIENTS = {c for c in _CLIENTS if c[0] != conn}
        conn.close()
        print(f"[Online] Client disconnected: {addr}")
        _notify_ui_clients()


def _notify_ui_clients():
    """Notify ModZT of connected clients."""
    if CLIENT_UPDATE_CALLBACK:
        try:
            with _CLIENTS_LOCK:
                peers = [addr for (_, addr) in _CLIENTS]
            CLIENT_UPDATE_CALLBACK(peers)
        except Exception as e:
            print(f"[Online] Client update callback failed: {e}")


def stop_host():
    """Stop the host, clients, and file watchers."""
    global _RUNNING, _SERVER, _OBSERVER
    _RUNNING = False

    try:
        if _SERVER:
            _SERVER.close()
            _SERVER = None
    except Exception as e:
        print(f"[Online] Stop host error: {e}")

    with _CLIENTS_LOCK:
        for conn, _ in list(_CLIENTS):
            try:
                conn.close()
            except Exception:
                pass
        _CLIENTS.clear()

    try:
        if _OBSERVER:
            _OBSERVER.stop()
            _OBSERVER.join()
            _OBSERVER = None
            print("[Online] Save watcher stopped.")
    except Exception as e:
        print(f"[Online] Watcher stop error: {e}")

    print("[Online] Server stopped.")


# ============================================================
#  Client
# ============================================================

def join_session(ip):
    """Connect to a host and listen for updates."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect((ip, _PORT))
        print(f"[Online] Connected to host at {ip}:{_PORT}")
        threading.Thread(target=_listen_to_host, args=(sock,), daemon=True).start()
        return sock
    except Exception as e:
        print(f"[Online] Join failed: {e}")
        return None


def _listen_to_host(sock):
    """Listen for incoming SAVE or TEXT messages."""
    try:
        while True:
            cmd = _recv_line(sock)
            if not cmd:
                break

            if cmd == b"SAVE":
                filename = _recv_line(sock).decode("utf-8", errors="ignore")
                size_line = _recv_line(sock)
                try:
                    total = int(size_line.decode("utf-8").strip())
                except ValueError:
                    print("[Online] Invalid SAVE size")
                    break

                data = _recvn(sock, total)
                if data is None:
                    print("[Online] Incomplete SAVE payload")
                    break

                save_dir = _ensure_save_dir()
                if not save_dir:
                    print("[Online] Could not resolve save directory.")
                    continue
                os.makedirs(save_dir, exist_ok=True)
                out_path = os.path.join(save_dir, filename)
                with open(out_path, "wb") as f:
                    f.write(data)
                print(f"[Online] Received save: {filename} ({total} bytes)")

            elif cmd == b"TEXT":
                length_bytes = sock.recv(4)
                if not length_bytes:
                    break
                length = struct.unpack("!I", length_bytes)[0]
                payload = _recvn(sock, length) or b""
                print(f"[Online] Host says: {payload.decode('utf-8', errors='ignore')}")
            else:
                print(f"[Online] Unknown command: {cmd!r}")
                break
    except Exception as e:
        print(f"[Online] Listener error: {e}")
    finally:
        try:
            sock.close()
        except Exception:
            pass
        print("[Online] Disconnected from host.")


def _recv_line(sock):
    """Receive a line terminated by newline."""
    buf = bytearray()
    while True:
        ch = sock.recv(1)
        if not ch:
            return None
        if ch == b"\n":
            return bytes(buf)
        buf.extend(ch)


def _recvn(sock, n):
    """Receive exactly n bytes or None if closed early."""
    data = bytearray()
    while len(data) < n:
        chunk = sock.recv(n - len(data))
        if not chunk:
            return None
        data.extend(chunk)
    return bytes(data)


# ============================================================
#  Save File Watcher and Broadcast
# ============================================================

class _SaveChangeHandler(FileSystemEventHandler):
    """Handles save file changes and triggers broadcasts."""
    def on_modified(self, event):
        if event.is_directory or not event.src_path.endswith(".z2s"):
            return
        print(f"[Online] Save file changed: {os.path.basename(event.src_path)}")
        push_save(event.src_path)


def start_save_watcher():
    """Watch the ZT2 save folder for changes."""
    global _OBSERVER
    print("[Debug] start_save_watcher() called")
    folder = _ensure_save_dir()
    if not folder:
        print("[Online] Save folder not found; watcher not started.")
        return

    if _OBSERVER:
        try:
            _OBSERVER.stop()
            _OBSERVER.join()
        except Exception:
            pass
        _OBSERVER = None

    observer = Observer()
    handler = _SaveChangeHandler()
    observer.schedule(handler, folder, recursive=False)
    observer.start()
    _OBSERVER = observer
    print(f"[Online] Watching for save changes in: {folder}")


def push_save(path):
    """
    Read a .z2s file and broadcast it to all connected clients.
    """
    global _CLIENTS, _CLIENTS_LOCK

    if not path or not os.path.isfile(path):
        return
    try:
        time.sleep(1.0)

        filename = os.path.basename(path)
        with open(path, "rb") as f:
            data = f.read()
        total = len(data)

        with _CLIENTS_LOCK:
            targets = list(_CLIENTS)

        if not targets:
            print("[Online] No clients connected; save not sent.")
            return

        print(f"[Online] Sending {filename} ({total} bytes) to {len(targets)} client(s)")
        for conn, addr in targets:
            try:
                conn.sendall(b"SAVE\n")
                conn.sendall((filename + "\n").encode("utf-8"))
                conn.sendall((str(total) + "\n").encode("utf-8"))
                conn.sendall(data)
            except Exception as e:
                print(f"[Online] Send error to {addr}: {e}")
                try:
                    conn.close()
                except Exception:
                    pass
                with _CLIENTS_LOCK:
                    _CLIENTS = {c for c in _CLIENTS if c[0] != conn}
    except Exception as e:
        print(f"[Online] push_save error: {e}")

# ============================================================
#  Callback registration UI
# ============================================================

def set_client_update_callback(callback):
    """
    Registers a callback function from ModZT to receive client updates.
    The callback should accept a list of (ip, port) tuples.
    Example:
        online_manager.set_client_update_callback(update_client_list)
    """
    global CLIENT_UPDATE_CALLBACK
    CLIENT_UPDATE_CALLBACK = callback
