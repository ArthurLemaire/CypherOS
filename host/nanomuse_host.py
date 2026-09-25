#!/usr/bin/env python3
"""nanoMuse host — lets the agent on your phone reach this computer (0.1.13 Reach).

One file, standard library only. Run it on the computer, read the pairing code off the
screen, type it into the app (Settings → Computers → Pair a computer), and a sentence on the
phone can run here: the shell, the files, the browser, a look at the screen. One way — the
phone drives the computer, never the other way round — and every approval happens on the
phone before a request is sent.

    python3 nanomuse_host.py                 # start; prints the address and a pairing code
    python3 nanomuse_host.py --port 7333     # another port
    python3 nanomuse_host.py --forget        # drop every paired phone and start over

Protocol (JSON over HTTP/1.1 on the local network; `Authorization: Bearer <token>` on
everything but /pair):

    POST /pair    {"code": "483921", "device": "Pixel 8"}        → {"token", "name", "os"}
    GET  /info                                                   → who and what this computer is
    POST /shell   {"command", "cwd"?, "timeout"?}                → {"exit_code", "stdout", "stderr", "timed_out"}
    GET  /files?path=~/Documents                                 → {"path", "entries": [...]}
    GET  /file?path=…                                            → the bytes
    PUT  /file?path=…  (body: the bytes)                         → {"path", "bytes"}
    POST /open    {"url": "https://…"}                           → opens it in the default browser
    GET  /screen                                                 → a JPEG or PNG of the screen, when possible

The pairing code is six digits, valid for ten minutes and for one phone; each phone gets its
own token, of which only a hash is kept in ~/.nanomuse/host.json. There is no TLS in this
version: use it on a network you trust, and `--forget` when a phone is gone.

Copyright (C) 2026 nanoMuse contributors. GPL-3.0-or-later.
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import os
import platform
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PROTOCOL_VERSION = 1
DEFAULT_PORT = 7333
PAIR_CODE_TTL_S = 10 * 60
PAIR_MAX_ATTEMPTS = 5
BODY_LIMIT = 64 * 1024 * 1024
FILE_LIMIT = 50 * 1024 * 1024
OUTPUT_LIMIT = 200 * 1024
SHELL_TIMEOUT_MAX_S = 15 * 60
SCREEN_MAX_WIDTH = 1280

STATE_DIR = Path(os.environ.get("NANOMUSE_HOME", Path.home() / ".nanomuse"))
STATE_FILE = STATE_DIR / "host.json"


# ── state ──────────────────────────────────────────────────────────────────


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class State:
    """Paired phones (token hashes) on disk; the current pairing code in memory."""

    def __init__(self, path: Path = STATE_FILE) -> None:
        self.path = path
        self.lock = threading.Lock()
        self.devices: dict[str, dict] = {}
        self.code: str | None = None
        self.code_expires = 0.0
        self.attempts = 0
        self.load()

    def load(self) -> None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self.devices = dict(data.get("devices", {}))
        except (OSError, ValueError):
            self.devices = {}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"devices": self.devices}, indent=2), encoding="utf-8")
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, self.path)

    def new_code(self) -> str:
        with self.lock:
            self.code = f"{secrets.randbelow(1_000_000):06d}"
            self.code_expires = time.time() + PAIR_CODE_TTL_S
            self.attempts = 0
            return self.code

    def code_valid(self) -> bool:
        return self.code is not None and time.time() < self.code_expires

    def try_pair(self, code: str, device: str) -> tuple[str | None, str]:
        """Returns (token, reason). A right code issues a token and retires the code."""
        with self.lock:
            if not self.code_valid():
                return None, "expired"
            if self.attempts >= PAIR_MAX_ATTEMPTS:
                return None, "locked"
            if not secrets.compare_digest(code.strip().replace(" ", ""), self.code or ""):
                self.attempts += 1
                if self.attempts >= PAIR_MAX_ATTEMPTS:
                    self.code = None
                return None, "wrong"
            token = secrets.token_urlsafe(32)
            self.devices[_hash(token)] = {
                "device": device[:80],
                "paired_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            }
            self.code = None
            self.save()
            return token, "ok"

    def authorised(self, header: str | None) -> dict | None:
        if not header or not header.startswith("Bearer "):
            return None
        token = header[len("Bearer ") :].strip()
        if not token:
            return None
        with self.lock:
            return self.devices.get(_hash(token))

    def forget_all(self) -> None:
        with self.lock:
            self.devices = {}
            self.save()


# ── the computer ───────────────────────────────────────────────────────────


def lan_addresses() -> list[str]:
    """The addresses a phone on the same network can reach."""
    found: list[str] = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("10.255.255.255", 1))
            found.append(s.getsockname()[0])
        finally:
            s.close()
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127.") and ip not in found:
                found.append(ip)
    except OSError:
        pass
    return found or ["127.0.0.1"]


def expand(path: str | None) -> Path:
    p = Path(os.path.expandvars(os.path.expanduser(path or "~"))).resolve()
    return p


def shell_name() -> str:
    if os.name == "nt":
        return os.environ.get("COMSPEC", "cmd.exe")
    return os.environ.get("SHELL", "/bin/sh")


def run_shell(command: str, cwd: str | None, timeout: float) -> dict:
    started = time.monotonic()
    timed_out = False
    try:
        proc = subprocess.run(
            command,
            shell=True,
            cwd=str(expand(cwd)) if cwd else None,
            capture_output=True,
            timeout=timeout,
        )
        code, out, err = proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired as e:
        timed_out = True
        code, out, err = 124, e.stdout or b"", e.stderr or b""
    except (OSError, ValueError) as e:
        code, out, err = 127, b"", str(e).encode()

    def text(b: bytes) -> str:
        s = b.decode("utf-8", errors="replace")
        if len(s) > OUTPUT_LIMIT:
            s = s[:OUTPUT_LIMIT] + f"\n… [{len(s) - OUTPUT_LIMIT} more characters not shown]"
        return s

    return {
        "exit_code": code,
        "stdout": text(out),
        "stderr": text(err),
        "timed_out": timed_out,
        "duration_ms": int((time.monotonic() - started) * 1000),
    }


def list_dir(path: str | None) -> dict:
    p = expand(path)
    if not p.exists():
        raise FileNotFoundError(str(p))
    if p.is_file():
        st = p.stat()
        return {"path": str(p), "entries": [_entry(p, st)]}
    entries = []
    for child in sorted(p.iterdir(), key=lambda c: (not c.is_dir(), c.name.lower())):
        try:
            entries.append(_entry(child, child.lstat()))
        except OSError:
            continue
        if len(entries) >= 2000:
            break
    return {"path": str(p), "entries": entries}


def _entry(p: Path, st: os.stat_result) -> dict:
    kind = "link" if p.is_symlink() else "dir" if p.is_dir() else "file"
    return {"name": p.name, "type": kind, "size": st.st_size, "mtime": int(st.st_mtime)}


def take_screenshot() -> tuple[bytes, str] | None:
    """A picture of the screen, at most SCREEN_MAX_WIDTH wide when Pillow is around."""
    data: bytes | None = None
    mime = "image/png"
    try:  # the good path: mss + Pillow, no external programs
        import mss  # type: ignore[import-not-found]
        from PIL import Image  # type: ignore[import-not-found]

        with mss.mss() as sct:
            shot = sct.grab(sct.monitors[1])
            img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
        if img.width > SCREEN_MAX_WIDTH:
            img = img.resize((SCREEN_MAX_WIDTH, int(img.height * SCREEN_MAX_WIDTH / img.width)))
        import io

        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=80)
        return buf.getvalue(), "image/jpeg"
    except Exception:
        pass
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "screen.png"
        cmds: list[list[str]] = []
        if sys.platform == "darwin":
            cmds.append(["screencapture", "-x", "-t", "png", str(out)])
        elif os.name == "nt":
            ps = (
                "Add-Type -AssemblyName System.Windows.Forms,System.Drawing;"
                "$b=[System.Windows.Forms.Screen]::PrimaryScreen.Bounds;"
                "$bmp=New-Object System.Drawing.Bitmap $b.Width,$b.Height;"
                "$g=[System.Drawing.Graphics]::FromImage($bmp);"
                "$g.CopyFromScreen($b.Location,[System.Drawing.Point]::Empty,$b.Size);"
                f"$bmp.Save('{out}',[System.Drawing.Imaging.ImageFormat]::Png)"
            )
            cmds.append(["powershell", "-NoProfile", "-Command", ps])
        else:
            for tool, argv in (
                ("grim", ["grim", str(out)]),
                ("gnome-screenshot", ["gnome-screenshot", "-f", str(out)]),
                ("spectacle", ["spectacle", "-b", "-n", "-o", str(out)]),
                ("import", ["import", "-window", "root", str(out)]),
                ("scrot", ["scrot", str(out)]),
            ):
                if shutil.which(tool):
                    cmds.append(argv)
        for argv in cmds:
            try:
                subprocess.run(argv, capture_output=True, timeout=20, check=False)
            except (OSError, subprocess.TimeoutExpired):
                continue
            if out.exists() and out.stat().st_size > 0:
                data = out.read_bytes()
                break
    if data is None:
        return None
    return data, mime


def info() -> dict:
    return {
        "version": PROTOCOL_VERSION,
        "name": socket.gethostname(),
        "os": platform.system(),
        "os_version": platform.release(),
        "arch": platform.machine(),
        "user": getpass.getuser(),
        "home": str(Path.home()),
        "cwd": os.getcwd(),
        "shell": shell_name(),
        "python": platform.python_version(),
        "capabilities": {"shell": True, "files": True, "browser": True, "screen": True},
    }


# ── HTTP ───────────────────────────────────────────────────────────────────


class Handler(BaseHTTPRequestHandler):
    server_version = f"nanoMuse-host/{PROTOCOL_VERSION}"
    state: State  # set on the server class

    # -- plumbing --

    def log_message(self, fmt: str, *args) -> None:  # quieter than the default
        sys.stderr.write(f"{time.strftime('%H:%M:%S')}  {fmt % args}\n")

    def _json(self, status: int, body: dict) -> None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _bytes(self, data: bytes, mime: str, name: str | None = None) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        if name:
            self.send_header("X-Name", urllib.parse.quote(name))
        self.end_headers()
        self.wfile.write(data)

    def _body(self) -> bytes:
        n = int(self.headers.get("Content-Length") or 0)
        if n > BODY_LIMIT:
            raise ValueError("body too large")
        return self.rfile.read(n) if n else b""

    def _json_body(self) -> dict:
        raw = self._body()
        if not raw:
            return {}
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("expected a JSON object")
        return data

    def _query(self) -> dict[str, str]:
        q = urllib.parse.urlparse(self.path).query
        return {k: v[0] for k, v in urllib.parse.parse_qs(q).items()}

    def _route(self) -> str:
        return urllib.parse.urlparse(self.path).path.rstrip("/") or "/"

    def _auth(self) -> dict | None:
        dev = self.state.authorised(self.headers.get("Authorization"))
        if dev is None:
            self._json(
                HTTPStatus.UNAUTHORIZED,
                {"error": "unauthorized", "message": "pair this phone first"},
            )
        return dev

    # -- verbs --

    def do_GET(self) -> None:  # noqa: N802
        try:
            route = self._route()
            if route == "/":
                self._json(
                    HTTPStatus.OK,
                    {
                        "name": "nanoMuse host",
                        "version": PROTOCOL_VERSION,
                        "pairing": self.state.code_valid(),
                    },
                )
                return
            if self._auth() is None:
                return
            if route == "/info":
                self._json(HTTPStatus.OK, info())
            elif route == "/files":
                self._json(HTTPStatus.OK, list_dir(self._query().get("path")))
            elif route == "/file":
                p = expand(self._query().get("path"))
                if not p.is_file():
                    self._json(HTTPStatus.NOT_FOUND, {"error": "not_found", "message": str(p)})
                    return
                if p.stat().st_size > FILE_LIMIT:
                    self._json(
                        HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                        {
                            "error": "too_large",
                            "message": f"{p} is over {FILE_LIMIT // (1024 * 1024)} MB",
                        },
                    )
                    return
                self._bytes(p.read_bytes(), "application/octet-stream", p.name)
            elif route == "/screen":
                shot = take_screenshot()
                if shot is None:
                    self._json(
                        HTTPStatus.NOT_IMPLEMENTED,
                        {
                            "error": "no_screen",
                            "message": "no way to take a screenshot here (pip install mss pillow)",
                        },
                    )
                    return
                self._bytes(shot[0], shot[1], "screen")
            else:
                self._json(HTTPStatus.NOT_FOUND, {"error": "no_route", "message": route})
        except FileNotFoundError as e:
            self._json(HTTPStatus.NOT_FOUND, {"error": "not_found", "message": str(e)})
        except PermissionError as e:
            self._json(HTTPStatus.FORBIDDEN, {"error": "permission", "message": str(e)})
        except Exception as e:  # noqa: BLE001
            self._json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"error": "failed", "message": f"{type(e).__name__}: {e}"},
            )

    def do_POST(self) -> None:  # noqa: N802
        try:
            route = self._route()
            if route == "/pair":
                body = self._json_body()
                token, reason = self.state.try_pair(
                    str(body.get("code", "")), str(body.get("device", "phone"))
                )
                if token is None:
                    status = {
                        "expired": HTTPStatus.GONE,
                        "locked": HTTPStatus.LOCKED,
                        "wrong": HTTPStatus.FORBIDDEN,
                    }[reason]
                    self._json(
                        status,
                        {
                            "error": reason,
                            "message": {
                                "expired": "the pairing code has expired; restart the host for a new one",
                                "locked": "too many wrong codes; restart the host for a new one",
                                "wrong": "wrong pairing code",
                            }[reason],
                        },
                    )
                    return
                print(
                    f"\nPaired: {body.get('device', 'phone')}  ({time.strftime('%H:%M:%S')})",
                    flush=True,
                )
                self._json(
                    HTTPStatus.OK,
                    {
                        "token": token,
                        "name": socket.gethostname(),
                        "os": platform.system(),
                        "version": PROTOCOL_VERSION,
                    },
                )
                return
            if self._auth() is None:
                return
            if route == "/shell":
                body = self._json_body()
                command = str(body.get("command", "")).strip()
                if not command:
                    self._json(
                        HTTPStatus.BAD_REQUEST, {"error": "usage", "message": "command is required"}
                    )
                    return
                timeout = min(float(body.get("timeout") or 120), SHELL_TIMEOUT_MAX_S)
                self._json(HTTPStatus.OK, run_shell(command, body.get("cwd"), timeout))
            elif route == "/open":
                body = self._json_body()
                url = str(body.get("url", "")).strip()
                scheme = urllib.parse.urlparse(url).scheme.lower()
                if scheme not in {"http", "https", "file"}:
                    self._json(
                        HTTPStatus.BAD_REQUEST,
                        {"error": "usage", "message": "url must be http(s):// or file://"},
                    )
                    return
                ok = webbrowser.open(url)
                self._json(HTTPStatus.OK, {"ok": bool(ok), "url": url})
            else:
                self._json(HTTPStatus.NOT_FOUND, {"error": "no_route", "message": route})
        except (ValueError, KeyError) as e:
            self._json(HTTPStatus.BAD_REQUEST, {"error": "bad_request", "message": str(e)})
        except Exception as e:  # noqa: BLE001
            self._json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"error": "failed", "message": f"{type(e).__name__}: {e}"},
            )

    def do_PUT(self) -> None:  # noqa: N802
        try:
            if self._route() != "/file":
                self._json(HTTPStatus.NOT_FOUND, {"error": "no_route", "message": self._route()})
                return
            if self._auth() is None:
                return
            p = expand(self._query().get("path"))
            data = self._body()
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
            self._json(HTTPStatus.OK, {"path": str(p), "bytes": len(data)})
        except ValueError as e:
            self._json(HTTPStatus.BAD_REQUEST, {"error": "bad_request", "message": str(e)})
        except PermissionError as e:
            self._json(HTTPStatus.FORBIDDEN, {"error": "permission", "message": str(e)})
        except Exception as e:  # noqa: BLE001
            self._json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"error": "failed", "message": f"{type(e).__name__}: {e}"},
            )


def make_server(state: State, bind: str, port: int) -> ThreadingHTTPServer:
    handler = type("BoundHandler", (Handler,), {"state": state})
    srv = ThreadingHTTPServer((bind, port), handler)
    srv.daemon_threads = True
    return srv


# ── main ───────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="nanoMuse host — let the agent on your phone reach this computer."
    )
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument(
        "--bind", default="0.0.0.0", help="address to listen on (default: every interface)"
    )
    ap.add_argument("--forget", action="store_true", help="forget every paired phone, then start")
    ap.add_argument(
        "--no-pair", action="store_true", help="start without a pairing code (paired phones only)"
    )
    args = ap.parse_args(argv)

    state = State()
    if args.forget:
        state.forget_all()
        print("Forgot every paired phone.")
    try:
        srv = make_server(state, args.bind, args.port)
    except OSError as e:
        print(f"Cannot listen on {args.bind}:{args.port}: {e}", file=sys.stderr)
        return 2

    addrs = lan_addresses()
    print(f"nanoMuse host · {socket.gethostname()} ({platform.system()} {platform.release()})")
    print(
        f"Address:      {addrs[0]}:{args.port}"
        + (
            f"   (also {', '.join(a + ':' + str(args.port) for a in addrs[1:])})"
            if len(addrs) > 1
            else ""
        )
    )
    if state.devices:
        print(f"Paired:       {len(state.devices)} phone(s)")
    if not args.no_pair:
        code = state.new_code()
        print(f"Pairing code: {code[:3]} {code[3:]}   — valid for 10 minutes, for one phone")
        print(
            "In the app:   Settings → Computers → Pair a computer, then the address and the code."
        )
    print(
        "Every approval happens on the phone before a request reaches here. Ctrl-C stops.\n",
        flush=True,
    )
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        srv.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
