# Writing a connector

A connector bridges a dot to an external system. It implements two methods:

```python
class Connector(Protocol):
    name: str
    async def poll(self) -> list[ConnectorEvent]: ...
    async def send(self, action: str, **kwargs) -> dict: ...
```

- **`poll`** returns new inbound items since the last call (may be empty).
- **`send`** performs an outbound action and returns the provider's response.

## Example: a minimal RSS connector

```python
from dots.connectors.base import ConnectorEvent

class RSSConnector:
    name = "rss"

    def __init__(self, url: str, client=None):
        self._url = url
        self._client = client
        self._seen: set[str] = set()

    async def poll(self) -> list[ConnectorEvent]:
        import httpx
        client = self._client or httpx.AsyncClient(timeout=15)
        resp = await client.get(self._url)
        items = parse_feed(resp.text)          # your parser
        fresh = [i for i in items if i["id"] not in self._seen]
        self._seen.update(i["id"] for i in fresh)
        return [
            ConnectorEvent(connector=self.name, kind="item",
                           data={"title": i["title"], "link": i["link"]})
            for i in fresh
        ]

    async def send(self, action: str, **kwargs):
        raise NotImplementedError("rss is read-only")
```

## Guidelines

- **Inject the HTTP client.** Accept a `client=` argument so tests pass a fake.
- **Track a cursor.** Only return items newer than the last poll.
- **Normalize.** Map provider payloads to `ConnectorEvent`; don't leak raw shapes.
- **Fail soft.** A transient poll error should return `[]`, not crash the dot.

## Turning connector events into dot events

```python
events = [ce.to_event() for ce in await connector.poll()]
await dot.step(*events)
```

See the bundled `SlackConnector`, `GitHubConnector`, and `GmailConnector` for
complete, testable references.
