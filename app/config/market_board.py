"""
后台「整体大盘」监控分组配置。

说明：
- 行情源为 Massive 美股快照；国债名义收益率（如 FRED DGS2/DGS10）、MOVE、VVIX、VXN、外汇即期等
  若需数值级精度，请配合 TradingView / FRED。
- 对无单一股票 ticker 的宏观变量，使用高流动性 ETF 作为「方向/风险偏好」近似，并在 note 中注明。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple


@dataclass(frozen=True)
class MarketBoardRow:
    """一行标的：展示名 + 实际拉取 ticker。"""

    ticker: str
    label: str
    note: str | None = None


@dataclass(frozen=True)
class MarketBoardSection:
    id: str
    title: str
    subtitle: str | None
    rows: Tuple[MarketBoardRow, ...]


# 四屏精简版（与用户「实用精简版」对齐，并略作可交易性修正）
SECTIONS: Tuple[MarketBoardSection, ...] = (
    MarketBoardSection(
        id="risk",
        title="① 风险偏好 · 权益",
        subtitle="SPY/纳指/小盘/半导体 + 波动率 ETF 近似",
        rows=(
            MarketBoardRow("SPY", "SPY", "标普500 ETF"),
            MarketBoardRow("QQQ", "QQQ", "纳指100"),
            MarketBoardRow("IWM", "IWM", "罗素2000 / 小盘"),
            MarketBoardRow("SMH", "SMH", "半导体"),
            MarketBoardRow("DIA", "DIA", "道指30"),
            MarketBoardRow("VIXY", "VIXY", "VIX 短期期货 ETF（非 VIX 现货）"),
        ),
    ),
    MarketBoardSection(
        id="rates_fx",
        title="② 宏观利率 · 久期 · 美元",
        subtitle="SHY≈前端久期、IEF≈7–10Y 桶、TLT 长端；UUP 美元多头",
        rows=(
            MarketBoardRow("SHY", "SHY", "1–3Y 国债 ETF（近似观察短端利率敏感度）"),
            MarketBoardRow("IEF", "IEF", "7–10Y 国债 ETF（近似 10Y 久期桶）"),
            MarketBoardRow("TLT", "TLT", "20+Y 国债"),
            MarketBoardRow("EDV", "EDV", "超长久期国债（30Y 久期风格）"),
            MarketBoardRow("UUP", "UUP", "美元指数多头 ETF（近似 DXY 方向）"),
            MarketBoardRow("FXY", "FXY", "日元 ETF（与 USDJPY 大体反向，套息情绪参考）"),
        ),
    ),
    MarketBoardSection(
        id="credit",
        title="③ 信用 · 流动性 · 货基",
        subtitle="HYG/LQD 风险偏好；SGOV/SHV 现金锚；BND/AGG 综合债",
        rows=(
            MarketBoardRow("HYG", "HYG", "高收益债 / 风险意愿"),
            MarketBoardRow("LQD", "LQD", "投资级公司债"),
            MarketBoardRow("SGOV", "SGOV", "超短国债 ETF"),
            MarketBoardRow("SHV", "SHV", "短久期国债"),
            MarketBoardRow("BND", "BND", "综合债"),
            MarketBoardRow("AGG", "AGG", "综合债（另一主流）"),
        ),
    ),
    MarketBoardSection(
        id="commodities",
        title="④ 商品 · 通胀锚",
        subtitle="金/银/油/铜/气 + 美元",
        rows=(
            MarketBoardRow("GLD", "GLD", "黄金"),
            MarketBoardRow("SLV", "SLV", "白银"),
            MarketBoardRow("USO", "USO", "原油"),
            MarketBoardRow("CPER", "CPER", "铜（Dr. Copper ETF）"),
            MarketBoardRow("UNG", "UNG", "天然气（波动大）"),
            MarketBoardRow("UDN", "UDN", "美元指数空头（与 UUP 对观）"),
        ),
    ),
    MarketBoardSection(
        id="sectors",
        title="⑤ 行业风向标",
        subtitle="金融 / 科技 / 能源 / 高 Beta 成长",
        rows=(
            MarketBoardRow("XLF", "XLF", "金融"),
            MarketBoardRow("XLK", "XLK", "科技板块"),
            MarketBoardRow("XLE", "XLE", "能源"),
            MarketBoardRow("ARKK", "ARKK", "高弹性成长情绪"),
        ),
    ),
    MarketBoardSection(
        id="fx_etfs",
        title="⑥ 外汇联动（ETF 近似）",
        subtitle="即期汇率请用专业终端；此处仅 ETF 方向参考",
        rows=(
            MarketBoardRow("FXE", "FXE", "欧元现货 ETF（EUR 方向）"),
            MarketBoardRow("CYB", "CYB", "人民币 ETF（离岸情绪参考）"),
        ),
    ),
)


def all_board_tickers() -> List[str]:
    """去重并保持大致板块顺序。"""
    seen: set[str] = set()
    out: List[str] = []
    for sec in SECTIONS:
        for r in sec.rows:
            t = r.ticker.upper()
            if t not in seen:
                seen.add(t)
                out.append(t)
    return out


# 用户强调的「核心 10 个」——在 UI 脚注中提示优先扫一眼（映射到实际 ticker）
CORE_WATCH_CHEATSHEET = (
    "SHY(≈短端) · IEF(≈10Y桶) · QQQ · IWM · SMH · HYG · "
    "FXY(日元/套息) · CYB(人民币) · CPER(铜) · "
    "MOVE/VVIX/VXN 为指数无场内单一 ticker，建议 TradingView"
)
