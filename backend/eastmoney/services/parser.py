"""Parse Eastmoney sector ranking payloads into local snapshot values."""


def extract_ranking_rows(payload: dict) -> list[dict]:
    """Read the upstream `data.diff` list, including its occasional dict form."""
    data = payload.get('data') or {}
    if not isinstance(data, dict):
        return []
    rows = data.get('diff') or []
    if isinstance(rows, dict):
        return [row for row in rows.values() if isinstance(row, dict)]
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def parse_sector_row(row: dict) -> dict | None:
    """Discard a row without the identity or primary fund-flow value."""
    sector_code = row.get('f12')
    main_net_inflow = optional_number(row, 'f62')
    if not sector_code or main_net_inflow is None:
        return None
    return {
        'sector_code': str(sector_code),
        'sector_name': str(row.get('f14') or ''),
        'latest_index': optional_number(row, 'f2'),
        'change_pct': optional_number(row, 'f3'),
        'main_net_inflow': main_net_inflow,
        'main_net_inflow_ratio': optional_number(row, 'f184'),
        'super_large_net_inflow': optional_number(row, 'f66'),
        'large_net_inflow': optional_number(row, 'f72'),
        'medium_net_inflow': optional_number(row, 'f78'),
        'small_net_inflow': optional_number(row, 'f84'),
    }


def optional_number(row: dict, field_name: str):
    value = row.get(field_name)
    return None if value in (None, '-', '') else value
