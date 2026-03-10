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
    }

    type BlockEnergySummary {
      blockHash: String!
      blockHeight: Int
      transactionCount: Int!
      totalEnergyKwh: Float!
      energyPerTransactionKwh: Float!
      transactions: [TransactionEnergy!]!
    }

    type DailyEnergySummary {
      date: String!
      blockCount: Int!
      transactionCount: Int!
      totalEnergyKwh: Float!
    }

    type WalletEnergySummary {
      address: String!
      transactionCount: Int!
      totalEnergyKwh: Float!
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
    return {
        "blockHash": item.block_hash,
        "blockHeight": item.block_height,
        "transactionCount": item.transaction_count,
        "totalEnergyKwh": item.total_energy_kwh,
        "energyPerTransactionKwh": item.energy_per_transaction_kwh,
        "transactions": [
            {
                "hash": tx.hash,
                "sizeBytes": tx.size_bytes,
                "energyKwh": tx.energy_kwh,
            }
            for tx in item.transactions
        ],
    }


def _to_daily(item: DailyEnergySummary) -> dict:
    return {
        "date": item.date,
        "blockCount": item.block_count,
        "transactionCount": item.transaction_count,
        "totalEnergyKwh": item.total_energy_kwh,
    }


def _to_wallet(item: WalletEnergySummary) -> dict:
    return {
        "address": item.address,
        "transactionCount": item.transaction_count,
        "totalEnergyKwh": item.total_energy_kwh,
    }


@query.field("latestBlock")
async def resolve_latest_block(_, info) -> dict:
    service: EnergyService = info.context["energy_service"]
    try:
        result = await service.get_latest_block()
        return result
    except BlockchainClientError as exc:
        raise ValueError(str(exc)) from exc


@query.field("energyPerTransactionForBlock")
async def resolve_energy_per_transaction_for_block(_, info, blockIdentifier: str) -> dict:
    service: EnergyService = info.context["energy_service"]
    try:
        result = await service.energy_per_transaction_for_block(blockIdentifier)
        return _to_block(result)
    except (ValidationError, BlockchainClientError) as exc:
        raise ValueError(str(exc)) from exc


@query.field("totalEnergyConsumptionLastDays")
async def resolve_total_energy_consumption_last_days(_, info, days: int) -> list[dict]:
    service: EnergyService = info.context["energy_service"]
    try:
        result = await service.total_energy_consumption_last_days(days)
        return [_to_daily(item) for item in result]
    except (ValidationError, BlockchainClientError) as exc:
        raise ValueError(str(exc)) from exc


@query.field("totalEnergyByWalletAddress")
async def resolve_total_energy_by_wallet_address(_, info, address: str) -> dict:
    service: EnergyService = info.context["energy_service"]
    try:
        result = await service.total_energy_by_wallet_address(address)
        return _to_wallet(result)
    except (ValidationError, BlockchainClientError) as exc:
        raise ValueError(str(exc)) from exc


def build_schema():
    return make_executable_schema(type_defs, query)


def build_service() -> EnergyService:
    return EnergyService(BlockchainClient())
