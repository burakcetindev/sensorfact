# Sensorfact Backend Integration Assignment — Python Solution

A GraphQL API for monitoring Bitcoin network energy consumption, built with Python.

## Stack

- **Python 3.12+**
- **FastAPI** — HTTP server
- **Ariadne** — schema-first GraphQL
- **httpx** — async HTTP with retry/backoff
- **TTL caching** — avoids redundant API calls
- **mempool.space** — live Bitcoin blockchain data source

## Requirements coverage

| Requirement | Query | Status |
|---|---|---|
| Energy per transaction for a specific block | `energyPerTransactionForBlock` | ✅ Mandatory |
| Total energy per day over last X days | `totalEnergyConsumptionLastDays` | ✅ Mandatory |
| Caching to reduce duplicate API calls | TTLCache on blocks + daily summaries | ✅ Optional |
| Total energy for a wallet address | `totalEnergyByWalletAddress` | ✅ Optional |

## Run

```bash
./scripts/build.sh
./scripts/start.sh
```

GraphQL endpoint: `http://localhost:4000/graphql`  
Health endpoint: `http://localhost:4000/health`  
GraphiQL IDE: open `http://localhost:4000/graphql` in a browser

## Interactive demo

```bash
./scripts/demo.sh
```

A menu-driven CLI that walks through all API features with real live data.

## GraphQL examples

### Latest block info
```graphql
query {
  latestBlock {
    hash
    height
  }
}
```

### Energy per transaction for a block
```graphql
query {
  energyPerTransactionForBlock(blockIdentifier: "940137") {
    blockHash
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

You can pass a block hash or a block height as `blockIdentifier`.

### Total energy over the last N days
```graphql
query {
  totalEnergyConsumptionLastDays(days: 3) {
    date
    blockCount
    transactionCount
    totalEnergyKwh
  }
}
```

### Energy for a wallet address
```graphql
query {
  totalEnergyByWalletAddress(address: "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa") {
    address
    transactionCount
    totalEnergyKwh
  }
}
```

## Energy model

Energy is estimated as:

```
energy_kwh = transaction_size_bytes × 4.56
```

## Documentation

Detailed docs are in `docs/`:

- `docs/architecture.md`
- `docs/system-architecture.md`
- `docs/data-flow.md`
- `docs/edge-cases.md`
