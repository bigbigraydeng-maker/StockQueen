"""
StockQueen - SEC EDGAR Form 4 内幕交易信号服务

数据流：
1. 从 EDGAR Submissions API 获取目标 ticker 的 Form 4 申报列表
2. 下载每份申报的 XML，解析非衍生品交易（nonDerivativeTransaction）
3. 清洗规则：只保留公开市场买入(P)/卖出(S)，过滤期权行权/赠与等
4. 写入 insider_transactions 表（UPSERT，accession+owner+code+date 去重）
5. 对最近5天的交易聚合，生成 event_signals（集群买/CEO买/大额买等）

EDGAR 速率限制：官方要求 max 10 req/sec，设 Semaphore(5) + 0.12s delay

清洗标准：
- transaction_code 必须是 P（公开市场买入）或 S（公开市场卖出）
- is_officer=True OR is_director=True（排除仅为10%大股东）
- 名义金额 shares × price >= MIN_NOTIONAL_USD ($50,000)
- shares > 0，price > 0（排除无价格申报）
"""

import asyncio
import logging
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)

# ============================================================
# 常量配置
# ============================================================

EDGAR_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
EDGAR_ARCHIVE_URL     = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nodash}/{doc}"
EDGAR_TICKERS_URL     = "https://www.sec.gov/files/company_tickers.json"

# EDGAR 要求 User-Agent 必须包含联系信息
EDGAR_HEADERS = {
    "User-Agent": "StockQueen Research contact@stockqueen.app",
    "Accept-Encoding": "gzip, deflate",
    "Accept": "application/json, application/xml, text/xml, */*",
}

MIN_NOTIONAL_USD  = 50_000    # 最低名义金额门槛（美元）
CLUSTER_DAYS      = 5         # 集群买入/卖出的回溯窗口（天）
CLUSTER_MIN_COUNT = 3         # 触发集群信号的最低内幕人数

# 速率限制：官方要求 <= 10 req/sec
_EDGAR_SEMAPHORE = asyncio.Semaphore(5)
_REQUEST_DELAY   = 0.12       # 秒，每个请求后强制等待

# 职位关键词 → 规范化标签（按优先级排列）
_TITLE_RULES: list[tuple[list[str], str]] = [
    (["chief executive", "ceo"],          "ceo"),
    (["chief financial", "cfo"],          "cfo"),
    (["chief operating", "coo"],          "coo"),
    (["chief technology", "cto"],         "cto"),
    (["chief revenue",   "cro"],          "cro"),
    (["chief marketing", "cmo"],          "cmo"),
    (["chief legal", "general counsel"],  "clo"),
    (["president"],                       "president"),
    (["chairman"],                        "chairman"),
    (["director"],                        "director"),
    (["officer"],                         "officer"),
]

# 信号规格：(event_type, direction, strength, 买入条件描述)
# 按优先级排列（从高到低）
_BUY_SIGNAL_RULES: list[dict] = [
    {
        "event_type": "insider_cluster_buy",
        "direction":  "bullish",
        "strength":   0.90,
        "desc":       "集群买入（3+内幕人，5日内）",
        "cond":       "cluster",        # 特殊条件，在代码中单独判断
    },
    {
        "event_type": "insider_ceo_buy",
        "direction":  "bullish",
        "strength":   0.85,
        "desc":       "CEO/CFO 公开市场买入",
        "cond":       "c_suite",        # title_normalized in {ceo, cfo}
    },
    {
        "event_type": "insider_large_buy",
        "direction":  "bullish",
        "strength":   0.80,
        "desc":       "大额内幕买入（>$500K）",
        "cond":       "large",          # notional >= 500_000
    },
    {
        "event_type": "insider_director_buy",
        "direction":  "bullish",
        "strength":   0.60,
        "desc":       "董事/高管买入（>$50K）",
        "cond":       "any",            # 任意通过过滤的买入
    },
]

_SELL_SIGNAL_RULES: list[dict] = [
    {
        "event_type": "insider_cluster_sell",
        "direction":  "bearish",
        "strength":   0.40,
        "desc":       "集群卖出（3+内幕人，5日内）",
        "cond":       "cluster",
    },
    {
        "event_type": "insider_large_sell",
        "direction":  "bearish",
        "strength":   0.35,
        "desc":       "C-Suite 大额卖出（>$2M）",
        "cond":       "c_suite_large",  # c_suite AND notional >= 2_000_000
    },
]


# ============================================================
# CIK 缓存（进程级，每次部署后首次调用时刷新）
# ============================================================

_cik_map: dict[str, int] = {}          # ticker(上) → CIK(int)
_cik_map_loaded_at: float = 0.0
_CIK_MAP_TTL = 86400                   # 24h


async def _ensure_cik_map(session: aiohttp.ClientSession) -> None:
    """确保 CIK 映射已加载（内存缓存，24h TTL）。"""
    global _cik_map, _cik_map_loaded_at
    if _cik_map and (time.time() - _cik_map_loaded_at) < _CIK_MAP_TTL:
        return

    logger.info("Loading SEC EDGAR CIK ticker map ...")
    async with _EDGAR_SEMAPHORE:
        try:
            async with session.get(EDGAR_TICKERS_URL, headers=EDGAR_HEADERS, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                if resp.status != 200:
                    logger.error(f"Failed to load CIK map: HTTP {resp.status}")
                    return
                data = await resp.json(content_type=None)
        except Exception as e:
            logger.error(f"CIK map fetch error: {e}", exc_info=True)
            return
        finally:
            await asyncio.sleep(_REQUEST_DELAY)

    # 格式: {"0": {"cik_str": "320193", "ticker": "AAPL", "title": "Apple Inc"}, ...}
    new_map: dict[str, int] = {}
    for entry in data.values():
        ticker = entry.get("ticker", "").upper().strip()
        cik    = entry.get("cik_str", "")
        if ticker and cik:
            try:
                new_map[ticker] = int(cik)
            except ValueError:
                pass

    _cik_map = new_map
    _cik_map_loaded_at = time.time()
    logger.info(f"CIK map loaded: {len(_cik_map)} tickers")


def _normalize_title(raw: str) -> str:
    """将原始职位名称规范化为标准标签，无匹配时返回空字符串。"""
    if not raw:
        return ""
    lower = raw.lower().strip()
    for keywords, tag in _TITLE_RULES:
        if any(k in lower for k in keywords):
            return tag
    return ""


def _xml_val(element: Optional[ET.Element], tag: str) -> Optional[str]:
    """
    从 XML 元素中安全提取子元素的文本值。
    Form 4 XML 有时用 <value> 子元素，有时直接是文本。
    """
    if element is None:
        return None
    child = element.find(tag)
    if child is None:
        return None
    # 尝试找 <value> 子元素
    val_el = child.find("value")
    if val_el is not None and val_el.text:
        return val_el.text.strip()
    # 直接文本
    if child.text:
        return child.text.strip()
    return None


def _safe_float(s: Optional[str]) -> Optional[float]:
    """字符串 → float，失败返回 None。"""
    if not s:
        return None
    try:
        return float(s.replace(",", ""))
    except (ValueError, AttributeError):
        return None


def _safe_bool(s: Optional[str]) -> bool:
    """'1'/'true'/'yes' → True，其他 → False。"""
    if not s:
        return False
    return s.strip().lower() in {"1", "true", "yes"}


# ============================================================
# XML 解析
# ============================================================

def parse_form4_xml(xml_content: str, filing_date: str, cik: str, source_url: str) -> list[dict]:
    """
    解析 Form 4 XML 内容，返回清洗后的交易记录列表。

    只处理 nonDerivativeTransaction（非衍生品）。
    衍生品（期权行权等）在 derivativeTable 中，直接跳过。

    返回字段：
        ticker, company_name, cik, insider_cik, insider_name,
        insider_title, title_normalized,
        is_director, is_officer, is_ten_pct_owner,
        transaction_code, transaction_date, shares, price_per_share,
        notional_value, acquired_or_disposed, shares_owned_after,
        pct_of_holdings, filing_date, accession_number, source_url
    """
    try:
        # 有些 Form 4 XML 有 BOM 或非标准编码声明，strip 掉
        xml_clean = xml_content.strip()
        if xml_clean.startswith("\ufeff"):
            xml_clean = xml_clean[1:]
        root = ET.fromstring(xml_clean)
    except ET.ParseError as e:
        logger.warning(f"Form 4 XML parse error ({source_url}): {e}")
        return []

    # ---- 发行人信息 ----
    issuer     = root.find("issuer")
    ticker_raw = _xml_val(issuer, "issuerTradingSymbol") or ""
    ticker     = ticker_raw.upper().strip()
    company    = _xml_val(issuer, "issuerName") or ""

    # ---- 申报人信息（可能有多个，但 Form 4 通常只有1个） ----
    owners = root.findall("reportingOwner")
    if not owners:
        return []

    # 取第一个（绝大多数情况只有1个）
    owner = owners[0]
    owner_id   = owner.find("reportingOwnerId")
    owner_rel  = owner.find("reportingOwnerRelationship")

    insider_cik   = _xml_val(owner_id, "rptOwnerCik") or ""
    insider_name  = (_xml_val(owner_id, "rptOwnerName") or "").strip().upper()
    insider_title = (_xml_val(owner_rel, "officerTitle") or "").strip()

    if not insider_name:
        return []

    is_director  = _safe_bool(_xml_val(owner_rel, "isDirector"))
    is_officer   = _safe_bool(_xml_val(owner_rel, "isOfficer"))
    is_ten_pct   = _safe_bool(_xml_val(owner_rel, "isTenPercentOwner"))
    title_norm   = _normalize_title(insider_title)

    # 提取 accession number：从 source_url 反推
    # source_url 格式: https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nodash}/{doc}
    accession_number = ""
    try:
        parts = source_url.split("/")
        acc_nodash = parts[-2]  # e.g. "0001234567-26-123456" 去掉连字符版
        # 还原连字符格式
        if len(acc_nodash) == 18:
            accession_number = f"{acc_nodash[:10]}-{acc_nodash[10:12]}-{acc_nodash[12:]}"
        else:
            accession_number = acc_nodash
    except Exception:
        accession_number = source_url

    # ---- 解析非衍生品交易 ----
    nd_table = root.find("nonDerivativeTable")
    if nd_table is None:
        return []

    records: list[dict] = []
    for txn in nd_table.findall("nonDerivativeTransaction"):
        # 交易日期
        txn_date_raw = _xml_val(txn, "transactionDate")
        if not txn_date_raw:
            continue
        txn_date = txn_date_raw[:10]  # 截取 YYYY-MM-DD

        # 交易编码（P=公开买, S=公开卖, M=期权行权, G=赠与, etc.）
        coding   = txn.find("transactionCoding")
        code_raw = _xml_val(coding, "transactionCode") if coding is not None else None
        if not code_raw or code_raw.strip().upper() not in {"P", "S"}:
            continue  # 只保留公开市场买卖
        code = code_raw.strip().upper()

        # 交易金额
        amounts = txn.find("transactionAmounts")
        shares_raw = _xml_val(amounts, "transactionShares")
        price_raw  = _xml_val(amounts, "transactionPricePerShare")
        acq_disp   = (_xml_val(amounts, "transactionAcquiredDisposedCode") or "").upper()

        shares = _safe_float(shares_raw)
        price  = _safe_float(price_raw)

        if shares is None or shares <= 0:
            continue  # 无效数量
        if price is None or price <= 0:
            continue  # 无价格（赠与、计划等，正常市场交易必有价格）

        notional = shares * price
        if notional < MIN_NOTIONAL_USD:
            continue  # 名义金额过小，噪音

        # 交易后持仓
        post = txn.find("postTransactionAmounts")
        shares_after_raw = _xml_val(post, "sharesOwnedFollowingTransaction")
        shares_after     = _safe_float(shares_after_raw)

        pct_of_holdings = None
        if shares_after and shares_after > 0:
            pct_of_holdings = round(shares / shares_after * 100, 2)

        records.append({
            "ticker":               ticker,
            "company_name":         company,
            "cik":                  cik,
            "insider_cik":          insider_cik,
            "insider_name":         insider_name,
            "insider_title":        insider_title,
            "title_normalized":     title_norm,
            "is_director":          is_director,
            "is_officer":           is_officer,
            "is_ten_pct_owner":     is_ten_pct,
            "transaction_code":     code,
            "transaction_date":     txn_date,
            "shares":               shares,
            "price_per_share":      price,
            "notional_value":       round(notional, 2),
            "acquired_or_disposed": acq_disp or None,
            "shares_owned_after":   shares_after,
            "pct_of_holdings":      pct_of_holdings,
            "filing_date":          filing_date,
            "accession_number":     accession_number,
            "source_url":           source_url,
        })

    return records


# ============================================================
# 数据清洗：第二层过滤（XML 解析后）
# ============================================================

def clean_transactions(raw: list[dict]) -> list[dict]:
    """
    XML 解析后的第二层过滤：
    - 必须是 officer 或 director（排除纯10%大股东）
    - notional >= MIN_NOTIONAL_USD（已在 parse 阶段过滤，双重确认）
    """
    cleaned = []
    for r in raw:
        if not (r["is_officer"] or r["is_director"]):
            continue  # 排除非管理层的大股东买卖（投机性强，信号价值低）
        if (r["notional_value"] or 0) < MIN_NOTIONAL_USD:
            continue
        cleaned.append(r)
    return cleaned


# ============================================================
# EDGAR API 调用
# ============================================================

async def _fetch_submissions(cik: int, session: aiohttp.ClientSession) -> Optional[dict]:
    """获取公司 EDGAR submissions JSON。"""
    url = EDGAR_SUBMISSIONS_URL.format(cik=cik)
    async with _EDGAR_SEMAPHORE:
        try:
            async with session.get(url, headers=EDGAR_HEADERS, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                if resp.status == 404:
                    return None
                if resp.status != 200:
                    logger.warning(f"Submissions fetch HTTP {resp.status}: {url}")
                    return None
                return await resp.json(content_type=None)
        except asyncio.TimeoutError:
            logger.warning(f"Submissions timeout: {url}")
            return None
        except Exception as e:
            logger.warning(f"Submissions fetch error ({url}): {e}")
            return None
        finally:
            await asyncio.sleep(_REQUEST_DELAY)


async def _fetch_form4_xml(cik: int, acc_nodash: str, primary_doc: str,
                            session: aiohttp.ClientSession) -> Optional[str]:
    """
    获取 Form 4 XML 文件内容。

    primary_doc 来自 submissions JSON，可能带子目录（如 "xslF345X05/wf-form4.xml"）。
    尝试顺序：
    1. 直接使用 primary_doc 构造 URL
    2. 如果第1步失败，尝试去掉子目录前缀（取最后一个斜杠后的文件名）
    """
    base_url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nodash}/"

    candidates = [primary_doc]
    # 若带路径前缀，也尝试去掉前缀的版本
    if "/" in primary_doc:
        candidates.append(primary_doc.split("/")[-1])

    for doc in candidates:
        url = base_url + doc
        async with _EDGAR_SEMAPHORE:
            try:
                async with session.get(url, headers=EDGAR_HEADERS,
                                       timeout=aiohttp.ClientTimeout(total=20)) as resp:
                    if resp.status != 200:
                        await asyncio.sleep(_REQUEST_DELAY)
                        continue
                    content_type = resp.headers.get("Content-Type", "")
                    text = await resp.text(encoding="utf-8", errors="replace")
                    # 确认是 XML（Form 4 XML 以 <?xml 或 <ownershipDocument 开头）
                    stripped = text.lstrip()
                    if not (stripped.startswith("<?xml") or
                            stripped.startswith("<ownershipDocument") or
                            "ownershipDocument" in stripped[:500]):
                        await asyncio.sleep(_REQUEST_DELAY)
                        continue
                    return text
            except asyncio.TimeoutError:
                logger.debug(f"Form 4 XML timeout: {url}")
            except Exception as e:
                logger.debug(f"Form 4 XML fetch error ({url}): {e}")
            finally:
                await asyncio.sleep(_REQUEST_DELAY)

    return None


async def fetch_form4_for_ticker(
    ticker: str,
    cik: int,
    days_back: int,
    session: aiohttp.ClientSession,
) -> list[dict]:
    """
    获取某 ticker 最近 days_back 天的 Form 4 申报并解析，返回清洗后的交易记录。
    """
    subs = await _fetch_submissions(cik, session)
    if not subs:
        return []

    recent = subs.get("filings", {}).get("recent", {})
    forms       = recent.get("form", [])
    filing_dates= recent.get("filingDate", [])
    acc_nums    = recent.get("accessionNumber", [])
    primary_docs= recent.get("primaryDocument", [])

    cutoff = (date.today() - timedelta(days=days_back)).isoformat()

    all_records: list[dict] = []

    for i, form in enumerate(forms):
        if form not in {"4", "4/A"}:
            continue
        if i >= len(filing_dates) or filing_dates[i] < cutoff:
            continue

        filing_date = filing_dates[i]
        acc_raw     = acc_nums[i] if i < len(acc_nums) else ""
        primary_doc = primary_docs[i] if i < len(primary_docs) else ""

        if not acc_raw or not primary_doc:
            continue

        acc_nodash  = acc_raw.replace("-", "")
        source_url  = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nodash}/{primary_doc}"

        xml_text = await _fetch_form4_xml(cik, acc_nodash, primary_doc, session)
        if not xml_text:
            logger.debug(f"No XML for {ticker} filing {acc_raw}")
            continue

        raw_records = parse_form4_xml(xml_text, filing_date, str(cik), source_url)
        cleaned     = clean_transactions(raw_records)
        all_records.extend(cleaned)

    return all_records


# ============================================================
# 数据库写入
# ============================================================

def _upsert_transactions(records: list[dict], db) -> int:
    """批量 UPSERT 清洗后的交易记录到 insider_transactions 表。"""
    saved = 0
    for r in records:
        try:
            db.table("insider_transactions").upsert(
                {
                    "accession_number":     r["accession_number"],
                    "filing_date":          r["filing_date"],
                    "transaction_date":     r["transaction_date"],
                    "ticker":               r["ticker"],
                    "company_name":         r["company_name"],
                    "cik":                  r["cik"],
                    "insider_cik":          r["insider_cik"],
                    "insider_name":         r["insider_name"],
                    "insider_title":        r["insider_title"],
                    "title_normalized":     r["title_normalized"],
                    "is_director":          r["is_director"],
                    "is_officer":           r["is_officer"],
                    "is_ten_pct_owner":     r["is_ten_pct_owner"],
                    "transaction_code":     r["transaction_code"],
                    "shares":               r["shares"],
                    "price_per_share":      r["price_per_share"],
                    "notional_value":       r["notional_value"],
                    "acquired_or_disposed": r["acquired_or_disposed"],
                    "shares_owned_after":   r["shares_owned_after"],
                    "pct_of_holdings":      r["pct_of_holdings"],
                    "source_url":           r["source_url"],
                },
                on_conflict="accession_number,insider_name,transaction_code,transaction_date",
            ).execute()
            saved += 1
        except Exception as e:
            logger.warning(f"Upsert failed for {r.get('ticker')} / {r.get('insider_name')}: {e}")
    return saved


# ============================================================
# 信号聚合
# ============================================================

def _make_accession_url(accession_number: str, cik: str) -> str:
    """构造 EDGAR 申报页面 URL（用作 event_signals.url 去重键）。"""
    acc_nodash = accession_number.replace("-", "")
    return f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nodash}/"


def _format_notional(v: float) -> str:
    """将金额格式化为可读字符串。"""
    if v >= 1_000_000:
        return f"${v / 1_000_000:.1f}M"
    elif v >= 1_000:
        return f"${v / 1_000:.0f}K"
    return f"${v:.0f}"


def _compute_signals_for_ticker(ticker: str, txns: list[dict], filing_date: str) -> list[dict]:
    """
    对某 ticker 的近期交易记录计算 event_signals 信号列表。

    Args:
        ticker:       股票代码
        txns:         最近 CLUSTER_DAYS 天的清洗后交易记录（来自 DB）
        filing_date:  本轮扫描日期（写入 event_signals.date）

    Returns:
        event_signals 记录列表（可能为空）
    """
    if not txns:
        return []

    buys  = [t for t in txns if t["transaction_code"] == "P"]
    sells = [t for t in txns if t["transaction_code"] == "S"]

    signals: list[dict] = []

    # ---------- 买入信号（按优先级，每个 ticker 只取最高级别） ----------
    generated_buy = False

    # 1. 集群买入（最高优先级）
    if not generated_buy and len(buys) >= CLUSTER_MIN_COUNT:
        unique_buyers = {t["insider_name"] for t in buys}
        if len(unique_buyers) >= CLUSTER_MIN_COUNT:
            total_notional  = sum(t["notional_value"] or 0 for t in buys)
            names_preview   = ", ".join(sorted(unique_buyers)[:3])
            latest_acc      = buys[0]["accession_number"]
            cik_val         = buys[0]["cik"]
            headline = (
                f"{ticker} 集群内幕买入：{len(unique_buyers)} 名内幕人 "
                f"合计 {_format_notional(total_notional)}"
            )
            summary = (
                f"过去 {CLUSTER_DAYS} 天内，{len(unique_buyers)} 名内幕人公开市场买入 {ticker}，"
                f"合计名义金额 {_format_notional(total_notional)}。"
                f"买入人员（前3）：{names_preview}。"
                f"数据来源：SEC EDGAR Form 4。"
            )
            signals.append({
                "date":            filing_date,
                "ticker":          ticker,
                "event_type":      "insider_cluster_buy",
                "direction":       "bullish",
                "headline":        headline,
                "summary":         summary,
                "signal_strength": 0.90,
                "relevance_score": 1.0,
                "sentiment_score": 0.90,
                "source":          "SEC EDGAR Form 4",
                "url":             _make_accession_url(latest_acc, cik_val),
                "published":       filing_date,
            })
            generated_buy = True

    # 2. CEO/CFO 买入
    if not generated_buy:
        c_suite_buys = [t for t in buys if t["title_normalized"] in {"ceo", "cfo"}]
        if c_suite_buys:
            best    = max(c_suite_buys, key=lambda t: t["notional_value"] or 0)
            notional = best["notional_value"] or 0
            if notional >= 100_000:
                role    = best["title_normalized"].upper()
                headline = (
                    f"{ticker} {role} 公开市场买入 {_format_notional(notional)}"
                )
                summary = (
                    f"{best['insider_name']}（{best['insider_title']}）"
                    f"于 {best['transaction_date']} 公开市场买入 {ticker} "
                    f"{best['shares']:.0f} 股，"
                    f"均价 ${best['price_per_share']:.2f}，"
                    f"合计 {_format_notional(notional)}。"
                )
                signals.append({
                    "date":            filing_date,
                    "ticker":          ticker,
                    "event_type":      "insider_ceo_buy",
                    "direction":       "bullish",
                    "headline":        headline,
                    "summary":         summary,
                    "signal_strength": 0.85,
                    "relevance_score": 1.0,
                    "sentiment_score": 0.85,
                    "source":          "SEC EDGAR Form 4",
                    "url":             _make_accession_url(best["accession_number"], best["cik"]),
                    "published":       best["transaction_date"],
                })
                generated_buy = True

    # 3. 大额单笔买入
    if not generated_buy:
        large_buys = [t for t in buys if (t["notional_value"] or 0) >= 500_000]
        if large_buys:
            best     = max(large_buys, key=lambda t: t["notional_value"] or 0)
            notional  = best["notional_value"]
            headline  = (
                f"{ticker} 内幕大额买入 {_format_notional(notional)}"
            )
            summary = (
                f"{best['insider_name']}（{best['insider_title'] or '内幕人'}）"
                f"于 {best['transaction_date']} 公开市场买入 {ticker} "
                f"{best['shares']:.0f} 股，均价 ${best['price_per_share']:.2f}，"
                f"合计 {_format_notional(notional)}。"
            )
            signals.append({
                "date":            filing_date,
                "ticker":          ticker,
                "event_type":      "insider_large_buy",
                "direction":       "bullish",
                "headline":        headline,
                "summary":         summary,
                "signal_strength": 0.80,
                "relevance_score": 1.0,
                "sentiment_score": 0.80,
                "source":          "SEC EDGAR Form 4",
                "url":             _make_accession_url(best["accession_number"], best["cik"]),
                "published":       best["transaction_date"],
            })
            generated_buy = True

    # 4. 普通董事/高管买入（通过最低门槛的所有买入）
    if not generated_buy and buys:
        best     = max(buys, key=lambda t: t["notional_value"] or 0)
        notional  = best["notional_value"]
        role_str  = best["insider_title"] or "内幕人"
        headline  = (
            f"{ticker} 内幕买入：{best['insider_name']} {_format_notional(notional)}"
        )
        summary = (
            f"{best['insider_name']}（{role_str}）"
            f"于 {best['transaction_date']} 公开市场买入 {ticker} "
            f"{best['shares']:.0f} 股，均价 ${best['price_per_share']:.2f}，"
            f"合计 {_format_notional(notional)}。"
        )
        signals.append({
            "date":            filing_date,
            "ticker":          ticker,
            "event_type":      "insider_director_buy",
            "direction":       "bullish",
            "headline":        headline,
            "summary":         summary,
            "signal_strength": 0.60,
            "relevance_score": 1.0,
            "sentiment_score": 0.60,
            "source":          "SEC EDGAR Form 4",
            "url":             _make_accession_url(best["accession_number"], best["cik"]),
            "published":       best["transaction_date"],
        })

    # ---------- 卖出信号（仅高置信度情形） ----------
    # 1. 集群卖出
    if len(sells) >= CLUSTER_MIN_COUNT:
        unique_sellers = {t["insider_name"] for t in sells}
        if len(unique_sellers) >= CLUSTER_MIN_COUNT:
            total_notional = sum(t["notional_value"] or 0 for t in sells)
            names_preview  = ", ".join(sorted(unique_sellers)[:3])
            latest_acc     = sells[0]["accession_number"]
            cik_val        = sells[0]["cik"]
            headline = (
                f"{ticker} 集群内幕卖出：{len(unique_sellers)} 名内幕人 "
                f"合计 {_format_notional(total_notional)}"
            )
            summary = (
                f"过去 {CLUSTER_DAYS} 天内，{len(unique_sellers)} 名内幕人公开市场卖出 {ticker}，"
                f"合计 {_format_notional(total_notional)}。"
                f"卖出人员（前3）：{names_preview}。注意：卖出原因多样，预测价值低于买入。"
            )
            signals.append({
                "date":            filing_date,
                "ticker":          ticker,
                "event_type":      "insider_cluster_sell",
                "direction":       "bearish",
                "headline":        headline,
                "summary":         summary,
                "signal_strength": 0.40,
                "relevance_score": 1.0,
                "sentiment_score": -0.40,
                "source":          "SEC EDGAR Form 4",
                "url":             _make_accession_url(latest_acc, cik_val),
                "published":       filing_date,
            })

    # 2. C-Suite 大额单笔卖出（>$2M）
    c_suite_large_sells = [
        t for t in sells
        if t["title_normalized"] in {"ceo", "cfo", "coo", "president", "chairman"}
        and (t["notional_value"] or 0) >= 2_000_000
    ]
    if c_suite_large_sells:
        best     = max(c_suite_large_sells, key=lambda t: t["notional_value"] or 0)
        notional  = best["notional_value"]
        role      = best["title_normalized"].upper()
        headline  = (
            f"{ticker} {role} 大额卖出 {_format_notional(notional)}"
        )
        summary = (
            f"{best['insider_name']}（{best['insider_title']}）"
            f"于 {best['transaction_date']} 公开市场卖出 {ticker} "
            f"{best['shares']:.0f} 股，均价 ${best['price_per_share']:.2f}，"
            f"合计 {_format_notional(notional)}。（注意：卖出原因多样，仅供参考）"
        )
        signals.append({
            "date":            filing_date,
            "ticker":          ticker,
            "event_type":      "insider_large_sell",
            "direction":       "bearish",
            "headline":        headline,
            "summary":         summary,
            "signal_strength": 0.35,
            "relevance_score": 1.0,
            "sentiment_score": -0.35,
            "source":          "SEC EDGAR Form 4",
            "url":             _make_accession_url(best["accession_number"], best["cik"]),
            "published":       best["transaction_date"],
        })

    return signals


def _save_signals(signals: list[dict], db) -> int:
    """将信号写入 event_signals 表（按 url 去重）。"""
    saved = 0
    for sig in signals:
        try:
            db.table("event_signals").upsert(
                sig,
                on_conflict="url",
            ).execute()
            saved += 1
        except Exception as e:
            logger.warning(f"Signal upsert failed ({sig.get('ticker')}): {e}")
    return saved


# ============================================================
# 主入口
# ============================================================

async def run_insider_scan(
    days_back: int = 2,
    extra_tickers: Optional[list[str]] = None,
) -> dict:
    """
    主入口：扫描内幕交易 Form 4 申报，清洗后写入 DB，聚合生成信号。

    Args:
        days_back:       回溯多少天的 EDGAR 申报（默认2天，覆盖周末和延迟）
        extra_tickers:   追加扫描的 ticker 列表（如当前仓位）

    Returns:
        {
            "tickers_scanned": int,
            "transactions_saved": int,
            "signals_generated": int,
            "duration_sec": float,
        }
    """
    from app.database import get_db
    from app.config.sp100_watchlist import SP100_TICKERS
    from app.config.rotation_watchlist import LARGECAP_STOCKS

    t0 = time.time()

    # 合并监控股票池（SP100 + 轮动大盘股 + 当前仓位）
    watchlist_set: set[str] = set(SP100_TICKERS)
    for item in LARGECAP_STOCKS:
        watchlist_set.add(item["ticker"].upper())
    if extra_tickers:
        for t in extra_tickers:
            watchlist_set.add(t.upper())

    watchlist = sorted(watchlist_set)
    logger.info(f"Insider scan: {len(watchlist)} tickers, days_back={days_back}")

    db = get_db()
    scan_date = date.today().isoformat()

    total_txns    = 0
    total_signals = 0
    tickers_hit   = []

    connector = aiohttp.TCPConnector(limit=10, ttl_dns_cache=300)
    async with aiohttp.ClientSession(connector=connector) as session:
        # 加载 CIK 映射
        await _ensure_cik_map(session)
        if not _cik_map:
            logger.error("CIK map empty, aborting insider scan")
            return {"tickers_scanned": 0, "transactions_saved": 0,
                    "signals_generated": 0, "duration_sec": 0}

        # 逐 ticker 串行扫描（SEC 速率限制严格，避免并发过高被封）
        for ticker in watchlist:
            cik = _cik_map.get(ticker)
            if not cik:
                logger.debug(f"No CIK for {ticker}, skipping")
                continue

            try:
                records = await fetch_form4_for_ticker(ticker, cik, days_back, session)
            except Exception as e:
                logger.error(f"Form 4 fetch error for {ticker}: {e}", exc_info=True)
                continue

            if not records:
                continue

            tickers_hit.append(ticker)
            n_saved = _upsert_transactions(records, db)
            total_txns += n_saved
            logger.info(f"{ticker}: {n_saved} transactions saved (CIK={cik})")

    # ---- 聚合信号（对所有有记录的 ticker，回溯 CLUSTER_DAYS 天） ----
    if tickers_hit:
        cutoff = (date.today() - timedelta(days=CLUSTER_DAYS)).isoformat()
        for ticker in tickers_hit:
            try:
                result = (
                    db.table("insider_transactions")
                    .select("*")
                    .eq("ticker", ticker)
                    .gte("transaction_date", cutoff)
                    .order("transaction_date", desc=True)
                    .execute()
                )
                txns = result.data or []
                signals = _compute_signals_for_ticker(ticker, txns, scan_date)
                if signals:
                    n_sig = _save_signals(signals, db)
                    total_signals += n_sig
                    logger.info(f"{ticker}: {n_sig} signals generated")
            except Exception as e:
                logger.error(f"Signal computation error for {ticker}: {e}", exc_info=True)

    duration = round(time.time() - t0, 1)
    summary = {
        "tickers_scanned":    len(watchlist),
        "tickers_hit":        len(tickers_hit),
        "transactions_saved": total_txns,
        "signals_generated":  total_signals,
        "duration_sec":       duration,
    }
    logger.info(f"Insider scan complete: {summary}")
    return summary
