from __future__ import annotations

import asyncio
import json as _json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import httpx

from src.config.settings import settings


class BlockchainClientError(Exception):
    pass


class RateLimitedError(BlockchainClientError):
    pass


class NotFoundError(BlockchainClientError):
    pass


# mempool.space API base: https://mempool.space
# Docs: https://mempool.space/docs/api/rest
_BASE = "https://mempool.space"


class BlockchainClient:
    """Async HTTP client backed by the mempool.space public REST API.

    Normalises mempool.space responses into the same dict shapes that the
    service layer already expects (matching the old blockchain.com format):

        block  → {"hash": str, "height": int, "tx": [{"hash": str, "size": int}]}
        txs    → [{"hash": str, "size": int}]
        wallet → {"txs": [{"hash": str, "size": int}]}
    """

    # mempool.space paginates block transactions in pages of 25
    _TX_PAGE_SIZE = 25

    def __init__(self, http_getter: Callable[..., Any] | None = None) -> None:
        self._http_getter = http_getter
        self._timeout = settings.request_timeout_seconds

    # ── low-level HTTP ────────────────────────────────────────────────────────

    def _make_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=_BASE,
            timeout=self._timeout,
            follow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                              "AppleWebKit/537.36 (KHTML, like Gecko) "
                              "Chrome/120.0.0.0 Safari/537.36",
                "Accept": "application/json",
            },
        )

    async def _get(self, path: str) -> Any:
        """GET with exponential-backoff retries. Returns parsed JSON or plain text.

        Regular errors use retry_backoff_seconds (0.5 → 1 → 2 …).
        HTTP 429 rate-limit responses use rate_limit_backoff_seconds (5 → 10 → 20 …)
        so we don't hammer the API while waiting for the limit to clear.
        """
        delay = settings.retry_backoff_seconds
        rate_delay = settings.rate_limit_backoff_seconds
        last_error: Exception | None = None

        for attempt in range(1, settings.max_retries + 1):
            try:
                if self._http_getter is not None:
                    return await self._http_getter(path)

                async with self._make_client() as client:
                    response = await client.get(path)

                if response.status_code == 429:
                    raise RateLimitedError("Rate limited by mempool.space API.")
                if response.status_code == 404:
                    raise NotFoundError(f"Not found: {path}")

                response.raise_for_status()

                ct = response.headers.get("content-type", "")
                if "application/json" in ct:
                    try:
                        return response.json()
                    except _json.JSONDecodeError as exc:
                        raise BlockchainClientError(
                            f"Non-JSON response at {path}: {response.text[:200]}"
                        ) from exc
                # plain-text response (e.g. /api/blocks/tip/hash)
                return response.text.strip()

            except (
                httpx.HTTPError,
                RateLimitedError,
                BlockchainClientError,
            ) as exc:
                last_error = exc
                if isinstance(exc, NotFoundError):
                    raise
                if attempt == settings.max_retries:
                    break
                if isinstance(exc, RateLimitedError):
                    # Rate-limited: back off much longer before retrying
                    await asyncio.sleep(rate_delay)
                    rate_delay *= 2
                else:
                    await asyncio.sleep(delay)
                    delay *= 2

        raise BlockchainClientError(
            f"Request failed after {settings.max_retries} attempts "
            f"[{path}]: {type(last_error).__name__}: {last_error}"
        )

    async def _get_json(self, path: str) -> Any:
        result = await self._get(path)
        if isinstance(result, str):
            try:
                return _json.loads(result)
            except _json.JSONDecodeError:
                return result
        return result

    # ── block transaction pagination ──────────────────────────────────────────

    async def _get_block_txs(self, block_hash: str, tx_count: int) -> list[dict[str, Any]]:
        """Fetch all transactions for a block — sequential pages to avoid rate limits."""
        txs: list[dict] = []
        start = 0
        while start < tx_count:
            path = (
                f"/api/block/{block_hash}/txs/{start}"
                if start > 0
                else f"/api/block/{block_hash}/txs"
            )
            page = await self._get_json(path)
            if not isinstance(page, list) or not page:
                break
            txs.extend(page)
            start += self._TX_PAGE_SIZE
            if start < tx_count:
                await asyncio.sleep(0.25)  # pacing between pages avoids 429s
        return txs

    # ── public API ────────────────────────────────────────────────────────────

    async def get_latest_block(self) -> dict[str, Any]:
        """Returns {"hash": str, "height": int}."""
        block_hash = await self._get("/api/blocks/tip/hash")
        if not isinstance(block_hash, str) or not block_hash:
            raise BlockchainClientError("Could not fetch latest block hash.")
        block = await self._get_json(f"/api/block/{block_hash}")
        return {
            "hash": str(block.get("id", block_hash)),
            "height": int(block.get("height", 0)),
        }

    async def get_block_by_hash(self, block_hash_or_height: str) -> dict[str, Any]:
        """Returns {"hash": str, "height": int, "tx": [{"hash": str, "size": int}]}."""
        ident = block_hash_or_height.strip()

        # If it looks like a height (numeric), resolve to hash first
        if ident.isdigit():
            resolved = await self._get(f"/api/block-height/{ident}")
            if not isinstance(resolved, str) or not resolved:
                raise BlockchainClientError(f"No block at height {ident}.")
            ident = resolved.strip()

        block = await self._get_json(f"/api/block/{ident}")
        tx_count = int(block.get("tx_count", 0))
        raw_txs = await self._get_block_txs(ident, tx_count)

        txs = [
            {"hash": str(tx.get("txid", "")), "size": int(tx.get("size", 0))}
            for tx in raw_txs
            if tx.get("txid") and isinstance(tx.get("size"), int)
        ]

        return {
            "hash": str(block.get("id", ident)),
            "height": int(block.get("height", 0)),
            "tx": txs,
        }

    async def get_blocks_by_day(self, day_start_utc: datetime) -> list[dict[str, Any]]:
        """Return block summaries for the UTC day of day_start_utc.

        mempool.space has no direct "blocks for a day" endpoint, so we:
          1. Get the current tip height + timestamp.
          2. Walk backwards in chunks of 10 blocks until we pass the day.
          3. Collect only blocks whose timestamp falls in [day_start, day_end).
        """
        if day_start_utc.tzinfo is None:
            day_start_utc = day_start_utc.replace(tzinfo=UTC)

        day_start_ts = int(day_start_utc.timestamp())
        day_end_ts = day_start_ts + 86_400

        # Get current tip to know where to start walking
        tip_height_text = await self._get("/api/blocks/tip/height")
        current_height = int(str(tip_height_text).strip())

        day_blocks: list[dict[str, Any]] = []
        start_height = current_height
        found_any = False

        while start_height > 0:
            # /api/blocks/{start_height} returns up to 10 blocks going backwards
            chunk = await self._get_json(f"/api/blocks/{start_height}")
            if not isinstance(chunk, list) or not chunk:
                break

            for block in chunk:
                ts = int(block.get("timestamp", 0))
                if ts >= day_end_ts:
                    continue  # future or same-day later chunk
                if ts < day_start_ts:
                    # We've gone past the target day — stop
                    found_any = True
                    break
                day_blocks.append({
                    "hash": str(block.get("id", "")),
                    "time": ts,
                    # Include block-level size and tx_count so callers can
                    # compute energy without fetching all transactions.
                    "size": int(block.get("size", 0)),
                    "tx_count": int(block.get("tx_count", 0)),
                })
                found_any = True

            if found_any and any(int(b.get("timestamp", 0)) < day_start_ts for b in chunk):
                break

            # Move start height back by the size of this chunk
            last_height = int(chunk[-1].get("height", start_height - len(chunk)))
            if last_height >= start_height:
                break
            start_height = last_height - 1

            await asyncio.sleep(0.4)  # gentle pacing between block chunks

        return day_blocks

    async def get_transaction(self, tx_hash: str) -> dict[str, Any]:
        """Returns {"hash": str, "size": int}."""
        tx = await self._get_json(f"/api/tx/{tx_hash}")
        return {
            "hash": str(tx.get("txid", tx_hash)),
            "size": int(tx.get("size", 0)),
        }

    async def get_wallet_transactions(self, address: str) -> dict[str, Any]:
        """Returns {"txs": [{"hash": str, "size": int}]}.

        mempool.space /api/address/{addr}/txs returns up to 50 confirmed txs.
        """
        raw = await self._get_json(f"/api/address/{address}/txs")
        if not isinstance(raw, list):
            raise BlockchainClientError(f"Unexpected wallet response for {address}.")
        txs = [
            {"hash": str(tx.get("txid", "")), "size": int(tx.get("size", 0))}
            for tx in raw
            if tx.get("txid") and isinstance(tx.get("size"), int)
        ]
        return {"txs": txs}
