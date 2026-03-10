"""Unit tests for all input validation rules in EnergyService."""
from __future__ import annotations

import pytest

from src.services.energy_service import EnergyService, ValidationError
from src.clients.blockchain_client import BlockchainClient


# ---------------------------------------------------------------------------
# Helper — build a service with no HTTP needed for validation-only tests
# ---------------------------------------------------------------------------

def _service() -> EnergyService:
    """Return an EnergyService whose client is never called in these tests."""
    # We pass a stalling getter — if a test accidentally triggers a network
    # call the test will fail with a KeyError, not silently pass.
    async def _no_call(path: str):
        raise AssertionError(f"Unexpected network call to: {path}")

    return EnergyService(BlockchainClient(http_getter=_no_call))


# ---------------------------------------------------------------------------
# _validate_block_identifier
# ---------------------------------------------------------------------------

class TestValidateBlockIdentifier:
    def setup_method(self):
        self.svc = _service()

    def test_empty_string_raises(self):
        with pytest.raises(ValidationError, match="cannot be empty"):
            self.svc._validate_block_identifier("")

    def test_whitespace_only_raises(self):
        with pytest.raises(ValidationError, match="cannot be empty"):
            self.svc._validate_block_identifier("   ")

    def test_valid_hash_returned_stripped(self):
        h = "00000000839a8e6886ab5951d76f411475428afc90947ee320161bbf18eb6048"
        assert self.svc._validate_block_identifier(h) == h

    def test_hash_with_surrounding_whitespace_is_stripped(self):
        h = "abc123"
        assert self.svc._validate_block_identifier(f"  {h}  ") == h

    def test_numeric_height_string_is_valid(self):
        assert self.svc._validate_block_identifier("840000") == "840000"


# ---------------------------------------------------------------------------
# _validate_days
# ---------------------------------------------------------------------------

class TestValidateDays:
    def setup_method(self):
        self.svc = _service()

    def test_zero_raises(self):
        with pytest.raises(ValidationError, match="greater than 0"):
            self.svc._validate_days(0)

    def test_negative_raises(self):
        with pytest.raises(ValidationError, match="greater than 0"):
            self.svc._validate_days(-5)

    def test_above_max_raises(self):
        with pytest.raises(ValidationError, match="60"):
            self.svc._validate_days(61)

    def test_exactly_sixty_is_valid(self):
        assert self.svc._validate_days(60) == 60

    def test_one_is_valid(self):
        assert self.svc._validate_days(1) == 1

    def test_mid_range_is_valid(self):
        assert self.svc._validate_days(30) == 30


# ---------------------------------------------------------------------------
# _validate_wallet_address
# ---------------------------------------------------------------------------

class TestValidateWalletAddress:
    def setup_method(self):
        self.svc = _service()

    def test_empty_string_raises(self):
        with pytest.raises(ValidationError, match="cannot be empty"):
            self.svc._validate_wallet_address("")

    def test_whitespace_only_raises(self):
        with pytest.raises(ValidationError, match="cannot be empty"):
            self.svc._validate_wallet_address("   ")

    def test_valid_address_returned_stripped(self):
        addr = "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"
        assert self.svc._validate_wallet_address(addr) == addr

    def test_address_with_whitespace_is_stripped(self):
        addr = "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"
        assert self.svc._validate_wallet_address(f"\t{addr}\n") == addr


# ---------------------------------------------------------------------------
# _energy_for_size
# ---------------------------------------------------------------------------

class TestEnergyForSize:
    def setup_method(self):
        self.svc = _service()

    def test_negative_size_raises(self):
        with pytest.raises(ValidationError, match="negative"):
            self.svc._energy_for_size(-1)

    def test_zero_size_returns_zero(self):
        assert self.svc._energy_for_size(0) == 0.0

    def test_known_value(self):
        # 100 bytes × 4.56 KWh/byte = 456.0 KWh
        assert self.svc._energy_for_size(100) == pytest.approx(456.0, rel=1e-6)

    def test_result_rounded_to_six_places(self):
        result = self.svc._energy_for_size(1)  # 4.56 KWh — already exact
        assert result == pytest.approx(4.56, rel=1e-9)

    def test_large_transaction(self):
        # 100 000 bytes × 4.56 = 456 000 KWh
        assert self.svc._energy_for_size(100_000) == pytest.approx(456_000.0, rel=1e-6)
