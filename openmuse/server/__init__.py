"""OpenMuse app server: the always-on agent behind the mobile-first web app.

    openmuse serve                     # http://127.0.0.1:8787
    openmuse serve --host 0.0.0.0      # reachable from your phone on the same Wi-Fi

Everything the CLI can do, the app can do — plus background work while the app
is closed, approval cards, side chats, goals, ideas, memory you can edit, and an
activity log behind the avatar.
"""

from __future__ import annotations

import socket

from openmuse.config import Settings
from openmuse.server.api import STATIC_DIR, create_app
from openmuse.server.service import MuseService

__all__ = ["MuseService", "STATIC_DIR", "create_app", "lan_ip", "serve"]


def lan_ip() -> str | None:
    """Best-effort LAN address (no packets are actually sent)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
    except OSError:
        return None


def serve(
    settings: Settings,
    host: str | None = None,
    port: int | None = None,
    print_qr: bool = True,
    log_level: str = "warning",
) -> None:
    """Run the app server (blocking). Prints the URL and a QR code for your phone."""
    import uvicorn

    host = host or settings.server.host
    port = port or settings.server.port
    service = MuseService(settings)
    app = create_app(settings, service)

    shown_host = host
    if host in ("0.0.0.0", "::", ""):
        shown_host = lan_ip() or "127.0.0.1"
    url = f"http://{shown_host}:{port}/"
    if service.token:
        url += f"?token={service.token}"
    _print_banner(url, service, print_qr)
    uvicorn.run(
        app, host=host, port=port, log_level=log_level, ws_ping_interval=20, ws_ping_timeout=20
    )


def _print_banner(url: str, service: MuseService, print_qr: bool) -> None:
    from rich.console import Console

    console = Console()
    name = service.profile.name
    console.print(f"[bold magenta]OpenMuse[/bold magenta] · [bold]{name}[/bold] is ready.")
    if not STATIC_DIR.is_dir():
        console.print(
            "[yellow]web app not built[/yellow] — run `cd web && npm install && npm run build`"
        )
    console.print(f"Open on this device or your phone:  [bold cyan]{url}[/bold cyan]")
    if service.token:
        console.print(
            "[dim]The link includes your access token — share it only with your own devices.[/dim]"
        )
    if print_qr:
        try:
            import qrcode

            qr = qrcode.QRCode(border=1)
            qr.add_data(url)
            qr.make(fit=True)
            qr.print_ascii(invert=True)
        except Exception:  # noqa: BLE001  pragma: no cover
            pass
    console.print(
        "[dim]Press Ctrl+C to stop. Your OpenMuse keeps working in the background while it runs.[/dim]"
    )
