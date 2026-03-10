# Data Flow Diagrams

All diagrams render in GitHub, GitLab, and VS Code with the [Markdown Preview Mermaid Support](https://marketplace.visualstudio.com/items?itemName=bierner.markdown-mermaid) extension.

---

## 1 — `energyPerTransactionForBlock`

```mermaid
sequenceDiagram
    autonumber
    actor Client as Browser / curl
    participant GQL  as GraphQL Resolver
    participant SVC  as EnergyService
    participant CAC  as TTL Block Cache
    participant API  as blockchain.com

    Client->>GQL: POST /graphql energyPerTransactionForBlock(blockIdentifier)
    GQL->>SVC: energy_per_transaction_for_block(blockIdentifier)
    SVC->>SVC: validate — non-empty identifier
    SVC->>CAC: get(blockHash)
    alt Cache HIT (TTL 15 min)
        CAC-->>SVC: cached block payload
    else Cache MISS
        CAC-->>SVC: nil
        SVC->>API: GET /rawblock/{blockHash}
        API-->>SVC: JSON block with tx[]
        SVC->>CAC: set(blockHash, block)
    end
    loop each tx in block.tx[]
        SVC->>SVC: energy_kwh = size_bytes x 4.56 KWh
    end
    SVC-->>GQL: BlockEnergySummary
    GQL-->>Client: blockHash, transactionCount, totalEnergyKwh, transactions[]
```

---

## 2 — `totalEnergyConsumptionLastDays`

```mermaid
sequenceDiagram
    autonumber
    actor Client as Browser / curl
    participant GQL  as GraphQL Resolver
    participant SVC  as EnergyService
    participant DCAC as TTL Day Cache
    participant BCAC as TTL Block Cache
    participant API  as blockchain.com

    Client->>GQL: POST /graphql totalEnergyConsumptionLastDays(days: N)
    GQL->>SVC: total_energy_consumption_last_days(N)
    SVC->>SVC: validate 1 <= days <= 60
    Note over SVC: asyncio.gather — all N days run concurrently
    loop for each UTC day D (concurrent)
        SVC->>DCAC: get(date)
        alt Day cache HIT (TTL 5 min)
            DCAC-->>SVC: DailyEnergySummary
        else Day cache MISS
            SVC->>API: GET /blocks/{day_epoch_ms}?format=json
            Note over API: Returns raw JSON array of block summaries
            API-->>SVC: [{hash, time, height, ...}, ...]
            Note over SVC: asyncio.gather, semaphore <= 8 concurrent
            loop for each block hash
                SVC->>BCAC: get(blockHash)
                alt Block cache HIT
                    BCAC-->>SVC: block payload
                else Block cache MISS
                    SVC->>API: GET /rawblock/{hash}
                    Note over API: 4x retry exponential backoff on 429/5xx
                    API-->>SVC: JSON block
                    SVC->>BCAC: set(blockHash, block)
                end
                SVC->>SVC: sum tx sizes to daily_energy_kwh
            end
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
    participant TCAC as TTL TX Cache
    participant API  as blockchain.com

    Client->>GQL: POST /graphql totalEnergyByWalletAddress(address)
    GQL->>SVC: total_energy_by_wallet_address(address)
    SVC->>SVC: validate — non-empty address
    SVC->>API: GET /rawaddr/{address}
    API-->>SVC: { txs: [{hash, size, ...}] }
    loop for each tx (deduplicated by hash)
        SVC->>TCAC: get(txHash)
        alt TX cache HIT (TTL 15 min)
            TCAC-->>SVC: cached tx
        else TX cache MISS
            SVC->>API: GET /rawtx/{txHash}
            API-->>SVC: JSON tx
            SVC->>TCAC: set(txHash, tx)
        end
        SVC->>SVC: total_energy_kwh += size_bytes x 4.56
    end
    SVC-->>GQL: WalletEnergySummary
    GQL-->>Client: { address, transactionCount, totalEnergyKwh }
```

---

## 4 — Error handling flow

```mermaid
flowchart TD
    A([Incoming GraphQL request]) --> B{Input valid?}
    B -- No --> C[ValidationError in GraphQL errors[]]
    B -- Yes --> D[BlockchainClient._request]
    D --> E{HTTP response status}
    E -- 200 and valid JSON --> F{Payload type correct?}
    F -- Yes --> K([Return data to resolver])
    F -- No --> L[BlockchainClientError]
    E -- 200 but HTML body --> M[JSONDecodeError to BlockchainClientError]
    E -- 429 Rate Limit --> G[Sleep and retry max 4 attempts exponential backoff]
    G -- retry succeeds --> K
    G -- attempts exhausted --> H[BlockchainClientError in GraphQL errors[]]
    E -- 404 Not Found --> I[NotFoundError no retry immediate]
    E -- 5xx or network error --> G
    L --> G
    M --> G
```
