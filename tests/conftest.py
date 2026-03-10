"""Shared pytest fixtures for the Bitcoin Energy API test suite."""
from __future__ import annotations

import pytest

from src.clients.blockchain_client import BlockchainClient
from src.services.energy_service import EnergyService


# ---------------------------------------------------------------------------
# Blockchain client stub helpers
# ---------------------------------------------------------------------------

def make_http_getter(responses: dict):
    """Return an async callable that maps URL paths to canned responses.

    Args:
        responses: Mapping of path substring to the value to return for that
            path.  The first key whose substring is found in the requested path
            wins.
    """
    async def getter(path: str):
        # Sort by key length descending so more-specific paths win over shorter
        # prefixes (e.g. "/api/block/h/txs" wins over "/api/block/h").
        for key, value in sorted(responses.items(), key=lambda kv: len(kv[0]), reverse=True):
            if key in path:
                return value
        raise KeyError(f"No canned response for path: {path}")

    return getter


def make_service(responses: dict) -> EnergyService:
    """Build an EnergyService wired up to canned HTTP responses.

    Args:
        responses: Passed directly to :func:`make_http_getter`.
    """
    client = BlockchainClient(http_getter=make_http_getter(responses))
    return EnergyService(client)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def minimal_block_responses():
    """Canned responses for a block with three transactions."""
    block_hash = "abc123"
    return {
        f"/api/block/{block_hash}": {
            "id": block_hash,
            "height": 800_000,
            "tx_count": 3,
        },
        f"/api/block/{block_hash}/txs": [
            {"txid": "tx1", "size": 250},
            {"txid": "tx2", "size": 500},
            {"txid": "tx3", "size": 1000},
        ],
    }


@pytest.fixture()
def service_with_minimal_block(minimal_block_responses):
    """EnergyService with a three-transaction block ready to query."""
    return make_service(minimal_block_responses), "abc123"
