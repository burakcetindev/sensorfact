from __future__ import annotations

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
    """Raised when a caller-supplied input fails a business rule.

    Maps to a structured GraphQL ``errors[]`` entry rather than an HTTP 500.
    """


class EnergyService:
    """Core business-logic layer for Bitcoin energy calculations.

    Coordinates the blockchain data client, the TTL caches, and the energy
    model (4.56 KWh per byte) to produce typed domain objects consumed by the
    GraphQL resolvers.

    Designed for dependency injection: pass a real ``BlockchainClient`` in
    production and a stub/fake in tests.
    """
    def __init__(self, blockchain_client: BlockchainClient) -> None:
        """Create an ``EnergyService`` backed by *blockchain_client*.

        Args:
            blockchain_client: HTTP client used to fetch block and wallet data.
                Injected so tests can supply a lightweight stub.
        """
        self._client = blockchain_client
        self._block_cache = TTLCache[dict[str, Any]](settings.block_cache_ttl_seconds)
        self._daily_cache = TTLCache[DailyEnergySummary](settings.daily_cache_ttl_seconds)

    def _validate_block_identifier(self, block_identifier: str) -> str:
        """Strip and validate *block_identifier*.

        Args:
            block_identifier: A hex block hash or numeric block height string.

        Returns:
            The stripped, non-empty identifier.

        Raises:
            ValidationError: If the identifier is empty after stripping.
        """
        normalized = block_identifier.strip()
        if not normalized:
            raise ValidationError("Block identifier cannot be empty.")
        return normalized

    def _validate_days(self, days: int) -> int:
        """Validate the *days* parameter for the daily energy query.

        Args:
            days: Requested number of past UTC days.

        Returns:
            The validated value unchanged.

        Raises:
            ValidationError: If *days* is <= 0 or exceeds the 60-day hard cap.
        """
        if days <= 0:
            raise ValidationError("Days must be greater than 0.")
        if days > 60:
            raise ValidationError("Days cannot be greater than 60 to protect API limits.")
        return days

    def _validate_wallet_address(self, address: str) -> str:
        """Strip and validate a Bitcoin *address*.

        Args:
            address: A Base58 or Bech32 Bitcoin address.

        Returns:
            The stripped, non-empty address.

        Raises:
            ValidationError: If the address is empty after stripping.
        """
        normalized = address.strip()
        if not normalized:
            raise ValidationError("Wallet address cannot be empty.")
        return normalized

    def _energy_for_size(self, size_bytes: int) -> float:
        """Compute the energy estimate for a transaction of *size_bytes*.

        Applies the assignment energy model::

            energy_kwh = size_bytes × energy_cost_per_byte_kwh

        Args:
            size_bytes: Serialised transaction size in bytes.

        Returns:
            Estimated energy in KWh, rounded to 6 decimal places.

        Raises:
            ValidationError: If *size_bytes* is negative.
        """
        if size_bytes < 0:
            raise ValidationError("Transaction size cannot be negative.")
        return round(size_bytes * settings.energy_cost_per_byte_kwh, 6)

    async def _get_block_cached(self, block_hash: str) -> dict[str, Any]:
        """Return a normalised block dict, fetching from the API on a cache miss.

        The result is stored in ``_block_cache`` with the block's canonical hash
        as the key so subsequent lookups for the same block are O(1).

        Args:
            block_hash: Canonical block hash or height string accepted by
                ``BlockchainClient.get_block_by_hash``.

        Returns:
            Dict with keys: ``hash``, ``height``, ``tx`` (list of tx dicts).
        """
        cached = self._block_cache.get(block_hash)
        if cached is not None:
            return cached
        block = await self._client.get_block_by_hash(block_hash)
        self._block_cache.set(block_hash, block)
        return block

    async def get_latest_block(self) -> dict:
        """Return the hash and height of the current chain tip.

        Returns:
            Dict with keys ``hash`` (str) and ``height`` (int).
        """
        block = await self._client.get_latest_block()
        return {
            "hash": str(block.get("hash", "")),
            "height": int(block.get("height", 0)),
        }

    async def energy_per_transaction_for_block(self, block_identifier: str) -> BlockEnergySummary:
        """Return the per-transaction energy breakdown for a Bitcoin block.

        Accepts either a full hex block hash or a numeric block height string.
        Results are cached by block hash for ``block_cache_ttl_seconds``.

        Energy formula::

            tx.energy_kwh = tx.size_bytes × 4.56

        Args:
            block_identifier: A block hash (64 hex chars) or block height string.

        Returns:
            A :class:`BlockEnergySummary` containing per-transaction detail,
            aggregate totals, and CO₂ equivalent figures.

        Raises:
            ValidationError: If *block_identifier* is blank.
            BlockchainClientError: If the upstream API call fails after retries.
        """
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
            tx_energy = self._energy_for_size(tx_size)
            transactions.append(
                TransactionEnergy(
                    hash=tx_hash,
                    size_bytes=tx_size,
                    energy_kwh=tx_energy,
                    co2_equivalent_kg=round(tx_energy * settings.co2_per_kwh_kg, 6),
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
            co2_equivalent_kg=round(total_energy * settings.co2_per_kwh_kg, 6),
            transactions=transactions,
        )

    async def _daily_energy_for_date(self, day_start_utc: datetime) -> DailyEnergySummary:
        """Compute the energy summary for a single UTC calendar day.

        Uses ``BlockchainClient.get_blocks_by_day`` to walk backwards from the
        chain tip and collect all blocks whose timestamp falls within
        ``[day_start_utc, day_start_utc + 24 h)``.  The block-level ``size``
        field is used to sum energy without fetching individual transaction
        pages, avoiding O(blocks × pages) API calls.

        Results are stored in ``_daily_cache`` keyed by ISO date string.

        Args:
            day_start_utc: A timezone-aware (UTC) datetime representing the
                start of the target calendar day (00:00:00).

        Returns:
            A :class:`DailyEnergySummary` for that day.
        """
        cache_key = day_start_utc.date().isoformat()
        cached = self._daily_cache.get(cache_key)
        if cached is not None:
            return cached

        block_items = await self._client.get_blocks_by_day(day_start_utc)
        if not isinstance(block_items, list):
            raise BlockchainClientError("Unexpected blocks-by-day response format.")

        # Use block-level `size` (included in the /api/blocks/{height} chunk
        # response) to compute energy without fetching all transaction pages.
        # This is equivalent to summing individual tx sizes and avoids ~80
        # extra API calls per block that would otherwise trigger rate limits.
        tx_count = sum(int(b.get("tx_count", 0)) for b in block_items)
        total_size = sum(int(b.get("size", 0)) for b in block_items)
        total_energy = round(total_size * settings.energy_cost_per_byte_kwh, 6)
        avg_per_tx = round(total_energy / tx_count, 6) if tx_count else 0.0

        summary = DailyEnergySummary(
            date=day_start_utc.date().isoformat(),
            block_count=len(block_items),
            transaction_count=tx_count,
            total_energy_kwh=total_energy,
            average_energy_per_transaction_kwh=avg_per_tx,
            co2_equivalent_kg=round(total_energy * settings.co2_per_kwh_kg, 6),
        )
        self._daily_cache.set(cache_key, summary)
        return summary

    async def total_energy_consumption_last_days(self, days: int) -> list[DailyEnergySummary]:
        """Return daily energy summaries for the last *days* UTC calendar days.

        Uses a single backwards walk (``BlockchainClient.get_blocks_for_days``)
        to collect blocks for all uncached days in one pass, avoiding the
        O(N²) cost of N independent walks from the chain tip.

        Days that are already in the daily cache are returned immediately;
        only the uncached subset triggers a network call.

        Args:
            days: Number of past days to include (inclusive of today).  Must
                be between 1 and 60.

        Returns:
            List of :class:`DailyEnergySummary`, sorted ascending by date.

        Raises:
            ValidationError: If *days* is outside [1, 60].
            BlockchainClientError: If the upstream API call fails after retries.
        """
        days = self._validate_days(days)
        now = datetime.now(tz=UTC)

        dates: list[datetime] = [
            (now - timedelta(days=offset)).replace(hour=0, minute=0, second=0, microsecond=0)
            for offset in range(days)
        ]

        # Return immediately from cache when all days are already cached.
        cached_results: dict[str, DailyEnergySummary] = {}
        uncached_dates: list[datetime] = []
        for day in dates:
            cache_key = day.date().isoformat()
            hit = self._daily_cache.get(cache_key)
            if hit is not None:
                cached_results[cache_key] = hit
            else:
                uncached_dates.append(day)

        if uncached_dates:
            # Single backwards walk for ALL uncached days at once — avoids the
            # O(N × blocks_to_cover) cost of separate per-day walks from the tip.
            blocks_by_day = await self._client.get_blocks_for_days(uncached_dates)
            for day in uncached_dates:
                cache_key = day.date().isoformat()
                block_items = blocks_by_day.get(cache_key, [])
                tx_count = sum(int(b.get("tx_count", 0)) for b in block_items)
                total_size = sum(int(b.get("size", 0)) for b in block_items)
                total_energy = round(total_size * settings.energy_cost_per_byte_kwh, 6)
                avg_per_tx = round(total_energy / tx_count, 6) if tx_count else 0.0
                summary = DailyEnergySummary(
                    date=cache_key,
                    block_count=len(block_items),
                    transaction_count=tx_count,
                    total_energy_kwh=total_energy,
                    average_energy_per_transaction_kwh=avg_per_tx,
                    co2_equivalent_kg=round(total_energy * settings.co2_per_kwh_kg, 6),
                )
                self._daily_cache.set(cache_key, summary)
                cached_results[cache_key] = summary

        return sorted(cached_results.values(), key=lambda item: item.date)

    async def total_energy_by_wallet_address(self, address: str) -> WalletEnergySummary:
        """Return the total energy consumed by all recent transactions for *address*.

        Fetches up to 50 most recent confirmed transactions from the
        ``/api/address/{address}/txs`` endpoint.  Duplicate transaction hashes
        are silently deduplicated so each transaction is counted exactly once.

        Args:
            address: A valid Bitcoin address (Base58 or Bech32).

        Returns:
            A :class:`WalletEnergySummary` with total energy and CO₂ figures.

        Raises:
            ValidationError: If *address* is blank.
            BlockchainClientError: If the upstream API call fails after retries.
        """
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

        total_rounded = round(total, 6)
        return WalletEnergySummary(
            address=wallet,
            transaction_count=len(unique_hashes),
            total_energy_kwh=total_rounded,
            co2_equivalent_kg=round(total_rounded * settings.co2_per_kwh_kg, 6),
        )
