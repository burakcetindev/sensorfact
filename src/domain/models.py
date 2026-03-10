from dataclasses import dataclass


@dataclass(frozen=True)
class TransactionEnergy:
    """Energy footprint of a single Bitcoin transaction.

    Attributes:
        hash:              The transaction identifier (txid).
        size_bytes:        Serialised size of the transaction in bytes.
        energy_kwh:        Estimated energy consumed (size_bytes × 4.56 KWh/byte).
        co2_equivalent_kg: CO₂ equivalent in kilograms (energy_kwh × co2_per_kwh_kg).
    """

    hash: str
    size_bytes: int
    energy_kwh: float
    co2_equivalent_kg: float


@dataclass(frozen=True)
class BlockEnergySummary:
    """Aggregated energy footprint of an entire Bitcoin block.

    Attributes:
        block_hash:                   The block hash (hex string).
        block_height:                 Block height in the chain, or ``None`` if unknown.
        transaction_count:            Number of valid transactions processed.
        total_energy_kwh:             Sum of energy across all transactions.
        energy_per_transaction_kwh:   Average energy per transaction.
        co2_equivalent_kg:            CO₂ equivalent for the whole block.
        transactions:                 Per-transaction breakdown.
    """

    block_hash: str
    block_height: int | None
    transaction_count: int
    total_energy_kwh: float
    energy_per_transaction_kwh: float
    co2_equivalent_kg: float
    transactions: list[TransactionEnergy]


@dataclass(frozen=True)
class DailyEnergySummary:
    """Aggregated energy footprint for a single UTC calendar day.

    Attributes:
        date:                               ISO-8601 date string (``YYYY-MM-DD``).
        block_count:                        Number of blocks mined that day.
        transaction_count:                  Total transactions across all blocks.
        total_energy_kwh:                   Total energy consumed that day.
        average_energy_per_transaction_kwh: Mean energy cost per transaction.
        co2_equivalent_kg:                  CO₂ equivalent for the whole day.
    """

    date: str
    block_count: int
    transaction_count: int
    total_energy_kwh: float
    average_energy_per_transaction_kwh: float
    co2_equivalent_kg: float


@dataclass(frozen=True)
class WalletEnergySummary:
    """Aggregated energy footprint of all recent transactions by a wallet.

    Attributes:
        address:           Bitcoin address.
        transaction_count: Number of unique confirmed transactions found.
        total_energy_kwh:  Total energy consumed by those transactions.
        co2_equivalent_kg: CO₂ equivalent for the wallet's activity.
    """

    address: str
    transaction_count: int
    total_energy_kwh: float
    co2_equivalent_kg: float
