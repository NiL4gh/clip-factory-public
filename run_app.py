"""ClipFactory.ai — Standalone Desktop Executable Entry Point

Launches the FastAPI backend in a background thread and presents the full
SaaS Studio inside a native Windows App Window (Edge WebView2 container).
"""
import os
import sys
import time
import socket
import threading
import multiprocessing
import urllib.request
import webview

# Force UTF-8 encoding on Windows streams
os.environ["PYTHONUTF8"] = "1"
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Ensure repository root is on sys.path
if getattr(sys, 'frozen', False):
    REPO_DIR = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
    # Prepend bundled bin dir so bundled ffmpeg/ffprobe take precedence over system ones
    BIN_DIR = os.path.dirname(sys.executable)
    os.environ["PATH"] = BIN_DIR + os.pathsep + os.environ.get("PATH", "")
else:
    REPO_DIR = os.path.dirname(os.path.abspath(__file__))

if REPO_DIR not in sys.path:
    sys.path.insert(0, REPO_DIR)


def find_available_port(start_port=8000, max_attempts=50):
    """Find an open TCP port starting from start_port."""
    for port in range(start_port, start_port + max_attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    return start_port


backend_error = [None]

def start_backend(port):
    """Run uvicorn server in background thread."""
    global backend_error
    try:
        print(f"[BACKEND] Starting Uvicorn on port {port}...", flush=True)
        import uvicorn
        from server.main import app
        config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
        server = uvicorn.Server(config)
        print(f"[BACKEND] Uvicorn server running.", flush=True)
        server.run()
    except Exception as e:
        import traceback
        backend_error[0] = traceback.format_exc()
        print(f"[BACKEND ERROR] {backend_error[0]}", flush=True)


def wait_for_backend(port, timeout=25):
    """Poll the health endpoint until the backend is ready or timeout expires."""
    health_url = f"http://127.0.0.1:{port}/health"
    deadline = time.time() + timeout
    print(f"[HEALTH] Polling {health_url}...", flush=True)
    while time.time() < deadline:
        if backend_error[0]:
            print(f"[HEALTH] Backend error detected: {backend_error[0]}", flush=True)
            return False
        try:
            with urllib.request.urlopen(health_url, timeout=1) as resp:
                if resp.status == 200:
                    print("[HEALTH] Backend is READY (200 OK)", flush=True)
                    return True
        except Exception:
            pass
        time.sleep(0.5)
    print("[HEALTH] Timed out waiting for backend", flush=True)
    return False


def acquire_instance_lock():
    """Attempt to acquire a single-instance lock using a socket."""
    lock_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    lock_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
    try:
        lock_sock.bind(("127.0.0.1", 19471))
        lock_sock.listen(1)
        return lock_sock
    except OSError:
        return None


def main():
    print("[MAIN] Entering main()...", flush=True)
    # ── Single-instance guard ────────────────────────────────────────────
    instance_lock = acquire_instance_lock()
    if instance_lock is None:
        print("[MAIN] Single-instance lock acquired by another process. Exiting.", flush=True)
        try:
            import tkinter as tk
            from tkinter import messagebox
            root = tk.Tk()
            root.withdraw()
            messagebox.showinfo(
                "ClipFactory Already Running",
                "ClipFactory is already open.\n\nCheck your taskbar or system tray."
            )
            root.destroy()
        except Exception:
            pass
        sys.exit(0)

    print("[MAIN] Single instance lock acquired.", flush=True)
    port = find_available_port(8000)
    server_url = f"http://127.0.0.1:{port}"
    print(f"[MAIN] Server URL set to {server_url}", flush=True)

    # ── Start FastAPI backend in background daemon thread ────────────────
    server_thread = threading.Thread(target=start_backend, args=(port,), daemon=True)
    server_thread.start()

    # ── Wait for backend to be ready before opening the window ───────────
    ready = wait_for_backend(port, timeout=60)
    if not ready:
        err_msg = backend_error[0] or "The backend server did not respond on port 8000 within 60s."
        print(f"[MAIN ERROR] {err_msg}", flush=True)
        try:
            import tkinter as tk
            from tkinter import messagebox
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror(
                "ClipFactory — Startup Error",
                f"ClipFactory failed to start backend server:\n\n{err_msg[:800]}"
            )
            root.destroy()
        except Exception:
            pass
        sys.exit(1)

    print("[MAIN] Backend ready! Launching window...", flush=True)

    # ── Resolve icon path (works both frozen and dev) ────────────────────
    if getattr(sys, 'frozen', False):
        icon_path = os.path.join(os.path.dirname(sys.executable), "app_icon.ico")
    else:
        icon_path = os.path.join(REPO_DIR, "app_icon.ico")
    icon_path = icon_path if os.path.exists(icon_path) else None

    # ── Create native desktop application window ─────────────────────────
    # Primary: Launch Microsoft Edge in App mode (standalone frameless window)
    # Secondary: pywebview
    # Tertiary: System default browser
    edge_paths = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ]
    target_edge = next((p for p in edge_paths if os.path.exists(p)), None)

    if target_edge:
        try:
            import subprocess
            cmd = [
                target_edge,
                f"--app={server_url}",
                "--window-size=1400,900",
                "--disable-features=PasswordManager,AutofillServerCommunication,msEdgeTextSelectionMenu,msWebSelect",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-sync",
                "--disable-translate",
                "--user-data-dir=" + os.path.join(os.environ.get("LOCALAPPDATA", REPO_DIR), "ClipFactory", "EdgeProfile")
            ]
            cflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            proc = subprocess.Popen(cmd, creationflags=cflags)
            proc.wait()
        except Exception:
            target_edge = None

    if not target_edge:
        try:
            window_kwargs = dict(
                title="ClipFactory.ai Studio",
                url=server_url,
                width=1400,
                height=900,
                min_size=(1024, 720),
                resizable=True,
                text_select=True,
            )
            if icon_path:
                window_kwargs["icon"] = icon_path
            webview.create_window(**window_kwargs)
            webview.start()
        except Exception:
            import webbrowser
            webbrowser.open(server_url)
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                pass

    # Release the single-instance lock on clean exit
    try:
        instance_lock.close()
    except Exception:
        pass


if __name__ == "__main__":
    multiprocessing.freeze_support()
    try:
        main()
    except Exception as top_err:
        import traceback
        try:
            import tkinter as tk
            from tkinter import messagebox
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror("ClipFactory Crash", f"Fatal startup exception:\n\n{traceback.format_exc()[:1000]}")
            root.destroy()
        except Exception:
            pass
        sys.exit(1)

