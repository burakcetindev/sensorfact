# Architecture

## Layer diagram

```mermaid
flowchart TB
    subgraph Presentation["Presentation Layer"]
        P1[FastAPI app -- src/main.py]
        P2[GraphiQL IDE -- GET /graphql]
        P3[Health endpoint -- GET /health]
    end
    subgraph API["API Layer -- src/api/schema.py"]
        A1[Ariadne GraphQL SDL type_defs]
        A2[Query resolvers: block / daily / wallet]
        A3[DTO mappers: domain models to dicts]
    end
    subgraph Service["Service Layer -- src/services/energy_service.py"]
        S1[EnergyService]
        S2[Input validation]
        S3[Energy calc: size_bytes x 4.56 KWh]
        S4[Single-pass multi-day walk]
        S5[TTL cache look-up and fill]
    end
    subgraph Client["Integration Layer -- src/clients/blockchain_client.py"]
        C1[BlockchainClient]
        C2[Parallel tx-page fetching with semaphore]
        C3[Single-pass get_blocks_for_days]
        C4[Retry + exponential backoff]
        C5[JSON decode guard and dict normalisation]
    end
    subgraph Cross["Cross-cutting"]
        X1[TTLCache -- src/utils/cache.py]
        X2[Settings -- src/config/settings.py]
    end
    subgraph Domain["Domain -- src/domain/models.py"]
        D1[BlockEnergySummary]
        D2[DailyEnergySummary]
        D3[WalletEnergySummary]
        D4[TransactionEnergy]
    end
    Presentation --> API
    API --> Service
    Service --> Client
    Service --> Cross
    Client --> Cross
    Service --> Domain
    API --> Domain
```

---

## Class relationships

```mermaid
classDiagram
    class BlockchainClient {
        +get_latest_block() dict
        +get_block_by_hash(hash) dict
        +get_blocks_by_day(datetime) list
        +get_blocks_for_days(list~datetime~) dict
        +get_transaction(hash) dict
        +get_wallet_transactions(addr) dict
        -_get(path) Any
        -_get_json(path) Any
        -_get_block_txs(hash, tx_count) list
    }
    class EnergyService {
        -_client BlockchainClient
        -_block_cache TTLCache
        -_daily_cache TTLCache
        +energy_per_transaction_for_block(id) BlockEnergySummary
        +total_energy_consumption_last_days(n) list
        +total_energy_by_wallet_address(addr) WalletEnergySummary
        -_energy_for_size(bytes) float
        -_get_block_cached(hash) dict
    }
    class TTLCache~T~ {
        -_store dict
        -_ttl_seconds int
        +get(key) T or None
        +set(key, value) void
    }
    class BlockEnergySummary {
        +block_hash str
        +block_height int or None
        +transaction_count int
        +total_energy_kwh float
        +energy_per_transaction_kwh float
        +transactions list~TransactionEnergy~
    }
    class TransactionEnergy {
        +hash str
        +size_bytes int
        +energy_kwh float
    }
    class DailyEnergySummary {
        +date str
        +block_count int
        +transaction_count int
        +total_energy_kwh float
    }
    class WalletEnergySummary {
        +address str
        +transaction_count int
        +total_energy_kwh float
    }
    EnergyService --> BlockchainClient : uses
    EnergyService --> TTLCache : block cache / day cache
    EnergyService --> BlockEnergySummary : returns
    EnergyService --> DailyEnergySummary : returns
    EnergyService --> WalletEnergySummary : returns
    BlockEnergySummary --> TransactionEnergy : contains
```

---

## OOP principles applied

| Principle | Where |
|---|---|
| Single Responsibility | `BlockchainClient` owns all HTTP I/O; `EnergyService` owns all business logic and validation |
| Open/Closed | Swap data sources by replacing `BlockchainClient` (e.g. from mempool.space to a different provider); `EnergyService` never changes |
| Dependency Inversion | `EnergyService` receives a `BlockchainClient` instance via constructor injection; testable with a fake/stub |
| Encapsulation | Cache state is private (`_block_cache`, `_daily_cache`); only typed domain objects cross layer boundaries |
| Generic typing | `TTLCache[T]` is reused for blocks and daily summaries with full type safety |

---

## Key performance decisions

### 1. Parallel transaction-page fetching

The mempool.space API paginates block transactions in pages of 25. A modern
Bitcoin block (~2500 txs) requires 100 pages. Fetching them sequentially with a
pacing delay took ~60 s. All pages are now fetched concurrently under an
`asyncio.Semaphore(max_parallel_requests)`, reducing this to ~5–10 s.

```
Before:  page 0 → sleep → page 25 → sleep → ... (sequential, O(pages × latency))
After:   [page 0, page 25, page 50, ...] all concurrent, semaphore-bounded
```

### 2. Single-pass multi-day block walk

The daily energy query previously called `get_blocks_by_day` once per day, each
starting a fresh backwards walk from the chain tip:

```
days=3:  walk tip → day 0  (full walk)
         walk tip → day 1  (full walk again)
         walk tip → day 2  (full walk again)
         Total API calls ≈ 3 × (blocks_to_cover / 10) = O(N²)
```

The new `get_blocks_for_days` method does a **single walk**, partitioning blocks
into all requested day-buckets as it goes:

```
days=3:  walk tip → earliest day  (one walk)
         bucket blocks by UTC day as we go
         Total API calls ≈ blocks_to_cover / 10 = O(N)
```

This eliminates the timeout that occurred with `days > 1` on a cold cache.

---

## Scaling path

```mermaid
flowchart LR
    subgraph Now["Current: single process"]
        A[FastAPI async] --> B[EnergyService + in-memory TTL cache]
        B --> C[mempool.space]
    end
    subgraph Next["Scale-out path"]
        D[FastAPI + Load Balancer] --> E[EnergyService + Redis shared cache]
        E --> F[Rate-limiter / queue middleware]
        F --> G[mempool.space or self-hosted node]
    end
    Now -.->|replace TTLCache with Redis adapter| Next
```
