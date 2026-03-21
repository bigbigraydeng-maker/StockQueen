"""
[已迁移] FMP 客户端已替换为 Massive 数据源。
本文件仅作向后兼容的重新导出层，所有逻辑已移至 massive_client.py。
"""

import logging
from app.services.massive_client import (  # noqa: F401
    get_earnings_history,
    get_company_profile,
    get_ratios_ttm,
    get_income_statement,
    get_cash_flow_statement,
    batch_get_earnings,
    batch_get_profiles,
    batch_get_ratios,
    batch_get_income,
    batch_get_cashflow,
)

logger = logging.getLogger(__name__)
