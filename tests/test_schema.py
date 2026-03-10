"""Tests for GraphQL resolvers and DTO mapper functions in api/schema.py."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.api.schema import (
    _to_block,
    _to_daily,
    _to_wallet,
    resolve_energy_per_transaction_for_block,
    resolve_latest_block,
    resolve_total_energy_by_wallet_address,
    resolve_total_energy_consumption_last_days,
)
from src.clients.blockchain_client import BlockchainClientError
from src.domain.models import (
    BlockEnergySummary,
    DailyEnergySummary,
    TransactionEnergy,
    WalletEnergySummary,
)
from src.services.energy_service import ValidationError


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def make_info(service):
    """Return a minimal Ariadne-style info mock with the service in context."""
    info = MagicMock()
    info.context = {"energy_service": service}
    return info


def make_tx(hash_="tx1", size=250, energy=1.14, co2=0.265548):
    return TransactionEnergy(hash=hash_, size_bytes=size, energy_kwh=energy, co2_equivalent_kg=co2)


def make_block_summary():
    tx = make_tx()
    return BlockEnergySummary(
        block_hash="abc123",
        block_height=800_000,
        transaction_count=1,
        total_energy_kwh=1.14,
        energy_per_transaction_kwh=1.14,
        co2_equivalent_kg=0.265548,
        transactions=[tx],
    )


def make_daily_summary():
    return DailyEnergySummary(
        date="2024-01-15",
        block_count=5,
        transaction_count=100,
        total_energy_kwh=500.0,
        average_energy_per_transaction_kwh=5.0,
        co2_equivalent_kg=116.5,
    )


def make_wallet_summary():
    return WalletEnergySummary(
        address="1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa",
        transaction_count=3,
        total_energy_kwh=12.456,
        co2_equivalent_kg=2.902248,
    )


# ---------------------------------------------------------------------------
# Mapper functions
# ---------------------------------------------------------------------------

class TestToBlock:

    def test_all_fields_present(self):
        item = make_block_summary()
        result = _to_block(item)
        assert result["blockHash"] == "abc123"
        assert result["blockHeight"] == 800_000
        assert result["transactionCount"] == 1
        assert result["totalEnergyKwh"] == 1.14
        assert result["energyPerTransactionKwh"] == 1.14
        assert result["co2EquivalentKg"] == 0.265548

    def test_transactions_are_mapped(self):
        item = make_block_summary()
        result = _to_block(item)
        assert len(result["transactions"]) == 1
        tx = result["transactions"][0]
        assert tx["hash"] == "tx1"
        assert tx["sizeBytes"] == 250
        assert tx["energyKwh"] == 1.14
        assert tx["co2EquivalentKg"] == 0.265548

    def test_empty_transactions(self):
        item = BlockEnergySummary(
            block_hash="h", block_height=1, transaction_count=0,
            total_energy_kwh=0, energy_per_transaction_kwh=0.0,
            co2_equivalent_kg=0.0, transactions=[],
        )
        result = _to_block(item)
        assert result["transactions"] == []


class TestToDaily:

    def test_all_fields_present(self):
        item = make_daily_summary()
        result = _to_daily(item)
        assert result["date"] == "2024-01-15"
        assert result["blockCount"] == 5
        assert result["transactionCount"] == 100
        assert result["totalEnergyKwh"] == 500.0
        assert result["averageEnergyPerTransactionKwh"] == 5.0
        assert result["co2EquivalentKg"] == 116.5


class TestToWallet:

    def test_all_fields_present(self):
        item = make_wallet_summary()
        result = _to_wallet(item)
        assert result["address"] == "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"
        assert result["transactionCount"] == 3
        assert result["totalEnergyKwh"] == 12.456
        assert result["co2EquivalentKg"] == 2.902248


# ---------------------------------------------------------------------------
# Resolvers
# ---------------------------------------------------------------------------

class TestResolveLatestBlock:

    @pytest.mark.asyncio
    async def test_returns_hash_and_height(self):
        svc = MagicMock()
        svc.get_latest_block = AsyncMock(return_value={"hash": "tip", "height": 900_000})
        result = await resolve_latest_block(None, make_info(svc))
        assert result == {"hash": "tip", "height": 900_000}

    @pytest.mark.asyncio
    async def test_client_error_raises_value_error(self):
        svc = MagicMock()
        svc.get_latest_block = AsyncMock(side_effect=BlockchainClientError("boom"))
        with pytest.raises(ValueError, match="boom"):
            await resolve_latest_block(None, make_info(svc))


class TestResolveEnergyPerTransactionForBlock:

    @pytest.mark.asyncio
    async def test_returns_mapped_block(self):
        block = make_block_summary()
        svc = MagicMock()
        svc.energy_per_transaction_for_block = AsyncMock(return_value=block)
        result = await resolve_energy_per_transaction_for_block(None, make_info(svc), "abc123")
        assert result["blockHash"] == "abc123"
        assert result["blockHeight"] == 800_000

    @pytest.mark.asyncio
    async def test_validation_error_raises_value_error(self):
        svc = MagicMock()
        svc.energy_per_transaction_for_block = AsyncMock(
            side_effect=ValidationError("bad input")
        )
        with pytest.raises(ValueError, match="bad input"):
            await resolve_energy_per_transaction_for_block(None, make_info(svc), "")

    @pytest.mark.asyncio
    async def test_client_error_raises_value_error(self):
        svc = MagicMock()
        svc.energy_per_transaction_for_block = AsyncMock(
            side_effect=BlockchainClientError("network failure")
        )
        with pytest.raises(ValueError, match="network failure"):
            await resolve_energy_per_transaction_for_block(None, make_info(svc), "hash")


class TestResolveTotalEnergyConsumptionLastDays:

    @pytest.mark.asyncio
    async def test_returns_list_of_daily_dicts(self):
        daily = make_daily_summary()
        svc = MagicMock()
        svc.total_energy_consumption_last_days = AsyncMock(return_value=[daily])
        result = await resolve_total_energy_consumption_last_days(None, make_info(svc), 3)
        assert len(result) == 1
        assert result[0]["date"] == "2024-01-15"

    @pytest.mark.asyncio
    async def test_validation_error_raises_value_error(self):
        svc = MagicMock()
        svc.total_energy_consumption_last_days = AsyncMock(
            side_effect=ValidationError("days out of range")
        )
        with pytest.raises(ValueError, match="days out of range"):
            await resolve_total_energy_consumption_last_days(None, make_info(svc), 0)


class TestResolveTotalEnergyByWalletAddress:

    @pytest.mark.asyncio
    async def test_returns_mapped_wallet(self):
        wallet = make_wallet_summary()
        svc = MagicMock()
        svc.total_energy_by_wallet_address = AsyncMock(return_value=wallet)
        result = await resolve_total_energy_by_wallet_address(
            None, make_info(svc), "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"
        )
        assert result["address"] == "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"
        assert result["transactionCount"] == 3

    @pytest.mark.asyncio
    async def test_validation_error_raises_value_error(self):
        svc = MagicMock()
        svc.total_energy_by_wallet_address = AsyncMock(
            side_effect=ValidationError("empty address")
        )
        with pytest.raises(ValueError, match="empty address"):
            await resolve_total_energy_by_wallet_address(None, make_info(svc), "")

    @pytest.mark.asyncio
    async def test_client_error_raises_value_error(self):
        svc = MagicMock()
        svc.total_energy_by_wallet_address = AsyncMock(
            side_effect=BlockchainClientError("timeout")
        )
        with pytest.raises(ValueError, match="timeout"):
            await resolve_total_energy_by_wallet_address(None, make_info(svc), "addr")
