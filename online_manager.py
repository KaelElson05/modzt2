from __future__ import annotations
import os
import socket
import threading
import struct
import time
import json
import requests
import hashlib
import tempfile
import hmac
import secrets
import base64
from typing import Optional, Callable, Iterable, Tuple
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

_PORT = 5000

_RUNNING = False
_SERVER: Optional[socket.socket] = None
_OBSERVER: Optional[Observer] = None

_CLIENTS = set()
_CLIENTS_LOCK = threading.Lock()

_CLIENT_UPDATE_CALLBACK: Optional[Callable[[Iterable[Tuple[str, int]]], None]] = None

_SESSION_KEY: Optional[bytes] = None
_SALT: Optional[bytes] = None
_SIGNING_ENABLED: bool = False

INCOMING_DIR = os.path.join(os.getenv("APPDATA") or os.path.expanduser("~"), "ModZT", "Incoming")
os.makedirs(INCOMING_DIR, exist_ok=True)

_SAVE_DIR: Optional[str] = None

def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode("ascii")

def _unb64(s: str) -> bytes:
    return base64.b64decode(s.encode("ascii"))

def _derive_key_from_password(password: str, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 200_000, dklen=32)

def _hmac(data: bytes) -> bytes:
    global _SESSION_KEY
    if not _SESSION_KEY:
        return b""
    return hmac.new(_SESSION_KEY, data, hashlib.sha256).digest()

def _ensure_save_dir() -> Optional[str]:
    global _SAVE_DIR
    if _SAVE_DIR and os.path.isdir(_SAVE_DIR):
        return _SAVE_DIR
    appdata = os.getenv("APPDATA")
    if not appdata:
        return None
    base = os.path.join(appdata, "Microsoft Games", "Zoo Tycoon 2")
    candidates = [
        os.path.join(base, "Default Profile", "Saved"),
        os.path.join(base, "Default Profile", "Saved Games"),
    ]
    for p in candidates:
        if os.path.isdir(p):
            _SAVE_DIR = p
            return p
    return None

def get_connection_info(callback: Optional[Callable[[str, str, int], None]] = None):
    """Return (local_ip, public_ip, port) synchronously or via callback."""
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
            try:
                callback(local_ip, public_ip, _PORT)
            except Exception:
                pass
            return None
        return local_ip, public_ip, _PORT

    if callback:
        threading.Thread(target=_work, daemon=True).start()
        return None
    else:
        return _work()

def start_host(password: Optional[str] = None) -> bool:
    global _SERVER, _RUNNING, _SESSION_KEY, _SALT, _SIGNING_ENABLED
    if _RUNNING:
        print("[Online] Server already running.")
        return True

    _SALT = secrets.token_bytes(16)
    if password:
        _SESSION_KEY = _derive_key_from_password(password, _SALT)
        _SIGNING_ENABLED = True
        print("[Online] Signing enabled for this session (HMAC).")
    else:
        _SESSION_KEY = None
        _SIGNING_ENABLED = False
        print("[Online] Signing disabled (no password).")

    try:
        _RUNNING = True
        _SERVER = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        _SERVER.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        _SERVER.bind(("0.0.0.0", _PORT))
        _SERVER.listen(8)
        threading.Thread(target=_accept_loop, daemon=True).start()
        print(f"[Online] Hosting started on port {_PORT}")
        return True
    except Exception as e:
        print(f"[Online] Failed to start host: {e}")
        _RUNNING = False
        return False

def _accept_loop():
    global _RUNNING, _SERVER
    while _RUNNING and _SERVER:
        try:
            conn, addr = _SERVER.accept()
            try:
                if _SIGNING_ENABLED and _SALT:
                    conn.sendall(b"HELLO\n")
                    conn.sendall(b"SIGNING:1\n")
                    conn.sendall(f"SALT:{_b64(_SALT)}\n".encode("utf-8"))
                    conn.sendall(b"\n")
                else:
                    conn.sendall(b"HELLO\n")
                    conn.sendall(b"SIGNING:0\n")
                    conn.sendall(b"\n")
            except Exception as e:
                try:
                    conn.close()
                except Exception:
                    pass
                print(f"[Online] Handshake send failed: {e}")
                continue

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

def _client_handler(conn: socket.socket, addr: Tuple[str, int]):
    global _CLIENTS
    try:
        while _RUNNING:
            line = _recv_line(conn)
            if not line:
                break
            msg = line.decode("utf-8", errors="ignore").strip()

    except Exception as e:
        if _RUNNING:
            print(f"[Online] Client handler error {addr}: {e}")
    finally:
        with _CLIENTS_LOCK:
            _CLIENTS = {c for c in _CLIENTS if c[0] != conn}
        try:
            conn.close()
        except Exception:
            pass
        print(f"[Online] Client disconnected: {addr}")
        _notify_ui_clients()

def stop_host():
    global _RUNNING, _SERVER, _OBSERVER
    _RUNNING = False
    try:
        if _SERVER:
            _SERVER.close()
            _SERVER = None
    except Exception as e:
        print(f"[Online] Stop host error: {e}")

    with _CLIENTS_LOCK:
        for c, _ in list(_CLIENTS):
            try:
                c.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            try:
                c.close()
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

def _notify_ui_clients():
    global _CLIENT_UPDATE_CALLBACK
    if _CLIENT_UPDATE_CALLBACK:
        try:
            with _CLIENTS_LOCK:
                peers = [addr for (_, addr) in _CLIENTS]
            try:
                _CLIENT_UPDATE_CALLBACK(peers)
            except Exception as e:
                print(f"[Online] Client update callback failed: {e}")
        except Exception as e:
            print(f"[Online] Error while notifying clients: {e}")

def _frame_text_payload(message: str) -> bytes:
    data = message.encode("utf-8")
    header = b"TEXT\n" + struct.pack("!I", len(data))
    return header + data

def push_state_update(diff: dict):
    try:
        data = json.dumps(diff).encode("utf-8")
        header = b"STATE\n" + len(data).to_bytes(4, "big")
        with _CLIENTS_LOCK:
            targets = list(_CLIENTS)
        for conn, addr in targets:
            try:
                conn.sendall(header + data)
            except Exception as e:
                print(f"[Online] State send error to {addr}: {e}")
    except Exception as e:
        print(f"[Online] push_state_update error: {e}")

def join_session(ip: str) -> Optional[socket.socket]:
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect((ip, _PORT))
        threading.Thread(target=_listen_to_host, args=(sock,), daemon=True).start()
        print(f"[Online] Connected to host at {ip}:{_PORT}")
        return sock
    except Exception as e:
        print(f"[Online] Join failed: {e}")
        return None

def _recv_line(sock: socket.socket) -> Optional[bytes]:
    buf = bytearray()
    while True:
        ch = sock.recv(1)
        if not ch:
            return None
        if ch == b"\n":
            return bytes(buf)
        buf.extend(ch)

def _recvn(sock: socket.socket, n: int) -> Optional[bytes]:
    data = bytearray()
    while len(data) < n:
        chunk = sock.recv(n - len(data))
        if not chunk:
            return None
        data.extend(chunk)
    return bytes(data)

def _listen_to_host(sock: socket.socket):
    signing = False
    salt = None
    try:
        while True:
            line = _recv_line(sock)
            if line is None:
                print("[Online] Disconnected during handshake.")
                return
            if line == b"":
                break
            if line == b"HELLO":
                continue
            if line.startswith(b"SIGNING:"):
                signing = line.split(b":", 1)[1] == b"1"
            elif line.startswith(b"SALT:"):
                try:
                    salt = _unb64(line.split(b":", 1)[1].decode("utf-8"))
                except Exception:
                    salt = None

        if signing and salt:
            try:
                import state_manager
                if hasattr(state_manager, "get_session_password"):
                    pwd = state_manager.get_session_password()
                    if pwd:
                        global _SESSION_KEY
                        _SESSION_KEY = _derive_key_from_password(pwd, salt)
                        print("[Online] Client signing enabled.")
                    else:
                        print("[Online] No password provided; cannot enable signing.")
                        return
                else:
                    print("[Online] No password hook provided by UI; cannot enable signing.")
                    return
            except Exception as e:
                print(f"[Online] Could not derive key from password: {e}")
                return

        try:
            sock.sendall(b"JOIN\n")
        except Exception:
            pass

        while True:
            cmd = _recv_line(sock)
            if not cmd:
                break

            if cmd == b"SAVE":
                header = {}
                while True:
                    line = _recv_line(sock)
                    if not line:
                        break
                    if line == b"":
                        break
                    try:
                        k, v = line.decode("utf-8", errors="ignore").split(":", 1)
                        header[k.strip().upper()] = v.strip()
                    except Exception:
                        pass

                filename = header.get("FILENAME", "received.z2s")
                size = int(header.get("SIZE", "0"))
                signed_flag = header.get("SIGNED", "0") == "1"
                hmac_b64 = header.get("HMAC")

                if size <= 0:
                    print("[Online] Invalid SAVE size header")
                    continue

                data = _recvn(sock, size)
                if data is None:
                    print("[Online] Incomplete SAVE payload")
                    break

                if signed_flag:
                    if _SESSION_KEY and hmac_b64:
                        tag = _unb64(hmac_b64)
                        expected = _hmac(filename.encode("utf-8") + b"\n" + str(size).encode("ascii") + b"\n" + data)
                        if not hmac.compare_digest(expected, tag):
                            print("[Online] SAVE HMAC mismatch; discarding.")
                            continue
                    else:
                        print("[Online] Signed SAVE received but no session key available; discarding.")
                        continue

                try:
                    sha = hashlib.sha256(data).hexdigest()
                    sandbox_path = os.path.join(INCOMING_DIR, f"{filename}.part")
                    with open(sandbox_path, "wb") as f:
                        f.write(data)
                    final_path = os.path.join(INCOMING_DIR, filename)
                    os.replace(sandbox_path, final_path)
                    print(f"[Online] Received save: {filename} ({size} bytes) SHA256:{sha[:12]}...")
                except Exception as e:
                    print(f"[Online] Failed to save incoming file: {e}")
                    continue

                try:
                    save_dir = _ensure_save_dir()
                    os.makedirs(save_dir, exist_ok=True)
                    dst_path = os.path.join(save_dir, filename)

                    if os.path.exists(dst_path):
                        ts = time.strftime("%Y%m%d_%H%M%S")
                        backup_path = dst_path + f".bak_{ts}"
                        os.rename(dst_path, backup_path)
                        print(f"[Online] Backup created: {backup_path}")

                    with open(dst_path, "wb") as out:
                        out.write(data)

                    print(f"[Online] Save auto-applied: {dst_path}")
                    try:
                        import state_manager
                        state_manager.start_auto_reload_watcher(save_dir)
                    except Exception as e:
                        print(f"[Online] Auto-reload watcher failed: {e}")

                    try:
                        import state_manager
                        if hasattr(state_manager, "notify_incoming_save"):
                            state_manager.notify_incoming_save(dst_path, sha)
                    except Exception as e:
                        print(f"[Online] UI notify failed: {e}")

                except Exception as e:
                    print(f"[Online] Auto-apply failed: {e}")

            elif cmd == b"STATE":
                size_bytes = sock.recv(4)
                if not size_bytes:
                    break
                size = int.from_bytes(size_bytes, "big")
                data = _recvn(sock, size)
                if not data:
                    break
                try:
                    diff = json.loads(data.decode("utf-8"))
                    import state_manager
                    if hasattr(state_manager, "apply_state_diff"):
                        state_manager.apply_state_diff(diff)
                except Exception as e:
                    print(f"[Online] Invalid STATE payload: {e}")

            else:
                print(f"[Online] Unknown command from host: {cmd!r}")
                break

    except Exception as e:
        print(f"[Online] Listener error: {e}")
    finally:
        try:
            sock.close()
        except Exception:
            pass
        print("[Online] Disconnected from host.")

class _SaveChangeHandler(FileSystemEventHandler):
    def on_modified(self, event):
        if event.is_directory or not event.src_path.lower().endswith(".z2s"):
            return
        print(f"[Online] Save file changed: {os.path.basename(event.src_path)}")
        push_save(event.src_path)

def start_save_watcher():
    global _OBSERVER
    folder = _ensure_save_dir()
    if not folder:
        print("[Online] Save folder not found; watcher not started.")
        return False
    if _OBSERVER:
        try:
            _OBSERVER.stop()
            _OBSERVER.join()
        except Exception:
            pass
        _OBSERVER = None
    observer = Observer()
    observer.schedule(_SaveChangeHandler(), folder, recursive=False)
    observer.start()
    _OBSERVER = observer
    print(f"[Online] Watching for save changes in: {folder}")
    return True

def push_save(path: str):
    global _CLIENTS
    if not path or not os.path.isfile(path):
        return
    try:
        time.sleep(0.5)
        filename = os.path.basename(path)
        with open(path, "rb") as f:
            data = f.read()
        total = len(data)
        with _CLIENTS_LOCK:
            targets = list(_CLIENTS)
        if not targets:
            print("[Online] No clients connected; save not sent.")
            return

        signed = _SIGNING_ENABLED and (_SESSION_KEY is not None)
        header_lines = []
        header_lines.append(b"SAVE\n")
        header_lines.append(f"FILENAME:{filename}\n".encode("utf-8"))
        header_lines.append(f"SIZE:{total}\n".encode("utf-8"))
        header_lines.append(b"SIGNED:1\n" if signed else b"SIGNED:0\n")
        if signed:
            tag = _hmac(filename.encode("utf-8") + b"\n" + str(total).encode("ascii") + b"\n" + data)
            header_lines.append(f"HMAC:{_b64(tag)}\n".encode("utf-8"))
        header_lines.append(b"\n")
        frame_head = b"".join(header_lines)

        print(f"[Online] Sending {filename} ({total} bytes) to {len(targets)} client(s)")
        for conn, addr in targets:
            try:
                conn.sendall(frame_head)
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

def set_client_update_callback(callback: Callable[[Iterable[Tuple[str, int]]], None]):
    """UI should call this to receive connected client list updates."""
    global _CLIENT_UPDATE_CALLBACK
    _CLIENT_UPDATE_CALLBACK = callback
