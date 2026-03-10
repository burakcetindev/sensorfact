from ariadne import QueryType, gql, make_executable_schema

from src.clients.blockchain_client import BlockchainClient, BlockchainClientError
from src.domain.models import BlockEnergySummary, DailyEnergySummary, WalletEnergySummary
from src.services.energy_service import EnergyService, ValidationError

type_defs = gql(
    """
    type TransactionEnergy {
      hash: String!
      sizeBytes: Int!
      energyKwh: Float!
      co2EquivalentKg: Float!
    }

    type BlockEnergySummary {
      blockHash: String!
      blockHeight: Int
      transactionCount: Int!
      totalEnergyKwh: Float!
      energyPerTransactionKwh: Float!
      co2EquivalentKg: Float!
      transactions: [TransactionEnergy!]!
    }

    type DailyEnergySummary {
      date: String!
      blockCount: Int!
      transactionCount: Int!
      totalEnergyKwh: Float!
      averageEnergyPerTransactionKwh: Float!
      co2EquivalentKg: Float!
    }

    type WalletEnergySummary {
      address: String!
      transactionCount: Int!
      totalEnergyKwh: Float!
      co2EquivalentKg: Float!
    }

    type LatestBlock {
      hash: String!
      height: Int!
    }

    type Query {
      latestBlock: LatestBlock!
      energyPerTransactionForBlock(blockIdentifier: String!): BlockEnergySummary!
      totalEnergyConsumptionLastDays(days: Int!): [DailyEnergySummary!]!
      totalEnergyByWalletAddress(address: String!): WalletEnergySummary!
    }
    """
)

query = QueryType()


def _to_block(item: BlockEnergySummary) -> dict:
    """Convert a :class:`BlockEnergySummary` domain object to a GraphQL-ready dict.

    Renames snake_case fields to camelCase as expected by the SDL schema.
    """
    return {
        "blockHash": item.block_hash,
        "blockHeight": item.block_height,
        "transactionCount": item.transaction_count,
        "totalEnergyKwh": item.total_energy_kwh,
        "energyPerTransactionKwh": item.energy_per_transaction_kwh,
        "co2EquivalentKg": item.co2_equivalent_kg,
        "transactions": [
            {
                "hash": tx.hash,
                "sizeBytes": tx.size_bytes,
                "energyKwh": tx.energy_kwh,
                "co2EquivalentKg": tx.co2_equivalent_kg,
            }
            for tx in item.transactions
        ],
    }


def _to_daily(item: DailyEnergySummary) -> dict:
    """Convert a :class:`DailyEnergySummary` domain object to a GraphQL-ready dict."""
    return {
        "date": item.date,
        "blockCount": item.block_count,
        "transactionCount": item.transaction_count,
        "totalEnergyKwh": item.total_energy_kwh,
        "averageEnergyPerTransactionKwh": item.average_energy_per_transaction_kwh,
        "co2EquivalentKg": item.co2_equivalent_kg,
    }


def _to_wallet(item: WalletEnergySummary) -> dict:
    """Convert a :class:`WalletEnergySummary` domain object to a GraphQL-ready dict."""
    return {
        "address": item.address,
        "transactionCount": item.transaction_count,
        "totalEnergyKwh": item.total_energy_kwh,
        "co2EquivalentKg": item.co2_equivalent_kg,
    }


@query.field("latestBlock")
async def resolve_latest_block(_, info) -> dict:
    """GraphQL resolver for ``latestBlock``.

    Returns the hash and height of the current Bitcoin chain tip.
    """
    service: EnergyService = info.context["energy_service"]
    try:
        result = await service.get_latest_block()
        return result
    except BlockchainClientError as exc:
        raise ValueError(str(exc)) from exc


@query.field("energyPerTransactionForBlock")
async def resolve_energy_per_transaction_for_block(_, info, blockIdentifier: str) -> dict:
    """GraphQL resolver for ``energyPerTransactionForBlock``.

    Delegates to :meth:`EnergyService.energy_per_transaction_for_block` and
    maps the domain result to a camelCase dict for the GraphQL runtime.

    Args:
        blockIdentifier: Block hash or numeric height string.
    """
    service: EnergyService = info.context["energy_service"]
    try:
        result = await service.energy_per_transaction_for_block(blockIdentifier)
        return _to_block(result)
    except (ValidationError, BlockchainClientError) as exc:
        raise ValueError(str(exc)) from exc


@query.field("totalEnergyConsumptionLastDays")
async def resolve_total_energy_consumption_last_days(_, info, days: int) -> list[dict]:
    """GraphQL resolver for ``totalEnergyConsumptionLastDays``.

    Delegates to :meth:`EnergyService.total_energy_consumption_last_days` and
    returns a list of daily summary dicts sorted ascending by date.

    Args:
        days: Number of past days to include (1–60).
    """
    service: EnergyService = info.context["energy_service"]
    try:
        result = await service.total_energy_consumption_last_days(days)
        return [_to_daily(item) for item in result]
    except (ValidationError, BlockchainClientError) as exc:
        raise ValueError(str(exc)) from exc


@query.field("totalEnergyByWalletAddress")
async def resolve_total_energy_by_wallet_address(_, info, address: str) -> dict:
    """GraphQL resolver for ``totalEnergyByWalletAddress``.

    Delegates to :meth:`EnergyService.total_energy_by_wallet_address` and
    maps the wallet energy summary to a camelCase dict.

    Args:
        address: Bitcoin address (Base58 or Bech32).
    """
    service: EnergyService = info.context["energy_service"]
    try:
        result = await service.total_energy_by_wallet_address(address)
        return _to_wallet(result)
    except (ValidationError, BlockchainClientError) as exc:
        raise ValueError(str(exc)) from exc


def build_schema():
    """Build and return the executable Ariadne GraphQL schema.

    Combines the SDL type definitions with the ``QueryType`` resolver
    bindings into a schema object ready to be passed to Ariadne's
    ``graphql()`` function.
    """
    return make_executable_schema(type_defs, query)


def build_service() -> EnergyService:
    """Create and return a production-ready ``EnergyService`` instance.

    Wires up a live ``BlockchainClient`` backed by the mempool.space REST API.
    Called once at application startup in ``src/main.py``.
    """
    return EnergyService(BlockchainClient())
