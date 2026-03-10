from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from ariadne import graphql as run_graphql

from src.api.schema import build_schema, build_service

# GraphiQL 3 — served from CDN; works in any modern browser with no build step
_GRAPHIQL_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Bitcoin Energy API — GraphiQL</title>
  <link rel="stylesheet" href="https://unpkg.com/graphiql@3/graphiql.min.css" />
  <style>
    body { margin: 0; background: #0d1117; }
    #graphiql { height: 100vh; }
  </style>
</head>
<body>
  <div id="graphiql">Loading GraphiQL...</div>
  <script src="https://unpkg.com/react@18/umd/react.production.min.js"></script>
  <script src="https://unpkg.com/react-dom@18/umd/react-dom.production.min.js"></script>
  <script src="https://unpkg.com/graphiql@3/graphiql.min.js" type="application/javascript"></script>
  <script>
    const fetcher = GraphiQL.createFetcher({ url: '/graphql' });
    const root = ReactDOM.createRoot(document.getElementById('graphiql'));
    root.render(React.createElement(GraphiQL, {
      fetcher,
      defaultEditorToolsVisibility: true,
      defaultQuery: `# Bitcoin Energy API — GraphiQL Explorer
# ─────────────────────────────────────────────────────────
# Run any query below using the ▶ button (or Ctrl+Enter).
# Use latestBlock first to grab a real block hash or height.

# 1. Get the current latest block (hash + height)
query LatestBlock {
  latestBlock {
    hash
    height
  }
}

# 2. Energy breakdown for a block
#    Paste the hash from LatestBlock above, or use a height like "940137"
query BlockEnergy {
  energyPerTransactionForBlock(
    blockIdentifier: "940137"
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

# 3. Total energy consumed day-by-day over the last N days
query DailyEnergy {
  totalEnergyConsumptionLastDays(days: 3) {
    date
    blockCount
    transactionCount
    totalEnergyKwh
  }
}

# 4. Total energy for a wallet address
#    Using Satoshi Nakamoto's genesis wallet as an example
query WalletEnergy {
  totalEnergyByWalletAddress(
    address: "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"
  ) {
    address
    transactionCount
    totalEnergyKwh
  }
}
`
    }));
  </script>
</body>
</html>
"""


schema = build_schema()
service = build_service()

app = FastAPI(title="Sensorfact Bitcoin Energy API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


@app.get("/graphql", response_class=HTMLResponse)
async def graphql_playground():
    """Serve GraphiQL for interactive browser testing."""
    return HTMLResponse(_GRAPHIQL_HTML)


@app.post("/graphql")
async def graphql_endpoint(request: Request):
    """Execute GraphQL queries against the Bitcoin energy API."""
    data = await request.json()
    context = {"energy_service": service}
    success, result = await run_graphql(schema, data, context_value=context)
    return JSONResponse(result, status_code=200 if success else 400)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
