# Memory

Memory is long-lived knowledge. (Short-lived scratch belongs in `State`.)
All backends implement the same protocol:

```python
await memory.remember("lithium supply tightened", tags=["news"])
hits = await memory.recall("lithium", k=5)   # ranked, best first
```

## Backends

| Backend | Recall | Persistence | Extra dep |
|---------|--------|-------------|-----------|
| `InMemoryMemory` | Jaccard token overlap | none | — |
| `SqliteMemory` | FTS5 (falls back to LIKE) | file | — |
| `VectorMemory` | cosine similarity | none | `[vector]` |

## Choosing one

- **Demos / tests** → `InMemoryMemory` (zero config).
- **Long-running dots** → `SqliteMemory` (survives restarts).
- **Semantic recall** → `VectorMemory` with a real embedder.

## Custom embedders

`VectorMemory` takes any `str -> list[float]` callable. The default is a
dependency-free hashing embedder so tests need no model. Swap in a real one:

```python
from dots.memory.vector import VectorMemory

def embed(text: str) -> list[float]:
    return my_model.encode(text).tolist()

memory = VectorMemory(embedder=embed)
```

## Recall in the loop

On every step the runtime recalls against the goal's objective and passes the
top matches to the planner, so a dot's past learnings inform its next actions.
