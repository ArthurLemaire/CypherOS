"""The PC companion (host/nanomuse_host.py): pairing, the token, and the five verbs."""

from __future__ import annotations

import importlib.util
import json
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

HOST_FILE = Path(__file__).resolve().parents[1] / "host" / "nanomuse_host.py"


def _load():
    spec = importlib.util.spec_from_file_location("nanomuse_host", HOST_FILE)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def host():
    return _load()


@pytest.fixture
def server(host, tmp_path):
    state = host.State(tmp_path / "host.json")
    srv = host.make_server(state, "127.0.0.1", 0)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    yield state, base
    srv.shutdown()
    srv.server_close()


def call(base, method, route, body=None, token=None, raw=None, headers=None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(base + route, data=data, method=method)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    if body is not None:
        req.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            payload = resp.read()
            ctype = resp.headers.get("Content-Type", "")
            return resp.status, (
                json.loads(payload) if ctype.startswith("application/json") else payload
            )
    except urllib.error.HTTPError as e:
        payload = e.read()
        try:
            return e.code, json.loads(payload)
        except ValueError:
            return e.code, payload


def pair(state, base):
    code = state.new_code()
    status, body = call(base, "POST", "/pair", {"code": code, "device": "test phone"})
    assert status == 200, body
    return body["token"]


def test_root_says_whether_pairing_is_open(server):
    state, base = server
    status, body = call(base, "GET", "/")
    assert status == 200 and body["pairing"] is False
    state.new_code()
    assert call(base, "GET", "/")[1]["pairing"] is True


def test_pairing_needs_the_right_code_and_retires_it(server):
    state, base = server
    assert call(base, "POST", "/pair", {"code": "000000"})[0] == 410  # no code yet
    code = state.new_code()
    wrong = "000000" if code != "000000" else "111111"
    assert call(base, "POST", "/pair", {"code": wrong})[0] == 403
    status, body = call(
        base, "POST", "/pair", {"code": code[:3] + " " + code[3:], "device": "Pixel"}
    )
    assert status == 200 and body["token"] and body["version"] == 1
    # one phone per code
    assert call(base, "POST", "/pair", {"code": code})[0] == 410
    # only a hash is stored
    saved = json.loads(state.path.read_text(encoding="utf-8"))
    assert body["token"] not in state.path.read_text(encoding="utf-8")
    assert list(saved["devices"].values())[0]["device"] == "Pixel"


def test_five_wrong_codes_lock_the_code(server):
    state, base = server
    code = state.new_code()
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(5):
        assert call(base, "POST", "/pair", {"code": wrong})[0] in (403, 423)
    assert call(base, "POST", "/pair", {"code": code})[0] in (410, 423)


def test_everything_else_needs_the_token(server):
    state, base = server
    for method, route in (
        ("GET", "/info"),
        ("GET", "/files"),
        ("POST", "/shell"),
        ("POST", "/open"),
        ("PUT", "/file?path=x"),
    ):
        status, body = call(
            base,
            method,
            route,
            body={} if method == "POST" else None,
            raw=b"" if method == "PUT" else None,
        )
        assert status == 401, (route, body)
    assert call(base, "GET", "/info", token="not-a-token")[0] == 401


def test_info_and_shell(server):
    state, base = server
    token = pair(state, base)
    status, body = call(base, "GET", "/info", token=token)
    assert status == 200 and body["capabilities"]["shell"] is True and body["name"]
    status, body = call(
        base, "POST", "/shell", {"command": f'"{sys.executable}" -c "print(6*7)"'}, token=token
    )
    assert (
        status == 200
        and body["exit_code"] == 0
        and body["stdout"].strip() == "42"
        and body["timed_out"] is False
    )
    status, body = call(
        base,
        "POST",
        "/shell",
        {"command": f'"{sys.executable}" -c "import sys; sys.exit(3)"'},
        token=token,
    )
    assert body["exit_code"] == 3
    status, body = call(
        base,
        "POST",
        "/shell",
        {"command": f'"{sys.executable}" -c "import time; time.sleep(5)"', "timeout": 0.5},
        token=token,
    )
    assert body["timed_out"] is True and body["exit_code"] == 124
    assert call(base, "POST", "/shell", {"command": ""}, token=token)[0] == 400


def test_files_round_trip(server, tmp_path):
    state, base = server
    token = pair(state, base)
    target = tmp_path / "out" / "hello.txt"
    status, body = call(base, "PUT", f"/file?path={target}", raw="你好 host".encode(), token=token)
    assert status == 200 and body["bytes"] == len("你好 host".encode())
    status, data = call(base, "GET", f"/file?path={target}", token=token)
    assert status == 200 and data == "你好 host".encode()
    status, body = call(base, "GET", f"/files?path={tmp_path / 'out'}", token=token)
    assert status == 200 and [e["name"] for e in body["entries"]] == ["hello.txt"]
    assert body["entries"][0]["type"] == "file"
    assert call(base, "GET", f"/files?path={tmp_path / 'missing'}", token=token)[0] == 404
    assert call(base, "GET", f"/file?path={tmp_path / 'missing'}", token=token)[0] == 404


def test_open_only_takes_web_urls(server, host, monkeypatch):
    state, base = server
    token = pair(state, base)
    opened = []
    monkeypatch.setattr(host.webbrowser, "open", lambda url: opened.append(url) or True)
    status, body = call(base, "POST", "/open", {"url": "https://example.com/x"}, token=token)
    assert status == 200 and body["ok"] is True and opened == ["https://example.com/x"]
    assert call(base, "POST", "/open", {"url": "javascript:alert(1)"}, token=token)[0] == 400
    assert call(base, "POST", "/open", {"url": "ssh://host"}, token=token)[0] == 400


def test_screen_is_a_picture_or_a_clear_no(server, host, monkeypatch):
    state, base = server
    token = pair(state, base)
    monkeypatch.setattr(host, "take_screenshot", lambda: (b"\x89PNG fake", "image/png"))
    status, data = call(base, "GET", "/screen", token=token)
    assert status == 200 and data == b"\x89PNG fake"
    monkeypatch.setattr(host, "take_screenshot", lambda: None)
    status, body = call(base, "GET", "/screen", token=token)
    assert status == 501 and body["error"] == "no_screen"


def test_lan_addresses_and_expand(host):
    assert host.lan_addresses()
    assert host.expand("~").is_absolute()
    assert host.expand(None) == host.expand("~")
