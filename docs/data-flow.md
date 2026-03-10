# Data Flow Diagrams

All diagrams render in GitHub, GitLab, and VS Code with the [Markdown Preview Mermaid Support](https://marketplace.visualstudio.com/items?itemName=bierner.markdown-mermaid) extension.

See `docs/images/` for screenshots of real query runs.

---

## 1 — `energyPerTransactionForBlock`

Transaction pages are fetched **concurrently** (bounded by `asyncio.Semaphore(5)`).
A cold-cache query for a modern block (~2500 transactions = 100 API pages) completes
in ~5–10 s instead of the ~60 s it took with sequential paging.

```mermaid
sequenceDiagram
    autonumber
    actor Client as Browser / curl
    participant GQL  as GraphQL Resolver
    participant SVC  as EnergyService
    participant CAC  as TTL Block Cache (15 min)
    participant CLI  as BlockchainClient
    participant API  as mempool.space

    Client->>GQL: POST /graphql energyPerTransactionForBlock(blockIdentifier)
    GQL->>SVC: energy_per_transaction_for_block(blockIdentifier)
    SVC->>SVC: validate — non-empty, strip whitespace
    SVC->>CAC: get(blockIdentifier)
    alt Cache HIT
        CAC-->>SVC: cached block payload (tx list already present)
    else Cache MISS
        CAC-->>SVC: nil
        SVC->>CLI: get_block_by_hash(blockIdentifier)
        Note over CLI: If numeric, resolve height → hash via GET /api/block-height/{n}
        CLI->>API: GET /api/block/{hash}  (metadata)
        API-->>CLI: {id, height, tx_count, ...}
        Note over CLI: All tx pages fired concurrently under Semaphore(5)
        par page 0
            CLI->>API: GET /api/block/{hash}/txs
            API-->>CLI: [{txid, size}, ...] page 0
        and page 25
            CLI->>API: GET /api/block/{hash}/txs/25
            API-->>CLI: [{txid, size}, ...] page 25
        and page N
            CLI->>API: GET /api/block/{hash}/txs/N
            API-->>CLI: [{txid, size}, ...] page N
        end
        CLI-->>SVC: {hash, height, tx: [{hash, size}, ...]}
        SVC->>CAC: set(hash, block)
    end
    loop for each tx in block.tx
        SVC->>SVC: energy_kwh = size_bytes × 4.56
    end
    SVC-->>GQL: BlockEnergySummary
    GQL-->>Client: {blockHash, blockHeight, transactionCount, totalEnergyKwh, transactions[]}
```

---

## 2 — `totalEnergyConsumptionLastDays`

All requested days are collected in a **single backwards walk** from the chain tip.
Previously N days required N separate walks (each starting from the tip), causing
O(N²) API calls and timeouts for `days > 1`.

```mermaid
sequenceDiagram
    autonumber
    actor Client as Browser / curl
    participant GQL  as GraphQL Resolver
    participant SVC  as EnergyService
    participant DCAC as TTL Day Cache (5 min)
    participant CLI  as BlockchainClient
    participant API  as mempool.space

    Client->>GQL: POST /graphql totalEnergyConsumptionLastDays(days: N)
    GQL->>SVC: total_energy_consumption_last_days(N)
    SVC->>SVC: validate 1 <= days <= 60
    SVC->>DCAC: get(date) for each of N dates
    alt All N dates cached
        DCAC-->>SVC: N × DailyEnergySummary
    else Some or all dates uncached
        SVC->>CLI: get_blocks_for_days([day_0, day_1, ..., day_N])
        CLI->>API: GET /api/blocks/tip/height
        API-->>CLI: current_height
        loop walk backwards in chunks of 10 (single pass for all days)
            CLI->>API: GET /api/blocks/{chunk_start_height}
            API-->>CLI: [{id, timestamp, size, tx_count}, ...] up to 10 blocks
            Note over CLI: Each block bucketed into its UTC day
            Note over CLI: Stop when chunk_min_timestamp < earliest requested day
            CLI->>CLI: asyncio.sleep(0.25) — gentle pacing
        end
        CLI-->>SVC: {"2026-03-10": [...], "2026-03-09": [...], ...}
        loop for each uncached date
            SVC->>SVC: sum block.size values → total_energy_kwh
            Note over SVC: Block-level size avoids fetching ~80 tx pages per block
            SVC->>DCAC: set(date, DailyEnergySummary)
        end
    end
    SVC-->>GQL: list[DailyEnergySummary] sorted by date asc
    GQL-->>Client: [{date, blockCount, transactionCount, totalEnergyKwh}, ...]
```

---

## 3 — `totalEnergyByWalletAddress`

```mermaid
sequenceDiagram
    autonumber
    actor Client as Browser / curl
    participant GQL  as GraphQL Resolver
    participant SVC  as EnergyService
    participant CLI  as BlockchainClient
    participant API  as mempool.space

    Client->>GQL: POST /graphql totalEnergyByWalletAddress(address)
    GQL->>SVC: total_energy_by_wallet_address(address)
    SVC->>SVC: validate — non-empty address
    SVC->>CLI: get_wallet_transactions(address)
    CLI->>API: GET /api/address/{address}/txs
    Note over API: Returns up to 50 most recent confirmed txs
    API-->>CLI: [{txid, size, ...}]
    CLI-->>SVC: {txs: [{hash, size}]}
    loop for each tx
        SVC->>SVC: total_energy_kwh += size_bytes × 4.56
    end
    SVC-->>GQL: WalletEnergySummary
    GQL-->>Client: {address, transactionCount, totalEnergyKwh}
```

---

## 4 — Error and retry flow

Every outbound HTTP call in `BlockchainClient._get` follows this path:

```mermaid
flowchart TD
    A([Outbound GET request]) --> B{HTTP status}
    B -- 200 + JSON --> C{Payload shape expected?}
    C -- Yes --> K([Return to caller])
    C -- No / JSONDecodeError --> E
    B -- 429 Rate Limit --> R1[Sleep rate_limit_backoff_seconds\nstarts at 5 s, doubles each retry]
    B -- 404 Not Found --> NF[Raise NotFoundError\nno retry]
    B -- 5xx / network error --> E[Retry with exponential backoff\nstarts at 0.5 s, doubles each retry]
    R1 --> AT{Attempt <= max_retries?}
    E --> AT
    AT -- Yes --> A
    AT -- No / exhausted --> ERR[Raise BlockchainClientError\nGraphQL errors[] surface to client]
```

| Error type | Initial backoff | Max attempts |
|---|---|---|
| Network / 5xx | 0.5 s (doubles per retry) | 4 |
| HTTP 429 rate limit | 5.0 s (doubles per retry) | 4 |
| HTTP 404 | — | No retry |
