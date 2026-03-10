"""Unit tests for BlockchainClient — all HTTP is stubbed via http_getter."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from src.clients.blockchain_client import (
    BlockchainClient,
    BlockchainClientError,
    NotFoundError,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_client(responses: dict) -> BlockchainClient:
    """Return a BlockchainClient with path-keyed canned responses.

    Args:
        responses: Mapping of path substrings to return values.  The first
            matching key wins per request.
    """
    async def getter(path: str):
        # Sort by key length descending so more-specific paths win over shorter
        # prefixes (e.g. "/api/block/h/txs" wins over "/api/block/h").
        for key, value in sorted(responses.items(), key=lambda kv: len(kv[0]), reverse=True):
            if key in path:
                return value
        raise KeyError(f"No canned response for: {path}")

    return BlockchainClient(http_getter=getter)


# ---------------------------------------------------------------------------
# _get_block_txs
# ---------------------------------------------------------------------------

class TestGetBlockTxs:

    @pytest.mark.asyncio
    async def test_zero_tx_count_returns_empty_list(self):
        """_get_block_txs with tx_count=0 must return [] without any HTTP call."""
        client = make_client({})
        result = await client._get_block_txs("anyhash", 0)
        assert result == []

    @pytest.mark.asyncio
    async def test_single_page_returned_correctly(self):
        txs = [{"txid": f"tx{i}", "size": 100 + i} for i in range(5)]
        client = make_client({"/api/block/h1/txs": txs})
        result = await client._get_block_txs("h1", 5)
        assert result == txs

    @pytest.mark.asyncio
    async def test_two_pages_concatenated_in_order(self):
        """Pages 0 and 25 are fetched concurrently and reassembled in offset order."""
        page0 = [{"txid": f"tx_p0_{i}", "size": i} for i in range(25)]
        page25 = [{"txid": f"tx_p25_{i}", "size": i + 100} for i in range(25)]

        async def getter(path: str):
            if "/txs/25" in path:
                return page25
            if "/txs" in path:
                return page0
            raise KeyError(path)

        client = BlockchainClient(http_getter=getter)
        result = await client._get_block_txs("somehash", 50)
        assert result[:25] == page0
        assert result[25:] == page25


# ---------------------------------------------------------------------------
# get_latest_block
# ---------------------------------------------------------------------------

class TestGetLatestBlock:

    @pytest.mark.asyncio
    async def test_returns_hash_and_height(self):
        client = make_client({
            "/api/blocks/tip/hash": "latesttiphash",
            "/api/block/latesttiphash": {"id": "latesttiphash", "height": 850_000},
        })
        result = await client.get_latest_block()
        assert result == {"hash": "latesttiphash", "height": 850_000}

    @pytest.mark.asyncio
    async def test_empty_tip_hash_raises(self):
        client = make_client({"/api/blocks/tip/hash": ""})
        with pytest.raises(BlockchainClientError, match="latest block hash"):
            await client.get_latest_block()


# ---------------------------------------------------------------------------
# get_block_by_hash
# ---------------------------------------------------------------------------

class TestGetBlockByHash:

    @pytest.mark.asyncio
    async def test_fetches_block_by_hash(self):
        block_hash = "validhash"
        client = make_client({
            f"/api/block/{block_hash}": {"id": block_hash, "height": 1, "tx_count": 1},
            f"/api/block/{block_hash}/txs": [{"txid": "tx1", "size": 250}],
        })
        result = await client.get_block_by_hash(block_hash)
        assert result["hash"] == block_hash
        assert result["height"] == 1
        assert len(result["tx"]) == 1
        assert result["tx"][0] == {"hash": "tx1", "size": 250}

    @pytest.mark.asyncio
    async def test_numeric_height_resolves_to_hash(self):
        resolved_hash = "resolvedhash"
        client = make_client({
            "/api/block-height/12345": resolved_hash,
            f"/api/block/{resolved_hash}": {"id": resolved_hash, "height": 12345, "tx_count": 1},
            f"/api/block/{resolved_hash}/txs": [{"txid": "tx1", "size": 100}],
        })
        result = await client.get_block_by_hash("12345")
        assert result["hash"] == resolved_hash
        assert result["height"] == 12345

    @pytest.mark.asyncio
    async def test_strips_whitespace_from_identifier(self):
        block_hash = "testhash"
        client = make_client({
            f"/api/block/{block_hash}": {"id": block_hash, "height": 10, "tx_count": 0},
        })
        result = await client.get_block_by_hash(f"  {block_hash}  ")
        assert result["hash"] == block_hash

    @pytest.mark.asyncio
    async def test_transactions_without_txid_excluded(self):
        block_hash = "h"
        client = make_client({
            f"/api/block/{block_hash}": {"id": block_hash, "height": 1, "tx_count": 2},
            f"/api/block/{block_hash}/txs": [
                {"size": 100},               # no txid — excluded
                {"txid": "good", "size": 200},
            ],
        })
        result = await client.get_block_by_hash(block_hash)
        assert len(result["tx"]) == 1
        assert result["tx"][0]["hash"] == "good"

    @pytest.mark.asyncio
    async def test_empty_block_returns_empty_tx_list(self):
        block_hash = "empty"
        client = make_client({
            f"/api/block/{block_hash}": {"id": block_hash, "height": 5, "tx_count": 0},
        })
        result = await client.get_block_by_hash(block_hash)
        assert result["tx"] == []


# ---------------------------------------------------------------------------
# get_blocks_for_days
# ---------------------------------------------------------------------------

class TestGetBlocksForDays:

    @pytest.mark.asyncio
    async def test_empty_input_returns_empty_dict(self):
        """An empty day list should short-circuit and return {} immediately."""
        client = make_client({})
        result = await client.get_blocks_for_days([])
        assert result == {}

    @pytest.mark.asyncio
    async def test_blocks_bucketed_by_correct_day(self):
        """Blocks are placed in the bucket matching their UTC timestamp."""
        today = datetime.now(tz=UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        today_ts = int(today.timestamp())
        yesterday = today - timedelta(days=1)
        yesterday_ts = int(yesterday.timestamp())

        chunk = [
            {"id": "b_today", "height": 10, "timestamp": today_ts + 100,
             "size": 1000, "tx_count": 10},
            {"id": "b_yesterday", "height": 9, "timestamp": yesterday_ts + 100,
             "size": 500, "tx_count": 5},
            # Older than both requested days — triggers early stop
            {"id": "b_old", "height": 8, "timestamp": yesterday_ts - 1,
             "size": 200, "tx_count": 2},
        ]

        client = make_client({
            "/api/blocks/tip/height": "10",
            "/api/blocks/10": chunk,
        })

        result = await client.get_blocks_for_days([today, yesterday])
        today_key = today.date().isoformat()
        yesterday_key = yesterday.date().isoformat()

        assert any(b["hash"] == "b_today" for b in result[today_key])
        assert any(b["hash"] == "b_yesterday" for b in result[yesterday_key])
        # The old block must not appear in any bucket
        all_ids = [b["hash"] for blocks in result.values() for b in blocks]
        assert "b_old" not in all_ids

    @pytest.mark.asyncio
    async def test_naive_datetimes_treated_as_utc(self):
        """Timezone-naive datetimes must be accepted without raising."""
        today_naive = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        today_ts = int(today_naive.replace(tzinfo=UTC).timestamp())

        chunk = [
            {"id": "b1", "height": 5, "timestamp": today_ts + 1,
             "size": 100, "tx_count": 1},
            {"id": "b_old", "height": 4, "timestamp": today_ts - 86_400,
             "size": 50, "tx_count": 1},
        ]

        client = make_client({
            "/api/blocks/tip/height": "5",
            "/api/blocks/5": chunk,
        })
        result = await client.get_blocks_for_days([today_naive])
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# get_wallet_transactions
# ---------------------------------------------------------------------------

class TestGetWalletTransactions:

    @pytest.mark.asyncio
    async def test_returns_normalised_txs(self):
        addr = "1Addr"
        client = make_client({
            f"/api/address/{addr}/txs": [
                {"txid": "tx1", "size": 300},
                {"txid": "tx2", "size": 600},
            ]
        })
        result = await client.get_wallet_transactions(addr)
        assert result == {"txs": [
            {"hash": "tx1", "size": 300},
            {"hash": "tx2", "size": 600},
        ]}

    @pytest.mark.asyncio
    async def test_non_list_response_raises_client_error(self):
        addr = "bad"
        client = make_client({f"/api/address/{addr}/txs": {"error": "not a list"}})
        with pytest.raises(BlockchainClientError):
            await client.get_wallet_transactions(addr)

    @pytest.mark.asyncio
    async def test_empty_list_returns_empty_txs(self):
        addr = "empty"
        client = make_client({f"/api/address/{addr}/txs": []})
        result = await client.get_wallet_transactions(addr)
        assert result == {"txs": []}

    @pytest.mark.asyncio
    async def test_txs_without_txid_are_excluded(self):
        addr = "addr"
        client = make_client({
            f"/api/address/{addr}/txs": [
                {"size": 100},                   # no txid — excluded
                {"txid": "good", "size": 200},
            ]
        })
        result = await client.get_wallet_transactions(addr)
        assert len(result["txs"]) == 1
        assert result["txs"][0]["hash"] == "good"

    @pytest.mark.asyncio
    async def test_txs_without_size_are_excluded(self):
        """Transactions must have an integer size to be included."""
        addr = "addr2"
        client = make_client({
            f"/api/address/{addr}/txs": [
                {"txid": "no_size"},            # missing size — excluded
                {"txid": "good", "size": 200},
            ]
        })
        result = await client.get_wallet_transactions(addr)
        assert len(result["txs"]) == 1


# ---------------------------------------------------------------------------
# get_transaction
# ---------------------------------------------------------------------------

class TestGetTransaction:

    @pytest.mark.asyncio
    async def test_returns_normalised_tx(self):
        tx_hash = "mytxhash"
        client = make_client({
            f"/api/tx/{tx_hash}": {"txid": tx_hash, "size": 400},
        })
        result = await client.get_transaction(tx_hash)
        assert result == {"hash": tx_hash, "size": 400}
