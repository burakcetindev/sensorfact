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
      defaultQuery: `# Bitcoin Energy API
# ─────────────────────────────────────────────────────────
# MANDATORY 1: Energy breakdown for a specific block
# Replace the hash below with any real block hash

query BlockEnergy {
  energyPerTransactionForBlock(
    blockIdentifier: "PASTE_A_BLOCK_HASH_HERE"
  ) {
    blockHash
    blockHeight
    transactionCount
    totalEnergyKwh
    transactions {
      hash
      sizeBytes
      energyKwh
    }
  }
}

# MANDATORY 2: Daily energy consumption (last 3 days)

query DailyEnergy {
  totalEnergyConsumptionLastDays(days: 3) {
    date
    blockCount
    transactionCount
    totalEnergyKwh
  }
}

# OPTIONAL: Wallet energy footprint

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
