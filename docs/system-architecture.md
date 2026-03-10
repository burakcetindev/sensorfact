# System Architecture

## Request lifecycle

```mermaid
flowchart LR
    CLI([curl / browser]) -->|HTTP POST| GQL[GraphQL Endpoint\nPOST /graphql]
    GQL -->|context injection| RES[Ariadne Resolver]
    RES -->|calls| SVC[EnergyService]
    SVC -->|cache-first| CAC[(TTL Cache)]
    SVC -->|on miss| CLI2[BlockchainClient]
    CLI2 -->|HTTPS with retry| BCAPI[blockchain.com REST API]
    BCAPI -->|JSON| CLI2
    CLI2 --> SVC
    SVC -->|domain model| RES
    RES -->|dict| GQL
    GQL -->|JSON response| CLI
```

---

## Deployment view

```mermaid
flowchart TB
    subgraph Host["Host machine / container"]
        UV[uvicorn on :4000]
        APP[FastAPI app]
        UV --> APP
    end
    BROWSER([Browser]) -->|GET /graphql| UV
    CURL([curl / demo.sh]) -->|POST /graphql| UV
    APP -->|HTTPS| BCAPI[blockchain.com]
```

---

## Runtime characteristics

| Property | Detail |
|---|---|
| Async I/O | All HTTP calls are `await`-based; no threads blocked |
| Bounded fan-out | `asyncio.Semaphore(8)` limits concurrent blockchain calls |
| Cache strategy | TTL cache per entity type (block 15 min, tx 15 min, day 5 min) |
| Retry policy | Up to 4 attempts with 0.5 s / 1 s / 2 s / 4 s backoff on 429 / 5xx |
| Error surface | All integration errors map to typed domain exceptions surfaced in GraphQL `errors[]` |

---

## Extensibility points

- **Cache**: swap `TTLCache` for a Redis adapter without touching `EnergyService`
- **Blockchain provider**: implement a new `BlockchainClient` subclass or replacement
- **New queries**: add resolver + SDL type; service logic stays isolated
- **Observability**: add structured logging / metrics middleware at the FastAPI layer
