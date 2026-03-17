"""
StockQueen Newsletter - AI 内容生成器
根据真实持仓数据和策略逻辑，自动生成 newsletter 所有文字内容

支持两种 AI 后端（自动选择）：
  1. Anthropic Claude (ANTHROPIC_API_KEY)  ← 优先
  2. DeepSeek (DEEPSEEK_API_KEY)           ← 后备

用法（在 generate.py 中调用，无需直接调用此模块）：
  from scripts.newsletter.ai_content_generator import AIContentGenerator
  gen = AIContentGenerator()
  content = await gen.generate(portfolio_data)
  # content 直接可以合并进 weekly_content_template.json
"""

import asyncio
import json
import logging
import os
from datetime import datetime
from typing import Optional

import httpx

logger = logging.getLogger("newsletter.ai_generator")

# ─────────────────────────────────────────────
# AI 后端配置
# ─────────────────────────────────────────────

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")


def _get_backend() -> str:
    """自动检测可用的 AI 后端"""
    if ANTHROPIC_API_KEY:
        return "anthropic"
    if DEEPSEEK_API_KEY:
        return "deepseek"
    return "none"


# ─────────────────────────────────────────────
# Prompt 构建
# ─────────────────────────────────────────────

SYSTEM_PROMPT = """你是 StockQueen 量化投资 newsletter 的首席分析师和内容编辑。

StockQueen 是一个基于 AI 量化模型的投资 newsletter，核心策略是：
- 多因子动量模型（Momentum + RSI + 成交量 + ATR）
- 市场状态识别（BULL/BEAR/CHOPPY 三种 Regime）
- 动态轮换：BULL 模式持成长ETF，BEAR 模式持做空/国债ETF，CHOPPY 模式降仓观望
- Walk-Forward 验证：163周，胜率57.7%，Sharpe 2.68，累计收益536.8%（对比 SPY +69.8%）

你的任务是根据本周真实的组合数据，生成高质量、有深度的 newsletter 内容。

写作风格要求：
- 专业但不晦涩，适合有一定投资知识的读者
- 数据驱动：一定要引用真实的持仓数据、收益数字
- 有观点、有判断：不要只描述现象，要解释「为什么」
- 中文版语气：专业理性，适合港台新马投资者
- 英文版语气：简洁直接，Institutional-grade，适合 AU/NZ/SG/JP/KR 英语投资者"""


def _build_generation_prompt(data: dict) -> str:
    """根据组合数据构建 AI 生成 prompt"""

    regime = data.get("market_regime", "UNKNOWN").upper()
    positions = data.get("positions", [])
    new_entries = data.get("new_entries", [])
    new_exits = data.get("new_exits", [])
    held = data.get("held_positions", [])
    recent_exits = data.get("recent_exits", [])
    trade_summary = data.get("trade_summary", {})
    backtest = data.get("backtest", {})
    week_number = data.get("week_number", datetime.now().isocalendar()[1])
    year = data.get("year", datetime.now().year)

    # 构建持仓描述
    def pos_desc(p):
        ticker = p.get("ticker", "?")
        ret = p.get("return_pct")
        ret_str = f"+{ret*100:.1f}%" if ret and ret >= 0 else (f"{ret*100:.1f}%" if ret else "持平")
        entry = p.get("entry_price")
        entry_str = f"${entry:.2f}" if entry else ""
        return f"{ticker}({ret_str}{', 进仓'+entry_str if entry_str else ''})"

    # 检测防御性标的
    defensive_tickers = {'SH', 'PSQ', 'DOG', 'RWM', 'VGIT', 'SHY', 'TLT', 'IEF', 'GLD', 'BIL'}
    defensive_pos = [p for p in positions if p.get("ticker", "") in defensive_tickers]
    offensive_pos = [p for p in positions if p.get("ticker", "") not in defensive_tickers]

    # 最近已平仓收益
    closed_summary = ""
    if recent_exits:
        wins = [t for t in recent_exits if t.get("return_pct", 0) > 0]
        losses = [t for t in recent_exits if t.get("return_pct", 0) <= 0]
        closed_summary = f"本周平仓 {len(recent_exits)} 笔: 盈利 {len(wins)} 笔 / 亏损 {len(losses)} 笔"
        if recent_exits:
            best = max(recent_exits, key=lambda t: t.get("return_pct", 0))
            closed_summary += f"，最佳平仓: {best.get('ticker')} {best.get('return_pct', 0)*100:+.1f}%"

    prompt = f"""
本周是 {year}年第{week_number}周。以下是 StockQueen 量化模型的真实持仓数据：

【市场状态】{regime}

【当前持仓（{len(positions)} 个）】
- 进攻型: {', '.join(pos_desc(p) for p in offensive_pos) or '无'}
- 防御型: {', '.join(pos_desc(p) for p in defensive_pos) or '无'}

【本周新买入（{len(new_entries)} 个）】
{', '.join(pos_desc(p) for p in new_entries) if new_entries else '本周无新买入信号'}

【本周卖出（{len(new_exits)} 个）】
{', '.join(p.get('ticker', '') for p in new_exits) if new_exits else '本周无卖出'}

【已平仓记录】
{closed_summary if closed_summary else '本周无已平仓记录'}

【历史统计】
- 总交易笔数: {trade_summary.get('total_trades', 'N/A')}
- 胜率: {trade_summary.get('win_rate', 0.577)*100:.1f}%
- 平均持仓天数: {trade_summary.get('avg_hold_days', 8.4):.1f} 天
- 累计收益: {backtest.get('total_return', '+536.8%')}（对比 SPY {backtest.get('spy_return', '+69.8%')}）

---

请生成以下 JSON 格式的 newsletter 内容（严格按格式输出，不要有额外文字）：

{{
  "strategy_pulse": {{
    "zh": "【策略脉搏·中文】200-350字。描述本周市场状态、模型触发的关键决策、持仓变化背后的逻辑。要有具体数据支撑，体现量化思维。",
    "en": "【Strategy Pulse·English】150-250 words. Same content in English. Reference actual portfolio moves, regime signals, and model logic. Be direct and data-driven."
  }},
  "quant_insight": {{
    "title_zh": "【量化深度文章标题·中文】15字以内",
    "title_en": "【Quant Deep Dive Title·English】8 words max",
    "body_zh": "【量化洞察正文·中文】600-900字。基于本周真实操作，深度解析一个量化投资核心话题。必须引用具体数据。可以探讨：为什么模型做了这个决策、该市场状态下历史上怎么表现、风险管理逻辑、与传统策略的对比等。",
    "body_en": "【Quant Deep Dive·English】400-600 words. Same deep dive in English. Institutional-grade analysis grounded in this week's actual moves."
  }},
  "strategy_notes": {{
    "zh": "【策略备注·中文】50-100字。模型运行状态、参数是否有调整、Walk-Forward 指标简报",
    "en": "【Strategy Notes·English】40-80 words. Model status, any parameter changes, performance metrics."
  }},
  "free_teaser_insight": {{
    "zh": "【免费版预告钩子·中文】80-120字。告知免费读者本周组合处于什么状态，暗示有完整信号，引导升级。不能透露具体进仓价/止损位。",
    "en": "【Free Version Teaser·English】60-100 words. Tease the week's regime and key moves without revealing exact prices. Drive upgrade."
  }}
}}

注意：
1. 严格输出 JSON，不要有 markdown 代码块标记
2. 所有内容必须基于上述真实数据，不要编造数字
3. 量化洞察文章必须有实质性深度，不能是泛泛而谈
4. 中英文内容必须语义一致（不是直译，而是符合各自受众的表达习惯）
"""
    return prompt.strip()


# ─────────────────────────────────────────────
# AI 调用：Anthropic Claude
# ─────────────────────────────────────────────

async def _call_anthropic(prompt: str) -> Optional[str]:
    """调用 Anthropic Claude API"""
    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    payload = {
        "model": "claude-opus-4-5",
        "max_tokens": 4096,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": prompt}],
    }
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers=headers,
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
            return data["content"][0]["text"]
    except Exception as e:
        logger.error(f"[Anthropic] API 调用失败: {e}")
        return None


# ─────────────────────────────────────────────
# AI 调用：DeepSeek
# ─────────────────────────────────────────────

async def _call_deepseek(prompt: str) -> Optional[str]:
    """调用 DeepSeek API"""
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.7,
        "max_tokens": 4096,
    }
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                f"{DEEPSEEK_BASE_URL}/chat/completions",
                headers=headers,
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]
    except Exception as e:
        logger.error(f"[DeepSeek] API 调用失败: {e}")
        return None


# ─────────────────────────────────────────────
# JSON 解析：从 AI 输出中提取 JSON
# ─────────────────────────────────────────────

def _extract_json(text: str) -> Optional[dict]:
    """从 AI 输出文本中提取 JSON（兼容有无代码块的情况）"""
    if not text:
        return None

    # 去掉 markdown 代码块
    text = text.strip()
    for marker in ["```json", "```JSON", "```"]:
        if text.startswith(marker):
            text = text[len(marker):]
            break
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    # 尝试直接解析
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 找到 JSON 对象的起始和结束
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError as e:
            logger.warning(f"[JSON] 解析失败: {e}")

    return None


# ─────────────────────────────────────────────
# 主类
# ─────────────────────────────────────────────

class AIContentGenerator:
    """
    AI 驱动的 newsletter 内容生成器

    使用方式:
        gen = AIContentGenerator()
        content = await gen.generate(portfolio_data)

    返回格式（可直接合并到 weekly_content_template.json）:
        {
          "strategy_pulse": {"zh": "...", "en": "..."},
          "quant_insight": {"title_zh": "...", "title_en": "...", "body_zh": "...", "body_en": "..."},
          "strategy_notes": {"zh": "...", "en": "..."},
          "free_teaser_insight": {"zh": "...", "en": "..."}
        }
    """

    def __init__(self):
        self.backend = _get_backend()
        if self.backend == "none":
            logger.warning(
                "[AIGen] 未检测到 ANTHROPIC_API_KEY 或 DEEPSEEK_API_KEY，"
                "将使用 weekly_content_template.json 中的静态内容"
            )
        else:
            logger.info(f"[AIGen] 使用 AI 后端: {self.backend}")

    @property
    def is_available(self) -> bool:
        return self.backend != "none"

    async def generate(self, portfolio_data: dict) -> Optional[dict]:
        """
        根据组合数据生成 newsletter 内容

        Args:
            portfolio_data: DataFetcher.fetch_all() 返回的完整数据包

        Returns:
            生成的内容字典，失败时返回 None
        """
        if not self.is_available:
            logger.info("[AIGen] 跳过 AI 生成（无 API key）")
            return None

        logger.info(f"[AIGen] 开始生成内容 (backend={self.backend})...")
        prompt = _build_generation_prompt(portfolio_data)

        # 调用 AI
        raw_text = None
        if self.backend == "anthropic":
            raw_text = await _call_anthropic(prompt)
        elif self.backend == "deepseek":
            raw_text = await _call_deepseek(prompt)

        if not raw_text:
            logger.error("[AIGen] AI 调用失败，返回 None")
            return None

        # 解析 JSON
        content = _extract_json(raw_text)
        if not content:
            logger.error(f"[AIGen] JSON 解析失败，原始输出:\n{raw_text[:500]}")
            return None

        # 验证必需字段
        required = ["strategy_pulse", "quant_insight", "strategy_notes", "free_teaser_insight"]
        missing = [k for k in required if k not in content]
        if missing:
            logger.warning(f"[AIGen] 缺少字段: {missing}")

        logger.info("[AIGen] ✅ 内容生成成功")
        return content

    async def generate_with_fallback(self, portfolio_data: dict, template_path: str) -> dict:
        """
        生成内容，失败时自动回退到 weekly_content_template.json

        Args:
            portfolio_data: 组合数据
            template_path: weekly_content_template.json 路径

        Returns:
            最终合并后的完整内容字典
        """
        # 1. 加载静态模板作为基础
        try:
            with open(template_path, "r", encoding="utf-8") as f:
                template = json.load(f)
            logger.info(f"[AIGen] 已加载静态模板: {template_path}")
        except Exception as e:
            logger.warning(f"[AIGen] 加载模板失败: {e}，使用空白基础")
            template = {}

        # 2. 尝试 AI 生成
        ai_content = await self.generate(portfolio_data)

        if ai_content:
            # 用 AI 内容覆盖模板中的对应字段（保留模板中 AI 不生成的字段如 blog_feature、product_news）
            for key in ["strategy_pulse", "quant_insight", "strategy_notes", "free_teaser_insight"]:
                if key in ai_content:
                    template[key] = ai_content[key]
            logger.info("[AIGen] ✅ AI 内容已合并到模板")
        else:
            logger.warning("[AIGen] ⚠️  AI 生成失败，使用静态模板内容")

        # 3. 补充 week/year 元数据
        template["week_number"] = portfolio_data.get("week_number", template.get("week_number"))
        template["year"] = portfolio_data.get("year", template.get("year"))
        template["generated_at"] = portfolio_data.get("generated_at", datetime.now().strftime("%Y-%m-%d %H:%M"))
        template["ai_generated"] = bool(ai_content)

        return template


# ─────────────────────────────────────────────
# 命令行调试接口
# ─────────────────────────────────────────────

async def _debug_run():
    """用于直接运行此模块进行调试"""
    from pathlib import Path
    import sys

    project_root = Path(__file__).parent.parent.parent
    sys.path.insert(0, str(project_root))

    from dotenv import load_dotenv
    load_dotenv(project_root / ".env")

    from scripts.newsletter.data_fetcher import DataFetcher

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")

    print("=" * 60)
    print("StockQueen AI Content Generator - Debug Mode")
    print("=" * 60)

    fetcher = DataFetcher()
    data = await fetcher.fetch_all()

    gen = AIContentGenerator()
    template_path = Path(__file__).parent / "weekly_content_template.json"
    content = await gen.generate_with_fallback(data, str(template_path))

    print("\n📄 生成内容预览:")
    print(json.dumps(content, ensure_ascii=False, indent=2))

    # 保存草稿
    draft_path = Path(__file__).parent / "weekly_content_draft.json"
    with open(draft_path, "w", encoding="utf-8") as f:
        json.dump(content, f, ensure_ascii=False, indent=2)
    print(f"\n✅ 草稿已保存: {draft_path}")


if __name__ == "__main__":
    asyncio.run(_debug_run())
