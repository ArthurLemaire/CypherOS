"""``python -m showcase_gateway`` — run the gateway with uvicorn, settings from the environment."""

from __future__ import annotations

import uvicorn

from .config import Settings


def main() -> None:
    settings = Settings.from_env()
    uvicorn.run(
        "showcase_gateway.app:build",
        factory=True,
        host=settings.listen_host,
        port=settings.listen_port,
        proxy_headers=settings.trust_proxy,
        forwarded_allow_ips="*" if settings.trust_proxy else None,
        log_level="info",
        ws_ping_interval=20,
        ws_ping_timeout=20,
    )


if __name__ == "__main__":
    main()
