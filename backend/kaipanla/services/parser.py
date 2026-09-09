"""Map Kaipanla `RealRankingInfo` array rows into typed sector values."""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation


@dataclass(frozen=True)
class KaipanlaSectorFundFlowRow:
    sector_code: str
    sector_name: str
    change_pct: Decimal | None
    main_net_inflow: Decimal
    main_buy: Decimal | None
    main_sell: Decimal | None
    large_order_net_inflow: Decimal | None
    volume_ratio: Decimal | None
    turnover_amount: Decimal | None
    float_market_cap: Decimal | None
    total_market_cap: Decimal | None


_EMPTY_NUMBERS = {None, '', '-', '--', 'null', 'NULL'}


def optional_decimal(value) -> Decimal | None:
    if value in _EMPTY_NUMBERS:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def parse_sector_row(item) -> KaipanlaSectorFundFlowRow | None:
    """Return no row for incomplete/invalid upstream records.

    Index mapping follows the verified RealRankingInfo payload: code/name at 0/1,
    change at 3, turnover at 5, main flow at 6–8, volume ratio at 9,
    float market cap at 10, large-order flow at 12 and total market cap at 13.
    """
    if not isinstance(item, (list, tuple)) or len(item) < 14:
        return None
    sector_code = str(item[0] or '').strip()
    main_net_inflow = optional_decimal(item[6])
    if not sector_code or main_net_inflow is None:
        return None
    return KaipanlaSectorFundFlowRow(
        sector_code=sector_code,
        sector_name=str(item[1] or '').strip(),
        change_pct=optional_decimal(item[3]),
        main_net_inflow=main_net_inflow,
        main_buy=optional_decimal(item[7]),
        main_sell=optional_decimal(item[8]),
        large_order_net_inflow=optional_decimal(item[12]),
        volume_ratio=optional_decimal(item[9]),
        turnover_amount=optional_decimal(item[5]),
        float_market_cap=optional_decimal(item[10]),
        total_market_cap=optional_decimal(item[13]),
    )
