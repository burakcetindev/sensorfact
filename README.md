# Bitcoin Energy Consumption API

A GraphQL API for monitoring Bitcoin network energy consumption, built with Python.

## Stack

| Component | Role |
|---|---|
| **Python 3.12+** | Language runtime |
| **FastAPI** | HTTP server, health endpoint, GraphiQL serving |
| **Ariadne** | Schema-first GraphQL (SDL → resolvers) |
| **httpx** | Async HTTP client with automatic redirect following |
| **mempool.space** | Live Bitcoin blockchain data source (public REST API) |
| **TTLCache** | In-process per-entity time-to-live cache |

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
| `docs/images/` | Screenshots of the GraphiQL UI and demo CLI in action |
