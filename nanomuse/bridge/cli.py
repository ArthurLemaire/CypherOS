"""``nanomuse-device``, ``nanomuse-browser`` and ``nanomuse-open``.

Small on purpose: the standard library only, so a script that calls them ten times does
not pay for Typer and Rich ten times on a phone. They read the two variables the shell tool
sets for the command they run in, post one JSON request to the server and print the answer.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any

from nanomuse.bridge.tokens import BRIDGE_TOKEN_ENV, BRIDGE_URL_ENV

NOT_HERE = (
    "nanoMuse's bridge is not here: this program works inside a command the agent runs "
    "from `nanomuse serve` (the app), where the server sets "
    f"{BRIDGE_URL_ENV} and {BRIDGE_TOKEN_ENV} for it."
)


class BridgeClient:
    def __init__(self, url: str | None = None, token: str | None = None, timeout: float = 600.0):
        self.url = (url or os.environ.get(BRIDGE_URL_ENV, "")).rstrip("/")
        self.token = token or os.environ.get(BRIDGE_TOKEN_ENV, "")
        self.timeout = timeout

    @property
    def available(self) -> bool:
        return bool(self.url and self.token)

    def post(self, kind: str, body: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", f"/api/bridge/{kind}", body)

    def get(self, path: str) -> dict[str, Any]:
        return self._request("GET", path, None)

    def _request(self, method: str, path: str, body: dict[str, Any] | None) -> dict[str, Any]:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            self.url + path,
            data=data,
            method=method,
            headers={"Content-Type": "application/json", "X-Nanomuse-Bridge": self.token},
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # noqa: S310 — 127.0.0.1
                return json.loads(resp.read().decode() or "{}")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")
            try:
                detail = json.loads(detail).get("detail", detail)
            except ValueError:
                pass
            return {"ok": False, "error": f"{detail or exc.reason} (HTTP {exc.code})"}
        except (urllib.error.URLError, OSError) as exc:
            return {"ok": False, "error": f"cannot reach nanoMuse at {self.url}: {exc}"}


def _print(result: dict[str, Any], as_json: bool) -> int:
    """The result on stdout (JSON when asked), the error on stderr; the exit code says which."""
    if as_json:
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result.get("ok") else 1
    if result.get("ok"):
        out = result.get("output") or ""
        if out:
            print(out)
        for path in result.get("images") or []:
            print(f"[image] {path}")
        return 0
    print(f"error: {result.get('error') or 'failed'}", file=sys.stderr)
    return 1


def parse_pairs(items: list[str]) -> dict[str, Any]:
    """``key=value`` arguments; a value that parses as JSON (``3``, ``true``, ``["a"]``) is
    taken as such, anything else stays a string."""
    args: dict[str, Any] = {}
    for item in items:
        if "=" not in item:
            raise SystemExit(f"error: expected key=value, got '{item}'")
        key, value = item.split("=", 1)
        key = key.strip().replace("-", "_")
        if not key:
            raise SystemExit(f"error: empty key in '{item}'")
        try:
            args[key] = json.loads(value)
        except ValueError:
            args[key] = value
    return args


# ------------------------------------------------------------------ nanomuse-device
def device_main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="nanomuse-device",
        description="The phone's capabilities, from a command the agent runs: "
        "`nanomuse-device CAPABILITY [ACTION] [key=value ...]`, e.g. `clipboard read`, "
        "`alarm set hour=7 minute=30 message=Train`, `notify title=Done body='Booked.'`. "
        "`nanomuse-device list` shows what this phone has.",
    )
    p.add_argument(
        "capability",
        help="clipboard, calendar, alarm, timer, contacts, location, notify, photo … or `list`",
    )
    p.add_argument(
        "action",
        nargs="?",
        help="read, write, list, create, set, search, pick … (none for notify, location, calendars)",
    )
    p.add_argument("pairs", nargs="*", metavar="key=value")
    p.add_argument("--json", action="store_true", help="print the raw result as JSON")
    ns = p.parse_args(argv)
    client = BridgeClient()
    if not client.available:
        print(NOT_HERE, file=sys.stderr)
        return 2
    if ns.capability == "list" and ns.action is None:
        result = client.get("/api/bridge/tools")
        if ns.json or not result.get("ok"):
            return _print(result, True)
        tools = result.get("tools") or []
        if not tools:
            print("no device capabilities here (no phone connected)")
            return 1
        for t in tools:
            print(f"{t['name'].replace('_', ' ', 1):<28} {t.get('description', '')}")
        return 0
    pairs = list(ns.pairs)
    action = ns.action
    if action is not None and "=" in action:  # `nanomuse-device notify title=…`: no action word
        pairs.insert(0, action)
        action = None
    tool = ns.capability if action is None else f"{ns.capability}_{action}"
    body = {"tool": tool, "args": parse_pairs(pairs)}
    return _print(client.post("device", body), ns.json)


# ------------------------------------------------------------------ nanomuse-browser
def browser_main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="nanomuse-browser",
        description="The agent's browser view, from a command: navigate, extract, click, type, press, "
        "scroll, back, wait, screenshot, fetch, close. The user sees the same page in the app and can take over.",
    )
    p.add_argument("--json", action="store_true", help="print the raw result as JSON")
    sub = p.add_subparsers(dest="action", required=True)
    sub.add_parser("navigate", help="open a URL").add_argument("url")
    sub.add_parser("extract", help="the page as text, with numbered interactive elements")
    sub.add_parser("click", help="click element N from the last extract").add_argument(
        "index", type=int
    )
    t = sub.add_parser("type", help="type into element N")
    t.add_argument("index", type=int)
    t.add_argument("text")
    t.add_argument("--submit", action="store_true", help="press Enter afterwards")
    sub.add_parser("press", help="press a key, e.g. Enter").add_argument("key")
    sub.add_parser("scroll", help="scroll the page").add_argument(
        "direction", choices=["up", "down"]
    )
    sub.add_parser("back", help="go back one page")
    sub.add_parser("wait", help="give a page that is still drawing itself a moment").add_argument(
        "seconds", type=float, nargs="?", default=None
    )
    sub.add_parser("screenshot", help="a picture of the page; prints where it was saved")
    f = sub.add_parser(
        "fetch",
        help="GET a URL with the browser's cookies (signed in) and print the raw body; "
        "--post BODY for a POST",
    )
    f.add_argument("url")
    f.add_argument("--post", dest="body", metavar="BODY", help="send this body with POST")
    pr = sub.add_parser("profile", help="how the browser presents itself")
    pr.add_argument("profile", nargs="?", choices=["mobile", "desktop"])
    pr.add_argument("--user-agent", dest="user_agent")
    pr.add_argument("--width", type=int)
    pr.add_argument("--height", type=int)
    sub.add_parser("close", help="close the browser")
    ns = p.parse_args(argv)
    client = BridgeClient()
    if not client.available:
        print(NOT_HERE, file=sys.stderr)
        return 2
    body: dict[str, Any] = {"action": ns.action}
    for key in (
        "url",
        "index",
        "text",
        "key",
        "direction",
        "seconds",
        "profile",
        "user_agent",
        "width",
        "height",
    ):
        if getattr(ns, key, None) is not None:
            body[key] = getattr(ns, key)
    if ns.action == "type" and ns.submit:
        body["submit"] = True
    if ns.action == "fetch" and ns.body is not None:
        body["method"] = "POST"
        body["body"] = ns.body
    return _print(client.post("browser", body), ns.json)


# ------------------------------------------------------------------ nanomuse-open
def open_main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="nanomuse-open",
        description="Open a page for the user in the app's browser view (the root file system's "
        "$BROWSER on the phone): a sign-in, a payment, anything that is theirs to do.",
    )
    p.add_argument("url")
    p.add_argument("--json", action="store_true")
    ns = p.parse_args(argv)
    client = BridgeClient()
    if not client.available:
        print(NOT_HERE, file=sys.stderr)
        return 2
    return _print(client.post("open", {"url": ns.url}), ns.json)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(device_main())
