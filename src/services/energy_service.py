from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

from src.clients.blockchain_client import BlockchainClient, BlockchainClientError
from src.config.settings import settings
from src.domain.models import (
    BlockEnergySummary,
    DailyEnergySummary,
    TransactionEnergy,
    WalletEnergySummary,
)
from src.utils.cache import TTLCache


class ValidationError(Exception):
    pass


class EnergyService:
    def __init__(self, blockchain_client: BlockchainClient) -> None:
        self._client = blockchain_client
        self._block_cache = TTLCache[dict[str, Any]](settings.block_cache_ttl_seconds)
        self._daily_cache = TTLCache[DailyEnergySummary](settings.daily_cache_ttl_seconds)
        self._semaphore = asyncio.Semaphore(settings.max_parallel_requests)

    def _validate_block_identifier(self, block_identifier: str) -> str:
        normalized = block_identifier.strip()
        if not normalized:
            raise ValidationError("Block identifier cannot be empty.")
        return normalized

    def _validate_days(self, days: int) -> int:
        if days <= 0:
            raise ValidationError("Days must be greater than 0.")
        if days > 60:
            raise ValidationError("Days cannot be greater than 60 to protect API limits.")
        return days

    def _validate_wallet_address(self, address: str) -> str:
        normalized = address.strip()
        if not normalized:
            raise ValidationError("Wallet address cannot be empty.")
        return normalized

    def _energy_for_size(self, size_bytes: int) -> float:
        if size_bytes < 0:
            raise ValidationError("Transaction size cannot be negative.")
        return round(size_bytes * settings.energy_cost_per_byte_kwh, 6)

    async def _get_block_cached(self, block_hash: str) -> dict[str, Any]:
        cached = self._block_cache.get(block_hash)
        if cached is not None:
            return cached
        block = await self._client.get_block_by_hash(block_hash)
        self._block_cache.set(block_hash, block)
        return block

    async def get_latest_block(self) -> dict:
        block = await self._client.get_latest_block()
        return {
            "hash": str(block.get("hash", "")),
            "height": int(block.get("height", 0)),
        }

    async def energy_per_transaction_for_block(self, block_identifier: str) -> BlockEnergySummary:
        normalized = self._validate_block_identifier(block_identifier)
        block = await self._get_block_cached(normalized)

        tx_payloads = block.get("tx")
        if not isinstance(tx_payloads, list):
            raise BlockchainClientError("Unexpected block payload: missing tx list.")

        transactions: list[TransactionEnergy] = []
        for tx in tx_payloads:
            tx_hash = str(tx.get("hash", ""))
            tx_size = tx.get("size")
            if not tx_hash or not isinstance(tx_size, int):
                continue
            transactions.append(
                TransactionEnergy(
                    hash=tx_hash,
                    size_bytes=tx_size,
                    energy_kwh=self._energy_for_size(tx_size),
                )
            )

        total_energy = round(sum(tx.energy_kwh for tx in transactions), 6)
        energy_per_tx = round(total_energy / len(transactions), 6) if transactions else 0.0
        block_height = block.get("height") if isinstance(block.get("height"), int) else None

        return BlockEnergySummary(
            block_hash=str(block.get("hash", normalized)),
            block_height=block_height,
            transaction_count=len(transactions),
            total_energy_kwh=total_energy,
            energy_per_transaction_kwh=energy_per_tx,
            transactions=transactions,
        )

    async def _daily_energy_for_date(self, day_start_utc: datetime) -> DailyEnergySummary:
        cache_key = day_start_utc.date().isoformat()
        cached = self._daily_cache.get(cache_key)
        if cached is not None:
            return cached

        blocks_result = await self._client.get_blocks_by_day(day_start_utc)
        # get_blocks_by_day now returns list[dict] directly
        if not isinstance(blocks_result, list):
            raise BlockchainClientError("Unexpected blocks-by-day response format.")

        block_items = blocks_result  # already a list[dict] after validation above

        async def load_block_energy(block_item: dict[str, Any]) -> tuple[int, float]:
            block_hash = block_item.get("hash")
            if not isinstance(block_hash, str) or not block_hash:
                return (0, 0.0)
            async with self._semaphore:
                block = await self._get_block_cached(block_hash)
            txs = block.get("tx")
            if not isinstance(txs, list):
                return (0, 0.0)

            total = 0.0
            count = 0
            for tx in txs:
                tx_size = tx.get("size")
                if isinstance(tx_size, int):
                    total += self._energy_for_size(tx_size)
                    count += 1
            return (count, round(total, 6))

        block_stats = await asyncio.gather(*(load_block_energy(block) for block in block_items))
        tx_count = sum(item[0] for item in block_stats)
        total_energy = round(sum(item[1] for item in block_stats), 6)

        summary = DailyEnergySummary(
            date=day_start_utc.date().isoformat(),
            block_count=len(block_items),
            transaction_count=tx_count,
            total_energy_kwh=total_energy,
        )
        self._daily_cache.set(cache_key, summary)
        return summary

    async def total_energy_consumption_last_days(self, days: int) -> list[DailyEnergySummary]:
        days = self._validate_days(days)
        now = datetime.now(tz=UTC)

        dates: list[datetime] = []
        for offset in range(days):
            day = (now - timedelta(days=offset)).replace(hour=0, minute=0, second=0, microsecond=0)
            dates.append(day)

        summaries = await asyncio.gather(*(self._daily_energy_for_date(day) for day in dates))
        return sorted(summaries, key=lambda item: item.date)

    async def total_energy_by_wallet_address(self, address: str) -> WalletEnergySummary:
        wallet = self._validate_wallet_address(address)
        result = await self._client.get_wallet_transactions(wallet)
        txs = result.get("txs")
        if not isinstance(txs, list):
            raise BlockchainClientError("Unexpected wallet payload: missing txs.")

        unique_hashes: set[str] = set()
        total = 0.0

        for tx in txs:
            tx_hash = tx.get("hash")
            if not isinstance(tx_hash, str) or not tx_hash or tx_hash in unique_hashes:
                continue
            unique_hashes.add(tx_hash)
            # rawaddr already includes `size` on each tx object — no extra API call needed
            tx_size = tx.get("size")
            if isinstance(tx_size, int):
                total += self._energy_for_size(tx_size)

        return WalletEnergySummary(
            address=wallet,
            transaction_count=len(unique_hashes),
            total_energy_kwh=round(total, 6),
        )
