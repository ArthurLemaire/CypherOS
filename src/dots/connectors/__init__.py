"""Connectors bridge a dot to the outside world (inbound events, outbound actions)."""

from __future__ import annotations

from dots.connectors.base import Connector, ConnectorEvent
from dots.connectors.github import GitHubConnector
from dots.connectors.gmail import GmailConnector
from dots.connectors.slack import SlackConnector

__all__ = [
    "Connector",
    "ConnectorEvent",
    "GitHubConnector",
    "GmailConnector",
    "SlackConnector",
]
