# Edge Cases

## Decision map

```mermaid
flowchart TD
    A([Request arrives]) --> B{Input validation}

    B -->|empty blockIdentifier| E1[ValidationError: identifier cannot be empty]
    B -->|days <= 0| E2[ValidationError: must be > 0]
    B -->|days > 60| E3[ValidationError: max 60 to protect API limits]
    B -->|empty address| E4[ValidationError: address cannot be empty]
    B -->|valid| C[Fetch from blockchain.com]

    C --> D{API response}
    D -->|429 Rate Limit| R[Retry with exponential backoff\nmax 4 attempts]
    R -->|success| F[Process response]
    R -->|exhausted| ERR[BlockchainClientError in GraphQL errors[]]
    D -->|404 Not Found| NF[NotFoundError -- no retry]
    D -->|HTML body| JD[JSONDecodeError -> BlockchainClientError -> retry]
    D -->|200 wrong type| WT[BlockchainClientError: unexpected payload type]
    D -->|200 valid JSON| F

    F --> G{Data quality}
    G -->|tx missing hash or size| SK[Row skipped silently]
    G -->|negative tx size| E5[ValidationError: size cannot be negative]
    G -->|duplicate wallet tx hash| DD[Deduplicated -- counted once]
    G -->|clean| H([Compute energy and return])
```

---

## Detailed breakdown

### Input validation guards

| Input | Rule | Error raised |
|---|---|---|
| `blockIdentifier` | Must be non-empty after strip | `ValidationError` |
| `days` | `1 ≤ days ≤ 60` | `ValidationError` |
| `address` | Must be non-empty after strip | `ValidationError` |
| Transaction `size` | Must be `>= 0` | `ValidationError` |

### External API failures

| Scenario | Handling |
|---|---|
| 429 rate-limit | Exponential backoff retry (4 max) |
| 404 not found | Immediate `NotFoundError`, no retry |
| 5xx server error | Retry with backoff |
| Network timeout | `httpx.TimeoutException` caught → retry |
| HTML response body | `JSONDecodeError` caught → `BlockchainClientError` → retry |
| Array vs dict response | `get_blocks_by_day` handles both formats |

### Data inconsistencies

| Scenario | Handling |
|---|---|
| Missing tx `hash` or `size` field | Row skipped, others processed |
| Duplicate tx hashes in wallet | Deduplicated with a `set` before fetching |
| Block with empty `tx[]` | Returns `transactionCount: 0, totalEnergyKwh: 0` |

### Performance safeguards

| Mechanism | Detail |
|---|---|
| `asyncio.Semaphore(8)` | Caps concurrent blockchain requests per query |
| TTL block cache (15 min) | Avoids re-fetching the same block |
| TTL tx cache (15 min) | Avoids re-fetching the same transaction |
| TTL day cache (5 min) | Daily summaries are re-used within a session |
| `days ≤ 60` guard | Hard limit to avoid unbounded fan-out |
