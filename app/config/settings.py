"""
StockQueen V1 - Configuration Module
Centralized configuration management using Pydantic Settings
"""

from pydantic_settings import BaseSettings
from pydantic import Field
from typing import Optional


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""
    
    # Application
    app_env: str = Field(default="development", alias="APP_ENV")
    app_name: str = Field(default="StockQueen", alias="APP_NAME")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    timezone: str = Field(default="Pacific/Auckland", alias="TIMEZONE")
    
    # Supabase
    supabase_url: str = Field(alias="SUPABASE_URL")
    supabase_service_key: str = Field(alias="SUPABASE_SERVICE_KEY")
    
    # DeepSeek AI
    deepseek_api_key: Optional[str] = Field(default=None, alias="DEEPSEEK_API_KEY")
    deepseek_model: str = Field(default="deepseek-chat", alias="DEEPSEEK_MODEL")
    deepseek_base_url: str = Field(default="https://api.deepseek.com", alias="DEEPSEEK_BASE_URL")
    
    # Tiger Open API (official SDK)
    tiger_id: Optional[str] = Field(default=None, alias="TIGER_ID")
    tiger_account: Optional[str] = Field(default=None, alias="TIGER_ACCOUNT")
    tiger_private_key: Optional[str] = Field(default=None, alias="TIGER_PRIVATE_KEY")
    
    # Twilio
    twilio_account_sid: Optional[str] = Field(default=None, alias="TWILIO_ACCOUNT_SID")
    twilio_auth_token: Optional[str] = Field(default=None, alias="TWILIO_AUTH_TOKEN")
    twilio_phone_from: Optional[str] = Field(default=None, alias="TWILIO_PHONE_FROM")
    twilio_phone_to: Optional[str] = Field(default=None, alias="TWILIO_PHONE_TO")
    
    # RSS Feeds
    pr_newswire_url: str = Field(
        default="https://www.prnewswire.com/rss/",
        alias="PR_NEWSWIRE_URL"
    )
    fda_url: str = Field(
        default="https://www.fda.gov/about-fda/contact-fda/rss-feeds",
        alias="FDA_URL"
    )
    
    # Feishu (Notification Service)
    feishu_webhook_url: Optional[str] = Field(default=None, alias="FEISHU_WEBHOOK_URL")
    feishu_app_secret: Optional[str] = Field(default=None, alias="FEISHU_APP_SECRET")
    feishu_app_id: Optional[str] = Field(default=None, alias="FEISHU_APP_ID")
    feishu_receive_id: Optional[str] = Field(default=None, alias="FEISHU_RECEIVE_ID")
    
    # OpenClaw (Notification Service)
    openclaw_webhook_url: Optional[str] = Field(default=None, alias="OPENCLAW_WEBHOOK_URL")
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


# Risk Management Constants (Hardcoded as per requirements)
class RiskConfig:
    """Hardcoded risk management configuration"""
    MAX_POSITIONS: int = 2
    RISK_PER_TRADE: float = 0.10  # 10% of account equity
    MAX_DRAWDOWN: float = 0.15    # 15% max drawdown
    CONSECUTIVE_LOSS_LIMIT: int = 2
    
    # Signal Thresholds (Optimized based on backtesting)
    LONG_MIN_GAIN: float = 0.08       # 8% gain for long signal
    SHORT_MIN_DROP: float = -0.10     # -10% drop for short signal
    VOLUME_MULTIPLIER: float = 5.0    # 5x average volume
    MIN_MARKET_CAP: float = 500_000_000   # $500M
    MAX_MARKET_CAP: float = 4_000_000_000 # $4B
    
    # Short Signal Toggle (requires real-time pre/post market data)
    ENABLE_SHORT_SIGNALS: bool = False  # Enable after Tiger API integration

    # === Geopolitical Crisis Signal Thresholds ===
    # 地缘政治危机信号阈值（比医药低，因为大盘股波动幅度小）
    GEO_LONG_MIN_GAIN: float = 0.03       # 3% gain for long (oil/gold/defense)
    GEO_SHORT_MIN_DROP: float = -0.04     # -4% drop for short (airlines/cruise)
    GEO_VOLUME_MULTIPLIER: float = 1.5    # 1.5x average volume (大盘股量能要求低)
    GEO_MIN_MARKET_CAP: float = 0         # No minimum (include ETFs)
    GEO_MAX_MARKET_CAP: float = 0         # No maximum (include mega caps)
    GEO_ENABLE_SHORT_SIGNALS: bool = True  # 地缘危机开启做空航空/邮轮





# Keyword Filter Configuration
class KeywordConfig:
    """Keywords for filtering news events"""
    KEYWORDS = [
        "phase 2",
        "phase 3",
        "phase2",
        "phase3",
        "topline",
        "fda approval",
        "crl",
        "clinical trial result",
        "endpoint",
        "complete response letter",
    ]

    # 地缘政治/能源危机关键词
    GEO_KEYWORDS = [
        "strait of hormuz",
        "hormuz",
        "霍尔木兹",
        "iran sanctions",
        "iran war",
        "iran strike",
        "iran attack",
        "oil embargo",
        "oil supply disruption",
        "oil tanker attack",
        "crude oil surge",
        "brent crude",
        "wti crude",
        "opec production",
        "opec cut",
        "shipping disruption",
        "maritime insurance",
        "persian gulf",
        "middle east conflict",
        "middle east crisis",
        "defense spending",
        "military escalation",
        "gold safe haven",
        "energy crisis",
        "lng supply",
        "oil price",
        "oil shock",
    ]


# Event Type Enumeration
VALID_EVENT_TYPES = [
    "Phase3_Positive",
    "Phase3_Negative",
    "FDA_Approval",
    "CRL",
    "Phase2_Positive",
    "Phase2_Negative",
    "Other",
]

VALID_DIRECTION_BIAS = ["long", "short", "none"]


# Global settings instance
settings = Settings()
