#!/usr/bin/env bash
# =============================================================================
# Bitcoin Energy API — Interactive Demo
# =============================================================================

set -uo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="$ROOT_DIR/.venv"
API_URL="http://localhost:4000"
GRAPHQL_URL="$API_URL/graphql"
SERVER_PID_FILE="/tmp/sensorfact_demo.pid"

R="\033[0m"; BOLD="\033[1m"; DIM="\033[2m"
CYAN="\033[36m"; GREEN="\033[32m"; YELLOW="\033[33m"
MAGENTA="\033[35m"; BLUE="\033[34m"; WHITE="\033[97m"

h1()   { echo -e "\n${BOLD}${CYAN}$1${R}\n"; }
h2()   { echo -e "${BOLD}${WHITE}$1${R}"; }
ok()   { echo -e "${GREEN}  ✓  $1${R}"; }
run()  { echo -e "${YELLOW}  →  $1${R}"; }
note() { echo -e "${DIM}      $1${R}"; }
warn() { echo -e "${YELLOW}  ⚠  $1${R}"; }
sep()  { echo -e "${DIM}  ────────────────────────────────────────────────────${R}"; }

pretty_json() {
  if command -v jq &>/dev/null; then
    jq -C '.'
  else
    python3 -c "import sys,json; print(json.dumps(json.load(sys.stdin), indent=2))"
  fi
}

gql() {
  local query="$1"; local timeout="${2:-120}"
  curl -s --max-time "$timeout" -X POST "$GRAPHQL_URL" \
    -H "Content-Type: application/json" \
    -d "{\"query\":\"$query\"}"
}

show_result() {
  local response="$1"
  echo ""
  echo "$response" | pretty_json | sed 's/^/      /'
  echo ""
  if echo "$response" | grep -q '"errors"'; then
    warn "The API returned a structured error (expected behavior, shown above)"
  else
    ok "Request completed successfully"
  fi
}

server_running() { curl -sf "$API_URL/health" > /dev/null 2>&1; }

wait_for_server() {
  for i in $(seq 1 30); do
    server_running && ok "Server is ready at $API_URL" && return 0
    echo -ne "${DIM}      Starting up... (${i}/30)\r${R}"; sleep 1
  done
  echo "Server failed to start."; exit 1
}

ensure_server() {
  if server_running; then
    ok "Server is already running at $API_URL"
    return
  fi
  run "Starting server..."
  [[ -d "$VENV_DIR" ]] || "$ROOT_DIR/scripts/build.sh"
  source "$VENV_DIR/bin/activate"
  export PYTHONPATH="$ROOT_DIR"
  "$VENV_DIR/bin/uvicorn" src.main:app \
    --host 0.0.0.0 --port 4000 --log-level warning \
    > /tmp/sensorfact_demo_server.log 2>&1 &
  echo $! > "$SERVER_PID_FILE"
  wait_for_server
}

stop_server() {
  [[ -f "$SERVER_PID_FILE" ]] || return
  local pid; pid=$(cat "$SERVER_PID_FILE")
  kill -0 "$pid" 2>/dev/null && kill "$pid" 2>/dev/null || true
  rm -f "$SERVER_PID_FILE"
}

trap stop_server EXIT

# ── screens ───────────────────────────────────────────────────────────────────

screen_block() {
  h1 "Energy consumption for a Bitcoin block"
  note "Each transaction in a block consumes energy proportional to its size."
  note "Formula: energy_kwh = transaction_size_bytes × 4.56"
  echo ""

  h2 "  Enter a block hash or height:"
  note "(press Enter to use the current latest block)"
  echo -ne "\n  ${CYAN}>${R} "; read -r BLOCK_ID

  if [[ -z "$BLOCK_ID" ]]; then
    run "Fetching the latest block..."
    LATEST_R=$(gql "query { latestBlock { hash height } }" 30)
    BLOCK_ID=$(echo "$LATEST_R" | python3 -c "import sys,json; print(json.load(sys.stdin)['data']['latestBlock']['hash'])" 2>/dev/null || true)
    HEIGHT=$(echo   "$LATEST_R" | python3 -c "import sys,json; print(json.load(sys.stdin)['data']['latestBlock']['height'])" 2>/dev/null || true)

    if [[ -z "$BLOCK_ID" ]]; then
      warn "Could not fetch the latest block automatically."
      h2 "  Please paste a block hash:"
      note "e.g. 00000000000000000002f5a..."
      echo -ne "\n  ${CYAN}>${R} "; read -r BLOCK_ID
      [[ -z "$BLOCK_ID" ]] && warn "Nothing entered — returning to menu." && return
    else
      ok "Latest block  height: $HEIGHT"
      note "hash: $BLOCK_ID"
    fi
  fi

  echo ""
  run "Querying energy breakdown for block $BLOCK_ID..."
  note "Fetching all transactions from mempool.space — this takes a few seconds"
  echo ""

  Q="query { energyPerTransactionForBlock(blockIdentifier: \\\"$BLOCK_ID\\\") { blockHash blockHeight transactionCount totalEnergyKwh energyPerTransactionKwh transactions { hash sizeBytes energyKwh } } }"
  RESP=$(gql "$Q" 120)
  show_result "$RESP"

  echo "$RESP" | python3 -c "
import sys, json
d = json.load(sys.stdin)
if 'errors' in d: exit(0)
b = d['data']['energyPerTransactionForBlock']
print('  Block height        :', b['blockHeight'])
print('  Transactions        :', b['transactionCount'])
print('  Total energy        : {:,.2f} KWh'.format(b['totalEnergyKwh']))
print('  Avg energy per tx   : {:,.4f} KWh'.format(b['energyPerTransactionKwh']))
txs = sorted(b['transactions'], key=lambda t: t['sizeBytes'], reverse=True)[:3]
if txs:
    print()
    print('  Largest 3 transactions:')
    for tx in txs:
        print('  {:.<50s}  {:>7,} bytes   {:>12,.4f} KWh'.format(
            tx['hash'][:46] + '..', tx['sizeBytes'], tx['energyKwh']))
" 2>/dev/null || true
}

screen_daily() {
  h1 "Daily energy consumption over the last N days"
  note "Aggregates every block and transaction for each day."
  note "The more days you request, the longer this takes (~20-60s per day)."
  echo ""

  h2 "  How many days would you like to query? (1–60)"
  note "(press Enter for 3 days)"
  echo -ne "\n  ${CYAN}>${R} "; read -r DAYS; DAYS=${DAYS:-3}

  echo ""
  run "Querying daily energy for the last $DAYS day(s)..."
  note "Please wait — this fetches every block and its transactions from the network"
  echo ""

  Q="query { totalEnergyConsumptionLastDays(days: $DAYS) { date blockCount transactionCount totalEnergyKwh } }"
  RESP=$(gql "$Q" 600)
  show_result "$RESP"

  echo "$RESP" | python3 -c "
import sys, json
d = json.load(sys.stdin)
if 'errors' in d: exit(0)
rows = d['data']['totalEnergyConsumptionLastDays']
print()
print('  {:<12}  {:>8}  {:>14}  {:>18}'.format('Date', 'Blocks', 'Transactions', 'Energy (KWh)'))
print('  ' + '-'*58)
for r in rows:
    print('  {:<12}  {:>8,}  {:>14,}  {:>18,.2f}'.format(
        r['date'], r['blockCount'], r['transactionCount'], r['totalEnergyKwh']))
total = sum(r['totalEnergyKwh'] for r in rows)
print('  ' + '-'*58)
print('  {:>37s}  {:>18,.2f}'.format('Total', total))
" 2>/dev/null || true
}

screen_wallet() {
  h1 "Energy consumption for a Bitcoin wallet"
  note "Calculates total energy used across all recent transactions for an address."
  note "Uses the size field from the address endpoint — no extra calls per transaction."
  echo ""

  h2 "  Enter a Bitcoin address:"
  note "(press Enter to use Satoshi Nakamoto's genesis wallet)"
  echo -ne "\n  ${CYAN}>${R} "; read -r ADDR
  ADDR=${ADDR:-1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa}

  if [[ "$ADDR" == "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa" ]]; then
    note "Using the genesis wallet — the very first Bitcoin address, from block 0 (Jan 3, 2009)"
  fi

  echo ""
  run "Querying energy for $ADDR..."
  echo ""

  Q="query { totalEnergyByWalletAddress(address: \\\"$ADDR\\\") { address transactionCount totalEnergyKwh } }"
  RESP=$(gql "$Q" 60)
  show_result "$RESP"

  echo "$RESP" | python3 -c "
import sys, json
d = json.load(sys.stdin)
if 'errors' in d: exit(0)
w = d['data']['totalEnergyByWalletAddress']
print('  Address       :', w['address'])
print('  Transactions  : {:,}'.format(w['transactionCount']))
print('  Total energy  : {:,.2f} KWh'.format(w['totalEnergyKwh']))
" 2>/dev/null || true
}

screen_validation() {
  h1 "Input validation"
  note "The API validates all inputs and returns structured GraphQL errors."
  note "These are not crashes — they are intentional, machine-readable error responses."
  echo ""

  sep
  h2 "  Sending days = 0  (must be a positive number)"
  sep
  echo ""
  RESP=$(gql "query { totalEnergyConsumptionLastDays(days: 0) { date } }" 10)
  show_result "$RESP"

  sep
  h2 "  Sending days = 999  (exceeds the maximum of 60)"
  sep
  echo ""
  RESP=$(gql "query { totalEnergyConsumptionLastDays(days: 999) { date } }" 10)
  show_result "$RESP"

  sep
  h2 "  Sending an empty block identifier"
  sep
  echo ""
  RESP=$(gql "query { energyPerTransactionForBlock(blockIdentifier: \\\"\\\") { blockHash } }" 10)
  show_result "$RESP"

  sep
  h2 "  Sending an empty wallet address"
  sep
  echo ""
  RESP=$(gql "query { totalEnergyByWalletAddress(address: \\\"\\\") { address } }" 10)
  show_result "$RESP"
}

screen_health() {
  h1 "System health"
  run "GET $API_URL/health"
  echo ""
  curl -s "$API_URL/health" | pretty_json | sed 's/^/      /'
  echo ""
  ok "Server is healthy"
  note "GraphQL playground available at: $GRAPHQL_URL"
}

screen_webui() {
  h1 "GraphiQL — interactive API explorer"
  note "GraphiQL is a browser-based IDE for writing and running GraphQL queries."
  note "You can explore the schema, autocomplete fields, and see live results."
  echo ""
  ok "Opening $GRAPHQL_URL in your browser..."
  echo ""
  if command -v open &>/dev/null; then
    open "$GRAPHQL_URL"
  elif command -v xdg-open &>/dev/null; then
    xdg-open "$GRAPHQL_URL"
  else
    warn "Could not detect a browser opener. Visit manually:"
    note "$GRAPHQL_URL"
  fi
}

print_menu() {
  clear
  echo ""
  echo -e "  ${BOLD}${CYAN}Bitcoin Energy Consumption API${R}"
  echo -e "  ${DIM}A GraphQL service for monitoring Bitcoin network energy usage${R}"
  echo ""
  sep
  echo ""
  echo -e "  ${BOLD}${WHITE}What would you like to explore?${R}"
  echo ""
  echo -e "   ${CYAN}${BOLD}1${R}  Energy per transaction for a specific block"
  echo -e "   ${CYAN}${BOLD}2${R}  Total energy consumption over the last N days"
  echo -e "   ${CYAN}${BOLD}3${R}  Total energy for a wallet address"
  echo -e "   ${CYAN}${BOLD}4${R}  Input validation examples"
  echo -e "   ${CYAN}${BOLD}5${R}  System health"
  echo -e "   ${CYAN}${BOLD}6${R}  Open GraphiQL in browser"
  echo ""
  sep
  echo ""
  echo -ne "  ${BOLD}Select an option: ${R}"
}

# ── startup ───────────────────────────────────────────────────────────────────
clear
echo ""
echo -e "  ${BOLD}${CYAN}Bitcoin Energy Consumption API${R}"
echo -e "  ${DIM}Starting up...${R}"
echo ""
ensure_server
echo ""
sleep 0.3

while true; do
  print_menu
  read -r CHOICE
  echo ""

  case "$CHOICE" in
    1) screen_block      ;;
    2) screen_daily      ;;
    3) screen_wallet     ;;
    4) screen_validation ;;
    5) screen_health     ;;
    6) screen_webui      ;;
    q|Q|quit|exit)
      echo -e "\n  ${DIM}Goodbye.${R}\n"; exit 0 ;;
    *)
      warn "Please enter a number from 1 to 6, or q to quit." ;;
  esac

  echo ""
  sep
  echo -ne "  ${DIM}Press Enter to go back to the menu...${R}"
  read -r
done
