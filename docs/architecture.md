# Architecture

## Layer diagram

```mermaid
flowchart TB
    subgraph Presentation["Presentation Layer"]
        P1[FastAPI app -- src/main.py]
        P2[GraphQL Playground -- GET /graphql]
        P3[Health endpoint -- GET /health]
    end
    subgraph API["API Layer -- src/api/schema.py"]
        A1[Ariadne GraphQL SDL type_defs]
        A2[Query resolvers: block / daily / wallet]
        A3[DTO mappers: domain to dict]
    end
    subgraph Service["Service Layer -- src/services/energy_service.py"]
        S1[EnergyService]
        S2[Input validation]
        S3[Energy calc: size x 4.56 KWh]
        S4[asyncio.gather + semaphore]
    end
    subgraph Client["Integration Layer -- src/clients/blockchain_client.py"]
        C1[BlockchainClient]
        C2[Retry + exponential backoff]
        C3[JSON decode guard]
        C4[Dict and List normalisation]
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
        +get_transaction(hash) dict
        +get_wallet_transactions(addr) dict
        -_request(path) Any
        -_request_dict(path) dict
    }
    class EnergyService {
        -_client BlockchainClient
        -_block_cache TTLCache
        -_tx_cache TTLCache
        -_daily_cache TTLCache
        -_semaphore Semaphore
        +energy_per_transaction_for_block(id) BlockEnergySummary
        +total_energy_consumption_last_days(n) list
        +total_energy_by_wallet_address(addr) WalletEnergySummary
        -_energy_for_size(bytes) float
        -_get_block_cached(hash) dict
        -_daily_energy_for_date(dt) DailyEnergySummary
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
    EnergyService --> TTLCache : block / tx / day caches
    EnergyService --> BlockEnergySummary : returns
    EnergyService --> DailyEnergySummary : returns
    EnergyService --> WalletEnergySummary : returns
    BlockEnergySummary --> TransactionEnergy : contains
```

---

## OOP principles applied

| Principle | Where |
|---|---|
| Single Responsibility | `BlockchainClient` owns HTTP; `EnergyService` owns business logic |
| Open/Closed | New data sources swap by replacing `BlockchainClient`; no service change needed |
| Dependency Inversion | `EnergyService` receives `BlockchainClient` via constructor |
| Encapsulation | Cache state is private; only typed domain objects cross layer boundaries |
| Generic typing | `TTLCache[T]` reused for blocks, transactions, and day summaries |

---

## Scaling path

```mermaid
flowchart LR
    subgraph Now["Current: single process"]
        A[FastAPI async] --> B[EnergyService + in-memory TTL cache]
        B --> C[blockchain.com]
    end
    subgraph Next["Scale-out path"]
        D[FastAPI + Load Balancer] --> E[EnergyService + Redis shared cache]
        E --> F[Rate-limiter middleware]
        F --> G[blockchain.com]
    end
    Now -.->|replace TTLCache implementation| Next
```
