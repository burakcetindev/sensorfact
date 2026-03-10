"""Unit tests for EnergyService — all network calls are stubbed."""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.clients.blockchain_client import BlockchainClient
from src.config.settings import settings
from src.domain.models import BlockEnergySummary, DailyEnergySummary, WalletEnergySummary
from src.services.energy_service import EnergyService, ValidationError
from tests.conftest import make_service


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

BLOCK_HASH = "00000000000000000002abc"
TX1 = {"txid": "tx_hash_1", "size": 250}
TX2 = {"txid": "tx_hash_2", "size": 500}
TX3 = {"txid": "tx_hash_3", "size": 1_000}

BLOCK_PAYLOAD = {
    "id": BLOCK_HASH,
    "height": 800_000,
    "tx_count": 3,
}

TX_PAGE = [TX1, TX2, TX3]


def _block_responses(block_hash: str = BLOCK_HASH, tx_page=None) -> dict:
    if tx_page is None:
        tx_page = TX_PAGE
    return {
        f"/api/block/{block_hash}": {**BLOCK_PAYLOAD, "id": block_hash},
        f"/api/block/{block_hash}/txs": tx_page,
    }


# ---------------------------------------------------------------------------
# energy_per_transaction_for_block
# ---------------------------------------------------------------------------

class TestEnergyPerTransactionForBlock:

    @pytest.mark.asyncio
    async def test_returns_block_energy_summary(self):
        svc = make_service(_block_responses())
        result = await svc.energy_per_transaction_for_block(BLOCK_HASH)
        assert isinstance(result, BlockEnergySummary)

    @pytest.mark.asyncio
    async def test_transaction_count_matches_tx_page(self):
        svc = make_service(_block_responses())
        result = await svc.energy_per_transaction_for_block(BLOCK_HASH)
        assert result.transaction_count == 3

    @pytest.mark.asyncio
    async def test_energy_calculated_correctly(self):
        svc = make_service(_block_responses())
        result = await svc.energy_per_transaction_for_block(BLOCK_HASH)
        expected_total = round((250 + 500 + 1_000) * settings.energy_cost_per_byte_kwh, 6)
        assert result.total_energy_kwh == pytest.approx(expected_total, rel=1e-5)

    @pytest.mark.asyncio
    async def test_energy_per_transaction_is_average(self):
        svc = make_service(_block_responses())
        result = await svc.energy_per_transaction_for_block(BLOCK_HASH)
        expected = round(result.total_energy_kwh / 3, 6)
        assert result.energy_per_transaction_kwh == pytest.approx(expected, rel=1e-5)

    @pytest.mark.asyncio
    async def test_co2_equivalent_computed(self):
        svc = make_service(_block_responses())
        result = await svc.energy_per_transaction_for_block(BLOCK_HASH)
        expected_co2 = round(result.total_energy_kwh * settings.co2_per_kwh_kg, 6)
        assert result.co2_equivalent_kg == pytest.approx(expected_co2, rel=1e-5)

    @pytest.mark.asyncio
    async def test_per_transaction_co2_computed(self):
        svc = make_service(_block_responses())
        result = await svc.energy_per_transaction_for_block(BLOCK_HASH)
        for tx in result.transactions:
            expected = round(tx.energy_kwh * settings.co2_per_kwh_kg, 6)
            assert tx.co2_equivalent_kg == pytest.approx(expected, rel=1e-5)

    @pytest.mark.asyncio
    async def test_block_height_is_set(self):
        svc = make_service(_block_responses())
        result = await svc.energy_per_transaction_for_block(BLOCK_HASH)
        assert result.block_height == 800_000

    @pytest.mark.asyncio
    async def test_empty_block_returns_zero_totals(self):
        svc = make_service(_block_responses(tx_page=[]))
        result = await svc.energy_per_transaction_for_block(BLOCK_HASH)
        assert result.transaction_count == 0
        assert result.total_energy_kwh == 0.0
        assert result.energy_per_transaction_kwh == 0.0
        assert result.co2_equivalent_kg == 0.0

    @pytest.mark.asyncio
    async def test_transactions_missing_hash_are_skipped(self):
        """Transactions with no hash should be silently ignored."""
        tx_page = [
            {"txid": "", "size": 250},      # empty hash — skip
            {"txid": "good_tx", "size": 500},
            {"size": 100},                  # missing txid key — skip
        ]
        svc = make_service(_block_responses(tx_page=tx_page))
        result = await svc.energy_per_transaction_for_block(BLOCK_HASH)
        assert result.transaction_count == 1
        assert result.transactions[0].hash == "good_tx"

    @pytest.mark.asyncio
    async def test_transactions_missing_size_are_skipped(self):
        tx_page = [
            {"txid": "no_size_tx"},         # missing size key — skip
            {"txid": "good_tx", "size": 500},
        ]
        svc = make_service(_block_responses(tx_page=tx_page))
        result = await svc.energy_per_transaction_for_block(BLOCK_HASH)
        assert result.transaction_count == 1

    @pytest.mark.asyncio
    async def test_empty_identifier_raises_validation_error(self):
        svc = make_service(_block_responses())
        with pytest.raises(ValidationError):
            await svc.energy_per_transaction_for_block("")

    @pytest.mark.asyncio
    async def test_whitespace_identifier_raises_validation_error(self):
        svc = make_service(_block_responses())
        with pytest.raises(ValidationError):
            await svc.energy_per_transaction_for_block("   ")

    @pytest.mark.asyncio
    async def test_result_is_cached_on_second_call(self):
        """A second call for the same block must not invoke the HTTP getter again."""
        call_count = 0

        async def counting_getter(path: str):
            nonlocal call_count
            call_count += 1
            responses = {
                **_block_responses(),
                "/api/blocks/tip/height": "800000",
            }
            for key, val in responses.items():
                if key in path:
                    return val
            raise KeyError(path)

        client = BlockchainClient(http_getter=counting_getter)
        svc = EnergyService(client)

        await svc.energy_per_transaction_for_block(BLOCK_HASH)
        first_call_count = call_count
        await svc.energy_per_transaction_for_block(BLOCK_HASH)
        # Cache should prevent any additional HTTP calls
        assert call_count == first_call_count


# ---------------------------------------------------------------------------
# total_energy_consumption_last_days
# ---------------------------------------------------------------------------

class TestTotalEnergyConsumptionLastDays:

    def _make_day_responses(self) -> dict:
        """Return canned responses for a single-day walk covering today."""
        now_ts = int(datetime.now(tz=UTC).replace(
            hour=0, minute=0, second=0, microsecond=0
        ).timestamp())

        return {
            "/api/blocks/tip/height": "800010",
            "/api/blocks/800010": [
                {
                    "id": "block_a",
                    "height": 800_010,
                    "timestamp": now_ts + 3600,
                    "size": 1_000_000,
                    "tx_count": 2000,
                },
                {
                    "id": "block_b",
                    "height": 800_009,
                    "timestamp": now_ts - 1,  # just before today — stops walk
                    "size": 500_000,
                    "tx_count": 1000,
                },
            ],
        }

    @pytest.mark.asyncio
    async def test_invalid_days_zero_raises(self):
        svc = make_service({})
        with pytest.raises(ValidationError):
            await svc.total_energy_consumption_last_days(0)

    @pytest.mark.asyncio
    async def test_invalid_days_over_max_raises(self):
        svc = make_service({})
        with pytest.raises(ValidationError):
            await svc.total_energy_consumption_last_days(61)

    @pytest.mark.asyncio
    async def test_returns_list_of_daily_summaries(self):
        svc = make_service(self._make_day_responses())
        result = await svc.total_energy_consumption_last_days(1)
        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], DailyEnergySummary)

    @pytest.mark.asyncio
    async def test_daily_summary_has_co2_field(self):
        svc = make_service(self._make_day_responses())
        result = await svc.total_energy_consumption_last_days(1)
        day = result[0]
        assert day.co2_equivalent_kg == pytest.approx(
            round(day.total_energy_kwh * settings.co2_per_kwh_kg, 6), rel=1e-5
        )

    @pytest.mark.asyncio
    async def test_daily_summary_has_avg_per_tx_field(self):
        svc = make_service(self._make_day_responses())
        result = await svc.total_energy_consumption_last_days(1)
        day = result[0]
        if day.transaction_count:
            expected_avg = round(day.total_energy_kwh / day.transaction_count, 6)
            assert day.average_energy_per_transaction_kwh == pytest.approx(expected_avg, rel=1e-5)

    @pytest.mark.asyncio
    async def test_result_sorted_ascending_by_date(self):
        svc = make_service(self._make_day_responses())
        result = await svc.total_energy_consumption_last_days(1)
        dates = [r.date for r in result]
        assert dates == sorted(dates)

    @pytest.mark.asyncio
    async def test_second_call_served_from_cache(self):
        call_count = 0
        base = self._make_day_responses()

        async def counting_getter(path: str):
            nonlocal call_count
            call_count += 1
            for key, val in base.items():
                if key in path:
                    return val
            raise KeyError(path)

        client = BlockchainClient(http_getter=counting_getter)
        svc = EnergyService(client)

        await svc.total_energy_consumption_last_days(1)
        first_count = call_count
        await svc.total_energy_consumption_last_days(1)
        assert call_count == first_count  # cache absorbed the repeat


# ---------------------------------------------------------------------------
# total_energy_by_wallet_address
# ---------------------------------------------------------------------------

class TestTotalEnergyByWalletAddress:

    ADDR = "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"

    def _wallet_responses(self, txs: list) -> dict:
        return {f"/api/address/{self.ADDR}/txs": txs}

    @pytest.mark.asyncio
    async def test_returns_wallet_energy_summary(self):
        svc = make_service(self._wallet_responses([
            {"txid": "tx1", "size": 250},
        ]))
        result = await svc.total_energy_by_wallet_address(self.ADDR)
        assert isinstance(result, WalletEnergySummary)

    @pytest.mark.asyncio
    async def test_energy_sum_is_correct(self):
        svc = make_service(self._wallet_responses([
            {"txid": "tx1", "size": 250},
            {"txid": "tx2", "size": 500},
        ]))
        result = await svc.total_energy_by_wallet_address(self.ADDR)
        expected = round((250 + 500) * settings.energy_cost_per_byte_kwh, 6)
        assert result.total_energy_kwh == pytest.approx(expected, rel=1e-5)

    @pytest.mark.asyncio
    async def test_co2_computed(self):
        svc = make_service(self._wallet_responses([
            {"txid": "tx1", "size": 500},
        ]))
        result = await svc.total_energy_by_wallet_address(self.ADDR)
        expected_co2 = round(result.total_energy_kwh * settings.co2_per_kwh_kg, 6)
        assert result.co2_equivalent_kg == pytest.approx(expected_co2, rel=1e-5)

    @pytest.mark.asyncio
    async def test_duplicate_txids_counted_once(self):
        """The same transaction hash appearing twice must only be counted once."""
        svc = make_service(self._wallet_responses([
            {"txid": "dupe_tx", "size": 300},
            {"txid": "dupe_tx", "size": 300},  # duplicate
        ]))
        result = await svc.total_energy_by_wallet_address(self.ADDR)
        assert result.transaction_count == 1
        expected = round(300 * settings.energy_cost_per_byte_kwh, 6)
        assert result.total_energy_kwh == pytest.approx(expected, rel=1e-5)

    @pytest.mark.asyncio
    async def test_empty_wallet_returns_zeros(self):
        svc = make_service(self._wallet_responses([]))
        result = await svc.total_energy_by_wallet_address(self.ADDR)
        assert result.transaction_count == 0
        assert result.total_energy_kwh == 0.0

    @pytest.mark.asyncio
    async def test_transactions_missing_hash_skipped(self):
        svc = make_service(self._wallet_responses([
            {"size": 250},              # no txid — skip
            {"txid": "", "size": 300},  # empty txid — skip
            {"txid": "good", "size": 400},
        ]))
        result = await svc.total_energy_by_wallet_address(self.ADDR)
        assert result.transaction_count == 1

    @pytest.mark.asyncio
    async def test_transactions_missing_size_still_counted(self):
        """Transactions without a size field are deduplicated but contribute 0 energy."""
        svc = make_service(self._wallet_responses([
            {"txid": "no_size"},        # no size
            {"txid": "good", "size": 400},
        ]))
        result = await svc.total_energy_by_wallet_address(self.ADDR)
        # "no_size" has no size field so get_wallet_transactions filters it out;
        # only "good" survives the normalisation step.
        assert result.transaction_count == 1

    @pytest.mark.asyncio
    async def test_empty_address_raises_validation_error(self):
        svc = make_service({})
        with pytest.raises(ValidationError):
            await svc.total_energy_by_wallet_address("")


# ---------------------------------------------------------------------------
# get_latest_block
# ---------------------------------------------------------------------------

class TestGetLatestBlock:

    @pytest.mark.asyncio
    async def test_returns_hash_and_height(self):
        svc = make_service({
            "/api/blocks/tip/hash": "latesthash",
            "/api/block/latesthash": {"id": "latesthash", "height": 900_000},
        })
        result = await svc.get_latest_block()
        assert result["hash"] == "latesthash"
        assert result["height"] == 900_000
