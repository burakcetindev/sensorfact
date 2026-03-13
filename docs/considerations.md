# Design Considerations

This document explains the key design decisions behind this solution, the limitations encountered during implementation, and how each challenge was handled.

## 1. Goals and design concentration

The assignment has two mandatory goals:

1. Energy per transaction for a specific block.
2. Total daily energy for the last X days, while handling rate limiting.

My design concentration was:

- Correctness first: return deterministic results from well-defined formulas.
- Reliability under public API constraints: avoid frequent failures from rate limits.
- Performance with bounded complexity: make expensive queries predictable and fast enough for demo/interview use.
- Maintainability and clear boundaries: keep transport, business logic, and API schema separated.

## 2. Why GraphQL and this architecture

The API is GraphQL-first because the frontend needs selective, query-driven data. The code is layered so each concern has one owner:

- `src/clients/blockchain_client.py`: external API I/O, retry policy, pagination.
- `src/services/energy_service.py`: validation, business calculations, caching policy.
- `src/api/schema.py`: SDL and resolver mapping.
- `src/domain/models.py`: typed immutable domain objects shared between layers.

This split keeps changes localized:

- If upstream API changes: mostly `BlockchainClient` changes.
- If energy formula changes: service layer changes.
- If GraphQL contract changes: schema + mapper changes.

## 3. Why mempool.space instead of the suggested blockchain.com API

The assignment suggests `blockchain.com` / `blockchain.info`, and that was the initial direction. During implementation and testing, the following practical problems were observed:

- Frequent HTTP 429 responses for real workloads.
- Inconsistent response behavior on some documented endpoints.
- Occasional non-JSON/HTML error payloads where JSON was expected.

The solution switched to `mempool.space` because it provided:

- Stable and consistent REST responses for blocks, transactions, and addresses.
- Better operational behavior under retry/backoff.
- Clear endpoint model suitable for pagination and chunk walking.

Important design safeguard:

- The provider-specific logic is isolated in `BlockchainClient`.
- Service and GraphQL layers consume normalized internal shapes.

This means switching back to `blockchain.com` (or any other provider) is feasible by changing the client adapter instead of rewriting the whole system.

## 4. Main technical limitations and how they were addressed

### Limitation A: Public API rate limiting (429)

Challenge:

- Large blocks require many transaction page calls.
- Multi-day queries can trigger many block/history calls.

Mitigations implemented:

- Bounded parallelism with `asyncio.Semaphore(max_parallel_requests)`.
- Exponential backoff with separate rate-limit backoff timing.
- Max retry cap to avoid infinite waits.

Outcome:

- Better success rate and predictable behavior under load.

### Limitation B: Daily query complexity explosion

Challenge:

- Naive approach: query each day independently from chain tip.
- This causes repeated overlap work and O(N^2)-like API pressure.

Mitigations implemented:

- Single-pass multi-day collection: `get_blocks_for_days` walks backward once and buckets blocks by day.

Outcome:

- Reduced redundant calls and major speedup for `days > 1`.

### Limitation C: Redundant repeated lookups

Challenge:

- Same block/day requested multiple times from UI/demo.

Mitigations implemented:

- TTL cache for blocks.
- TTL cache for daily summaries.

Outcome:

- Warm requests are near-instant and reduce external API pressure.

### Limitation D: Incomplete or dirty upstream data

Challenge:

- Some entries may miss `txid` or `size`.

Mitigations implemented:

- Defensive normalization in the client layer.
- Skip malformed entries without failing full request.
- Deduplicate wallet tx hashes where needed.

Outcome:

- Partial data quality issues do not crash user flows.

## 5. Energy model and sustainability rationale

The assignment provides a simplified model:

- `energy_kwh = size_bytes * 4.56`

This model is applied consistently across all endpoints.

To improve sustainability interpretation, the solution also adds CO2 equivalent fields:

- `co2_equivalent_kg = energy_kwh * co2_per_kwh_kg`
- default `co2_per_kwh_kg = 0.233`

Why this matters:

- KWh alone is technical.
- CO2-equivalent is easier for product stakeholders to compare and reason about.

## 6. Error handling strategy

Error handling is explicit and layered:

- Validation errors become structured GraphQL errors, not server crashes.
- Upstream API failures are retried when transient.
- Non-recoverable failures are surfaced with meaningful messages.
- Malformed request JSON on `/graphql` returns HTTP 400 cleanly.

This was designed to make client behavior deterministic and interview demos stable.

## 7. Why Python for this version

The assignment encourages staying close to their TypeScript stack, but also allows a preferred stack.

Python was chosen here to maximize implementation speed and quality under time constraints while still demonstrating:

- clean architecture,
- async I/O,
- resilience patterns,
- and test discipline.

The current structure intentionally keeps a future TypeScript port straightforward:

- clear boundaries,
- contract-first GraphQL schema,
- isolated client adapter and service logic.

## 8. Quality gates and submission readiness

Quality decisions made:

- Comprehensive test suite covering unit and integration edges.
- Coverage gate enforced in pytest config (`--cov-fail-under=80`).
- Current state: all tests passing with coverage above threshold.

This ensures the project is demonstrably stable, not only functionally complete.

## 9. Known trade-offs and future improvements

Trade-offs accepted for assignment scope:

- In-memory cache only (no distributed cache).
- Single-process deployment assumptions.
- Public API dependency (no internal data mirror).

If productized further, next steps would be:

- Pluggable provider abstraction with fallback providers.
- Background pre-aggregation for daily summaries.
- Persistent/shared cache (Redis).
- Observability (metrics, tracing, structured logs).
- Optional TypeScript implementation parity for team homogeneity.
