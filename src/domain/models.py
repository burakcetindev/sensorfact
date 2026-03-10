from dataclasses import dataclass


@dataclass(frozen=True)
class TransactionEnergy:
    hash: str
    size_bytes: int
    energy_kwh: float


@dataclass(frozen=True)
class BlockEnergySummary:
    block_hash: str
    block_height: int | None
    transaction_count: int
    total_energy_kwh: float
    energy_per_transaction_kwh: float
    transactions: list[TransactionEnergy]


@dataclass(frozen=True)
class DailyEnergySummary:
    date: str
    block_count: int
    transaction_count: int
    total_energy_kwh: float


@dataclass(frozen=True)
class WalletEnergySummary:
    address: str
    transaction_count: int
    total_energy_kwh: float
