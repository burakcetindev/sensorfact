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
      defaultQuery: `# ── 1. Block energy breakdown ─────────────────────────────────────────────────
# Small early blocks (1–2 transactions) return in under 5 seconds.
# Pick any hash below and press ▶ (or Ctrl+Enter) to run.
#
#  Block 1    – 00000000839a8e6886ab5951d76f411475428afc90947ee320161bbf18eb6048
#  Block 170  – 00000000d1145790a8694403d4063f323d499e655c83426834d4ce2f8dd4a2ee
#  Block 1000 – 00000000c937983704a73af28acdec37b049d214adbda81d7e2a3dd146f6ed09

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

# ── 2. Daily energy summary ────────────────────────────────────────────────────
# days: 1 is fast (~10 s).  Increase to 2–3 for more history (30–60 s).

query DailyEnergy {
  totalEnergyConsumptionLastDays(days: 1) {
    date
    blockCount
    transactionCount
    totalEnergyKwh
  }
}

# ── 3. Latest block ────────────────────────────────────────────────────────────
# Grab the current tip hash/height to use in BlockEnergy above.

query LatestBlock {
  latestBlock {
    hash
    height
  }
}

# ── 4. Wallet energy footprint ────────────────────────────────────────────────
# Satoshi Nakamoto's genesis wallet (block 0, Jan 3 2009).

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
    """Execute a GraphQL query or mutation.

    Reads the JSON body, injects ``energy_service`` into the Ariadne context,
    and returns the result with status 200 on success or 400 on a parse error.
    Validation and resolver errors are returned as structured GraphQL
    ``errors[]`` within a 200 response body.  A malformed (non-JSON) request
    body returns a 400 with a descriptive error rather than a 500.
    """
    try:
        data = await request.json()
    except Exception:
        return JSONResponse(
            {"errors": [{"message": "Request body is not valid JSON."}]},
            status_code=400,
        )
    context = {"energy_service": service}
    success, result = await run_graphql(schema, data, context_value=context)
    return JSONResponse(result, status_code=200 if success else 400)


@app.get("/health")
async def health() -> dict[str, str]:
    """Return a simple liveness probe.

    Returns ``{"status": "ok"}`` whenever the process is running.  Used by
    the demo script and monitoring tools to confirm the server is up before
    sending GraphQL queries.
    """
    return {"status": "ok"}
