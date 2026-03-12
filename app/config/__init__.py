"""
StockQueen V1 - Config Package
"""

from app.config.settings import Settings, settings
from app.config.settings import RiskConfig, KeywordConfig
from app.config.settings import VALID_EVENT_TYPES, VALID_DIRECTION_BIAS
from app.config.pharma_watchlist import PHARMA_WATCHLIST, PHARMA_KEYWORDS
from app.config.rotation_watchlist import RotationConfig

__all__ = [
    'Settings',
    'settings',
    'RiskConfig',
    'KeywordConfig',
    'RotationConfig',
    'VALID_EVENT_TYPES',
    'VALID_DIRECTION_BIAS',
    'PHARMA_WATCHLIST',
    'PHARMA_KEYWORDS',
]
