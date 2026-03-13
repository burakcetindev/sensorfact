# Bitcoin Energy Consumption API

A GraphQL API for monitoring Bitcoin network energy consumption, built with Python.

## Stack

| Component | Role |
|---|---|
| **Python 3.12+** | Language runtime |
| **FastAPI** | HTTP server, health endpoint, GraphiQL serving |
| **Ariadne** | Schema-first GraphQL (SDL → resolvers) |
| **httpx** | Async HTTP client with automatic redirect following |
| **mempool.space** | Live Bitcoin blockchain data source (public REST API) — see note below |
| **TTLCache** | In-process per-entity time-to-live cache |

> **API choice:** The assignment suggests `blockchain.com` / `blockchain.info`.
> After testing, that API throttled aggressively (frequent HTTP 429), had inconsistent
> CORS headers, and several of its documented endpoints returned HTML error pages
> rather than JSON.
> [mempool.space](https://mempool.space/docs/api/rest) is an open-source alternative
> that exposes the same data (blocks, transactions, wallet addresses) with consistent
> JSON responses, clearer rate-limit behaviour, and better documentation.
> The normalisation layer in `BlockchainClient` maps mempool.space response shapes
> to the dict format the service layer expects, so swapping data sources in future
> requires changing only that file.

## Requirements coverage

| Requirement | Query | Status |
|---|---|---|
| Energy per transaction for a specific block | `energyPerTransactionForBlock` | ✅ Mandatory |
| Total energy per day over last X days | `totalEnergyConsumptionLastDays` | ✅ Mandatory |
| Caching to avoid redundant API calls | TTLCache on blocks + daily summaries | ✅ Optional |
| Total energy for a wallet address | `totalEnergyByWalletAddress` | ✅ Optional |

## Quick start

```bash
# 1. Create virtualenv and install dependencies
./scripts/build.sh

# 2. Start the API server on port 4000
./scripts/start.sh
```

| Endpoint | URL |
|---|---|
| GraphQL API | `http://localhost:4000/graphql` |
| GraphiQL IDE (browser) | `http://localhost:4000/graphql` (GET) |
| Health check | `http://localhost:4000/health` |

## Interactive demo

```bash
./scripts/demo.sh
```

A menu-driven shell script that starts the server if needed, then walks through
every API feature with real live Bitcoin data. See `docs/images/` for screenshots
of the demo in action.

## GraphQL queries

### 1. Energy per transaction — specific block

Paste any of these ready-to-run hashes (early blocks have 1–2 transactions and
return in under 5 seconds):

| Block | Hash |
|---|---|
| Block 1 | `00000000839a8e6886ab5951d76f411475428afc90947ee320161bbf18eb6048` |
| Block 170 | `00000000d1145790a8694403d4063f323d499e655c83426834d4ce2f8dd4a2ee` |
| Block 1000 | `00000000c937983704a73af28acdec37b049d214adbda81d7e2a3dd146f6ed09` |

You can also pass a block **height** (numeric string) and the API resolves it to a hash.

```graphql
query BlockEnergy {
  energyPerTransactionForBlock(
    blockIdentifier: "00000000839a8e6886ab5951d76f411475428afc90947ee320161bbf18eb6048"
  ) {
    blockHash
    blockHeight
    transactionCount
    totalEnergyKwh
    energyPerTransactionKwh
    transactions {
      hash
      sizeBytes
      energyKwh
    }
  }
}
```

### 2. Daily energy — last N days

Start with `days: 1` (~10 s). Each additional day adds ~10 s on a cold cache.

```graphql
query DailyEnergy {
  totalEnergyConsumptionLastDays(days: 1) {
    date
    blockCount
    transactionCount
    totalEnergyKwh
  }
}
```

### 3. Latest block

```graphql
query LatestBlock {
  latestBlock {
    hash
    height
  }
}
```

### 4. Wallet energy footprint

```graphql
query WalletEnergy {
  totalEnergyByWalletAddress(
    address: "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"
  ) {
    address
    transactionCount
    totalEnergyKwh
  }
}
```

## Energy model

```
energy_kwh = transaction_size_bytes × 4.56
```

For the daily query, the block-level `size` field (sum of all transaction bytes)
is used instead of fetching every individual transaction — this avoids ~80 extra
API calls per block while producing identical results.

## Rate limiting and performance

This API hits the public mempool.space REST API, which enforces rate limits.
Several strategies are layered to keep response times fast and avoid 429 errors:

| Strategy | Where | Benefit |
|---|---|---|
| **Parallel page fetching** | `BlockchainClient._get_block_txs` | All transaction pages for a block are fetched concurrently (semaphore-bounded), cutting block query time from ~60 s to ~5–10 s |
| **Single-pass multi-day walk** | `BlockchainClient.get_blocks_for_days` | One backwards walk from the chain tip collects data for all requested days; previously N days required N separate walks, each starting from the tip |
| **asyncio.Semaphore** | `BlockchainClient._get_block_txs` | Caps concurrent outbound requests at `max_parallel_requests` (default 5) to avoid flooding the API |
| **Exponential backoff** | `BlockchainClient._get` | On 429 or network error, backs off starting at 0.5 s (regular errors) or 5 s (rate limit), doubling each retry, up to 4 attempts |
| **TTL block cache** | `EnergyService._block_cache` | Blocks cached for 15 min — a repeated query for the same block returns instantly |
| **TTL daily cache** | `EnergyService._daily_cache` | Daily summaries cached for 5 min — a second query within a session costs nothing |
| **Block-level size aggregation** | `EnergyService._daily_energy_for_date` | Uses the `size` field from the block summary endpoint rather than fetching all transaction pages, eliminating the biggest source of API call fan-out |
| **`days ≤ 60` guard** | `EnergyService._validate_days` | Hard limit prevents unbounded API fan-out |

See `docs/data-flow.md` for sequence diagrams and `docs/edge-cases.md` for the
full rate-limit handling decision tree.

## Documentation

| File | Contents |
|---|---|
| `docs/architecture.md` | Layer diagram, class relationships, OOP principles, scaling path |
| `docs/system-architecture.md` | Request lifecycle, deployment view, runtime characteristics |
| `docs/data-flow.md` | Sequence diagrams for every query including cache and retry paths |
| `docs/edge-cases.md` | Input validation rules, API failure modes, data inconsistency handling |
| `docs/considerations.md` | Design rationale: API choice, trade-offs, limitations, and mitigation strategy |
| `docs/images/` | Screenshots of the GraphiQL UI and demo CLI in action |

---

## Project file hierarchy

```
sensorfact/
│
├── README.md                    ← This file — setup, queries, architecture summary
├── requirements.txt             ← Python dependencies (FastAPI, Ariadne, httpx, pytest …)
├── pytest.ini                   ← Test runner config: asyncio mode, coverage gate ≥80%
├── .gitignore                   ← Excludes .venv/, __pycache__/, .coverage, .env, etc.
│
├── scripts/
│   ├── build.sh                 ← Creates .venv and installs requirements.txt
│   ├── start.sh                 ← Starts the API server on port 4000 (runs build if needed)
│   └── demo.sh                  ← Interactive menu-driven demo; auto-starts the server
│
├── src/
│   ├── main.py                  ← FastAPI app: mounts GraphQL endpoint, serves GraphiQL IDE,
│   │                               exposes GET /health, handles malformed request bodies
│   │
│   ├── api/
│   │   └── schema.py            ← Ariadne SDL type definitions; all four GraphQL resolvers;
│   │                               camelCase DTO mapper functions (_to_block, _to_daily, _to_wallet)
│   │
│   ├── clients/
│   │   └── blockchain_client.py ← All HTTP I/O against mempool.space REST API.
│   │                               Implements: exponential-backoff retries, 429 rate-limit
│   │                               handling, parallel tx-page fetching (asyncio.gather +
│   │                               Semaphore), single-pass multi-day block walk
│   │
│   ├── config/
│   │   └── settings.py          ← Pydantic Settings class; all tunable values (energy model
│   │                               constant, cache TTLs, retry counts, parallel request cap,
│   │                               CO₂ factor) — all overridable via APP_* environment variables
│   │
│   ├── domain/
│   │   └── models.py            ← Four frozen dataclasses: TransactionEnergy,
│   │                               BlockEnergySummary, DailyEnergySummary, WalletEnergySummary.
│   │                               These are the only types that cross layer boundaries.
│   │
│   ├── services/
│   │   └── energy_service.py    ← Core business logic: input validation, cache coordination,
│   │                               energy calculation (size × 4.56 KWh), CO₂ conversion,
│   │                               daily aggregation, deduplication of wallet transactions
│   │
│   └── utils/
│       └── cache.py             ← Generic in-process TTL cache (TTLCache[T]). O(1) get/set,
│                                   lazy expiry on read, not thread-safe (safe for asyncio)
│
├── tests/
│   ├── conftest.py              ← Shared fixtures: make_http_getter, make_service;
│   │                               longest-key-wins stub matcher to avoid prefix collisions
│   ├── test_cache.py            ← TTLCache: set/get round-trips, expiry, overwrite, TTL=0
│   ├── test_validation.py       ← All _validate_* helpers and _energy_for_size boundary values
│   ├── test_energy_service.py   ← EnergyService integration tests: CO₂ fields, caching,
│   │                               deduplication, empty blocks, skipped transactions
│   ├── test_blockchain_client.py← BlockchainClient: pagination order, day bucketing,
│   │                               string-JSON branch, height resolution, error paths
│   ├── test_schema.py           ← All four GraphQL resolvers + all three DTO mappers;
│   │                               verifies error wrapping (ValidationError → ValueError)
│   └── test_main.py             ← FastAPI layer: /health, GET /graphql (HTML), POST /graphql
│                                   (introspection, validation errors, malformed JSON, CORS)
│
└── docs/
    ├── architecture.md          ← Layer diagram, class relationships, design principles
    ├── system-architecture.md   ← Request lifecycle, deployment view, caching strategy
    ├── data-flow.md             ← Mermaid sequence diagrams for all four query paths
    ├── edge-cases.md            ← Decision flowchart, validation rules, failure-mode table
    ├── considerations.md        ← Design decisions, constraints, API choice, and trade-off analysis
    └── images/
        ├── block-energy-breakdown.png  ← GraphiQL screenshot: block query result
        ├── daily-energy-summary.png    ← GraphiQL screenshot: daily aggregation result
        └── demo-cli-overview.png       ← Terminal screenshot: demo.sh menu in action
```
