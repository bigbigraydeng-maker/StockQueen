"""
StockQueen V1 - AI Classification Service
DeepSeek API integration for news classification
"""

import httpx
import json
import logging
from typing import Optional, List
from datetime import datetime

from app.config import settings, VALID_EVENT_TYPES, VALID_DIRECTION_BIAS
from app.models import AIClassificationResult, AIEventCreate, NewsEvent
from app.services.db_service import EventService, AIEventService

logger = logging.getLogger(__name__)


class DeepSeekClient:
    """DeepSeek API client"""
    
    def __init__(self):
        self.api_key = settings.deepseek_api_key
        self.base_url = settings.deepseek_base_url
        self.model = settings.deepseek_model
        self.timeout = 60.0
        self.max_retries = 3
    
    async def classify_news(
        self,
        title: str,
        summary: Optional[str] = None,
        ticker: Optional[str] = None
    ) -> Optional[AIClassificationResult]:
        """
        Classify news using DeepSeek API
        Returns structured classification result
        """
        # Build prompt
        prompt = self._build_classification_prompt(title, summary, ticker)
        
        # Prepare request
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": "You are a financial news analyst specializing in biotech and pharmaceutical stocks. Analyze news and classify events accurately."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            "temperature": 0.1,  # Low temperature for consistent results
            "max_tokens": 150,
            "response_format": {"type": "json_object"}
        }
        
        # Make API call with retries
        for attempt in range(self.max_retries):
            try:
                logger.info(f"Calling DeepSeek API for: {title[:50]}...")
                
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.post(
                        f"{self.base_url}/chat/completions",
                        headers=headers,
                        json=payload
                    )
                    response.raise_for_status()
                    
                    result = response.json()
                    
                    # Parse response
                    content = result["choices"][0]["message"]["content"]
                    classification = self._parse_response(content)
                    
                    if classification:
                        logger.info(
                            f"Classification result: {classification.event_type} "
                            f"({classification.direction_bias})"
                        )
                        return classification
                    else:
                        logger.error("Failed to parse classification response")
                        return None
                        
            except httpx.HTTPStatusError as e:
                logger.error(f"DeepSeek API HTTP error: {e.response.status_code}")
                if e.response.status_code == 429:  # Rate limit
                    await self._exponential_backoff(attempt)
                elif attempt < self.max_retries - 1:
                    await self._exponential_backoff(attempt)
                else:
                    return None
                    
            except httpx.RequestError as e:
                logger.error(f"DeepSeek API request error: {e}")
                if attempt < self.max_retries - 1:
                    await self._exponential_backoff(attempt)
                else:
                    return None
                    
            except Exception as e:
                logger.error(f"Unexpected error calling DeepSeek API: {e}")
                return None
        
        return None
    
    def _build_classification_prompt(
        self,
        title: str,
        summary: Optional[str] = None,
        ticker: Optional[str] = None
    ) -> str:
        """Build classification prompt"""
        
        context = f"Ticker: {ticker}\n" if ticker else ""
        context += f"Title: {title}\n"
        if summary:
            context += f"Summary: {summary[:500]}\n"
        
        prompt = f"""Analyze the following biotech/pharmaceutical news and classify it.

{context}

Classify this news into the following categories:

1. Is this a valid biotech/pharma event? (true/false)
   - Valid events: Phase 2/3 results, FDA approvals, CRLs, clinical trial results
   - Invalid events: General news, partnerships without data, financial reports

2. Event Type (choose one):
   - Phase3_Positive: Positive Phase 3 trial results
   - Phase3_Negative: Negative or failed Phase 3 trial
   - FDA_Approval: FDA approval granted
   - CRL: Complete Response Letter (FDA rejection)
   - Phase2_Positive: Positive Phase 2 results
   - Phase2_Negative: Negative Phase 2 results
   - Other: Other significant events

3. Direction Bias:
   - long: Bullish/positive for stock price
   - short: Bearish/negative for stock price
   - none: Neutral or unclear impact

Respond ONLY with a JSON object in this exact format:
{{
    "is_valid_event": true/false,
    "event_type": "One of the event types above",
    "direction_bias": "long/short/none"
}}

Do not include any other text, explanations, or markdown formatting."""
        
        return prompt
    
    def _parse_response(self, content: str) -> Optional[AIClassificationResult]:
        """Parse DeepSeek API response"""
        try:
            # Clean up response (remove markdown code blocks if present)
            content = content.strip()
            if content.startswith("```json"):
                content = content[7:]
            if content.startswith("```"):
                content = content[3:]
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()
            
            # Parse JSON
            data = json.loads(content)
            
            # Validate required fields
            if not all(key in data for key in ["is_valid_event", "event_type", "direction_bias"]):
                logger.error(f"Missing required fields in response: {data}")
                return None
            
            # Validate event_type
            event_type = data["event_type"]
            if event_type not in VALID_EVENT_TYPES:
                logger.warning(f"Invalid event_type: {event_type}, defaulting to 'Other'")
                event_type = "Other"
            
            # Validate direction_bias
            direction_bias = data["direction_bias"]
            if direction_bias not in VALID_DIRECTION_BIAS:
                logger.warning(f"Invalid direction_bias: {direction_bias}, defaulting to 'none'")
                direction_bias = "none"
            
            return AIClassificationResult(
                is_valid_event=bool(data["is_valid_event"]),
                event_type=event_type,
                direction_bias=direction_bias
            )
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON response: {e}, content: {content[:200]}")
            return None
        except Exception as e:
            logger.error(f"Error parsing response: {e}")
            return None
    
    async def _exponential_backoff(self, attempt: int):
        """Exponential backoff between retries"""
        import asyncio
        wait_time = 2 ** attempt
        logger.info(f"Retrying DeepSeek API call in {wait_time} seconds...")
        await asyncio.sleep(wait_time)


class AIClassificationService:
    """Main AI classification service"""
    
    def __init__(self):
        self.client = DeepSeekClient()
        self.db_service = AIEventService()
        self.event_service = EventService()
    
    async def process_pending_events(self) -> dict:
        """
        Process all pending events with AI classification
        Returns summary of processed events
        """
        results = {
            "total_pending": 0,
            "total_processed": 0,
            "total_valid": 0,
            "errors": []
        }
        
        # Get pending events
        pending_events = await self.event_service.get_pending_events()
        results["total_pending"] = len(pending_events)
        
        logger.info(f"Found {len(pending_events)} pending events to classify")
        
        for event in pending_events:
            try:
                # Classify event
                classification = await self.client.classify_news(
                    title=event.title,
                    summary=event.summary,
                    ticker=event.ticker
                )
                
                if classification:
                    # Store classification
                    ai_event = AIEventCreate(
                        event_id=event.id,
                        ticker=event.ticker,
                        is_valid_event=classification.is_valid_event,
                        event_type=classification.event_type,
                        direction_bias=classification.direction_bias,
                        raw_response=json.dumps(classification.dict())
                    )
                    
                    stored = await self.db_service.create_ai_event(ai_event)
                    
                    if stored:
                        results["total_processed"] += 1
                        if classification.is_valid_event:
                            results["total_valid"] += 1
                        
                        # Update event status
                        await self.event_service.update_event_status(
                            event.id,
                            "processed"
                        )
                        
                        logger.info(
                            f"Classified event {event.id}: "
                            f"{classification.event_type} "
                            f"(valid: {classification.is_valid_event})"
                        )
                else:
                    # Mark as error
                    await self.event_service.update_event_status(event.id, "error")
                    results["errors"].append(f"Failed to classify event {event.id}")
                    
            except Exception as e:
                logger.error(f"Error processing event {event.id}: {e}")
                await self.event_service.update_event_status(event.id, "error")
                results["errors"].append(f"Error processing event {event.id}: {str(e)}")
        
        logger.info(
            f"AI classification complete: {results['total_processed']}/{results['total_pending']} "
            f"processed, {results['total_valid']} valid events"
        )
        return results
    
    async def classify_single_event(self, event: NewsEvent) -> Optional[AIClassificationResult]:
        """Classify a single event (for testing)"""
        return await self.client.classify_news(
            title=event.title,
            summary=event.summary,
            ticker=event.ticker
        )


# Convenience function for scheduled tasks
async def run_ai_classification() -> dict:
    """Run AI classification (for scheduled execution)"""
    service = AIClassificationService()
    return await service.process_pending_events()


class AIChatService:
    """AI Chat Service for Feishu bot"""
    
    def __init__(self):
        self.client = DeepSeekClient()
        self.conversation_history = {}  # Simple in-memory storage for user conversations
    
    async def _fetch_realtime_data(self, ticker: str) -> Optional[dict]:
        """Fetch real-time stock data from Yahoo Finance"""
        try:
            from app.services.market_service import YahooFinanceClient
            yahoo_client = YahooFinanceClient()
            data = await yahoo_client.get_stock_quote(ticker)
            return data
        except Exception as e:
            logger.error(f"[AIChat] Error fetching real-time data for {ticker}: {e}")
            return None
    
    def _extract_ticker_from_message(self, message: str) -> Optional[str]:
        """Extract stock ticker from user message"""
        import re
        
        # Common patterns for stock mentions
        patterns = [
            r'([A-Z]{1,5})\s*(?:股票|股价|价格|行情|ETF|etf)?',  # English tickers
            r'(?:股票|代码| ticker)?\s*[:：]?\s*([A-Z]{1,5})',  # Ticker after label
        ]
        
        for pattern in patterns:
            match = re.search(pattern, message.upper())
            if match:
                ticker = match.group(1)
                # Filter out common words that might be matched
                if ticker not in ['ETF', 'A股', '美股', '港股', '什么', '怎么']:
                    return ticker
        
        return None
    
    async def chat(self, user_id: str, message: str) -> str:
        """
        Chat with user using DeepSeek AI
        
        Args:
            user_id: User's open_id for conversation context
            message: User's message
            
        Returns:
            AI's response
        """
        try:
            # Initialize conversation history for new users
            if user_id not in self.conversation_history:
                self.conversation_history[user_id] = []
            
            # Check if user is asking for real-time data
            ticker = self._extract_ticker_from_message(message)
            realtime_data = None
            rag_context = ""

            if ticker:
                if any(keyword in message.lower() for keyword in ['价格', '股价', '行情', '多少', 'price', '实时']):
                    logger.info(f"[AIChat] Fetching real-time data for {ticker}")
                    realtime_data = await self._fetch_realtime_data(ticker)

                # RAG: fetch knowledge base context for this ticker
                try:
                    from app.services.knowledge_service import get_knowledge_service
                    ks = get_knowledge_service()
                    rag_context = await ks.get_context_for_signal(ticker)
                    if rag_context:
                        logger.info(f"[AIChat] RAG context found for {ticker} ({len(rag_context)} chars)")
                except Exception as e:
                    logger.warning(f"[AIChat] RAG context fetch failed: {e}")

            # Add user message to history
            self.conversation_history[user_id].append({"role": "user", "content": message})

            # Keep only last 10 messages for context
            if len(self.conversation_history[user_id]) > 10:
                self.conversation_history[user_id] = self.conversation_history[user_id][-10:]

            # Build system prompt with real-time data and RAG context
            system_prompt = self._build_system_prompt(realtime_data, ticker, rag_context)
            
            # Prepare messages
            messages = [
                {"role": "system", "content": system_prompt}
            ] + self.conversation_history[user_id]
            
            # Call DeepSeek API
            headers = {
                "Authorization": f"Bearer {self.client.api_key}",
                "Content-Type": "application/json"
            }
            
            payload = {
                "model": self.client.model,
                "messages": messages,
                "temperature": 0.7,
                "max_tokens": 1000
            }
            
            logger.info(f"[AIChat] Processing message from user {user_id[:10]}...")
            
            async with httpx.AsyncClient(timeout=self.client.timeout) as client:
                response = await client.post(
                    f"{self.client.base_url}/chat/completions",
                    headers=headers,
                    json=payload
                )
                response.raise_for_status()
                
                result = response.json()
                ai_response = result["choices"][0]["message"]["content"]
                
                # Add AI response to history
                self.conversation_history[user_id].append({"role": "assistant", "content": ai_response})
                
                logger.info(f"[AIChat] Response generated successfully")
                return ai_response.strip()
                
        except Exception as e:
            logger.error(f"[AIChat] Error generating response: {e}")
            return "抱歉，AI服务暂时不可用。请稍后重试或联系管理员。"
    
    def _build_system_prompt(self, realtime_data: Optional[dict], ticker: Optional[str],
                             rag_context: str = "") -> str:
        """Build system prompt with optional real-time data and RAG context"""

        base_prompt = """You are StockQueen, a professional AI investment advisor. You have deep expertise in:
1. US stock market — ETFs, mid-cap growth stocks, momentum rotation strategies
2. Biotech/pharma industry analysis and clinical trial interpretation
3. Technical analysis — momentum, moving averages, ATR-based risk management
4. StockQueen's proprietary systems: D+1 confirmation model, weekly rotation strategy
5. Real-time market data analysis

Your Role:
- Act as a confident, knowledgeable investment advisor
- Provide actionable insights and analysis based on available information
- When knowledge base context is provided, reference it in your analysis
- Be proactive in offering perspectives and recommendations

Guidelines:
- Be concise, professional, and confident
- Use Chinese for responses
- When asked about stocks, provide analysis and insights, not just data
- If you don't have specific data, provide analytical frameworks and industry insights
- Be decisive in your analysis while acknowledging risks
- When providing price data, include the data source and timestamp"""

        # Add real-time data if available
        if realtime_data and ticker:
            data_info = f"""

**Real-time Data Available for {ticker}:**
- Current Price: ${realtime_data.get('latest_price', 'N/A')}
- Change: {realtime_data.get('change_percent', 0):.2f}%
- Open: ${realtime_data.get('open', 'N/A')}
- High: ${realtime_data.get('high', 'N/A')}
- Low: ${realtime_data.get('low', 'N/A')}
- Volume: {realtime_data.get('volume', 'N/A'):,}
- Data Source: {realtime_data.get('data_source', 'Yahoo Finance')}
- Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

Use this data in your response when relevant."""
            base_prompt += data_info

        # Add RAG knowledge base context
        if rag_context:
            base_prompt += f"""

**Knowledge Base Context (from StockQueen's accumulated intelligence):**
{rag_context[:1500]}

Use this knowledge base context to enrich your analysis. Reference specific data points when relevant."""

        return base_prompt
    
    def clear_history(self, user_id: str):
        """Clear conversation history for a user"""
        if user_id in self.conversation_history:
            del self.conversation_history[user_id]


# Global AI chat service instance
_ai_chat_service: Optional[AIChatService] = None


def get_ai_chat_service() -> AIChatService:
    """Get or create AI chat service singleton"""
    global _ai_chat_service
    if _ai_chat_service is None:
        _ai_chat_service = AIChatService()
    return _ai_chat_service


# ---------------------------------------------------------------------------
# C2: General stock event classifier (not pharma-only)
# ---------------------------------------------------------------------------

class DeepSeekStockClassifier:
    """
    Classifies general stock news events using DeepSeek.
    Used by NewsEventScanner for after-hours event signal generation.
    Falls back to keyword rules when DeepSeek API is unavailable.
    """

    VALID_EVENT_TYPES = [
        "earnings_beat", "earnings_miss",
        "analyst_upgrade", "analyst_downgrade",
        "guidance_raise", "guidance_cut",
        "fda_approval", "fda_rejection",
        "ma_activity", "management_change",
        "buyback", "macro_risk",
        "other_positive", "other_negative",
        "noise",
    ]

    def __init__(self):
        self.api_key = settings.deepseek_api_key
        self.base_url = settings.deepseek_base_url
        self.model = settings.deepseek_model
        self.timeout = 30.0
        self.max_retries = 2

    async def classify(
        self,
        title: str,
        summary: Optional[str],
        ticker: str,
    ) -> Optional[dict]:
        """
        Returns dict: {event_type, direction, confidence}
        or None on failure.
        """
        if not self.api_key:
            return self._keyword_classify(title, summary)

        prompt = self._build_prompt(title, summary, ticker)
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a financial news analyst. Classify stock-related news events "
                        "accurately and concisely. Respond only with valid JSON."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.1,
            "max_tokens": 80,
            "response_format": {"type": "json_object"},
        }

        for attempt in range(self.max_retries):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    resp = await client.post(
                        f"{self.base_url}/chat/completions",
                        headers=headers,
                        json=payload,
                    )
                    resp.raise_for_status()
                    content = resp.json()["choices"][0]["message"]["content"]
                    return self._parse(content)
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429 and attempt < self.max_retries - 1:
                    import asyncio
                    await asyncio.sleep(2 ** attempt)
                else:
                    logger.warning(
                        f"[StockClassifier] API error {e.response.status_code}, "
                        "falling back to keywords"
                    )
                    return self._keyword_classify(title, summary)
            except Exception as e:
                logger.warning(f"[StockClassifier] Error: {e}, falling back to keywords")
                return self._keyword_classify(title, summary)

        return self._keyword_classify(title, summary)

    def _build_prompt(self, title: str, summary: Optional[str], ticker: str) -> str:
        ctx = f"Ticker: {ticker}\nTitle: {title}\n"
        if summary:
            ctx += f"Summary: {summary[:300]}\n"
        return (
            f"{ctx}\n"
            "Classify this news. Choose event_type from:\n"
            "earnings_beat, earnings_miss, analyst_upgrade, analyst_downgrade,\n"
            "guidance_raise, guidance_cut, fda_approval, fda_rejection,\n"
            "ma_activity, management_change, buyback, macro_risk,\n"
            "other_positive, other_negative, noise\n\n"
            "direction: \"bullish\" | \"bearish\" | \"neutral\"\n"
            "confidence: 0.0-1.0\n\n"
            'Respond ONLY with JSON: {"event_type": "...", "direction": "...", "confidence": 0.0}'
        )

    def _parse(self, content: str) -> Optional[dict]:
        try:
            content = content.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
            data = json.loads(content)
            event_type = data.get("event_type", "noise")
            if event_type not in self.VALID_EVENT_TYPES:
                event_type = "noise"
            direction = data.get("direction", "neutral")
            if direction not in ("bullish", "bearish", "neutral"):
                direction = "neutral"
            return {
                "event_type": event_type,
                "direction": direction,
                "confidence": float(data.get("confidence", 0.5)),
            }
        except Exception:
            return None

    def _keyword_classify(self, title: str, summary: Optional[str] = None) -> dict:
        """Fast keyword-based fallback classifier. Zero API cost."""
        text = (title + " " + (summary or "")).lower()

        if any(k in text for k in ["upgrade", "outperform", "buy rating", "overweight", "raised price target"]):
            return {"event_type": "analyst_upgrade", "direction": "bullish", "confidence": 0.7}
        if any(k in text for k in ["downgrade", "underperform", "sell rating", "underweight", "lowered price target"]):
            return {"event_type": "analyst_downgrade", "direction": "bearish", "confidence": 0.7}
        if any(k in text for k in ["beat", "beats expectations", "eps beat", "revenue beat", "better-than-expected"]):
            return {"event_type": "earnings_beat", "direction": "bullish", "confidence": 0.8}
        if any(k in text for k in ["miss", "missed", "below expectations", "eps miss", "disappointing earnings"]):
            return {"event_type": "earnings_miss", "direction": "bearish", "confidence": 0.8}
        if any(k in text for k in ["raises guidance", "raised guidance", "increased outlook", "raises forecast"]):
            return {"event_type": "guidance_raise", "direction": "bullish", "confidence": 0.75}
        if any(k in text for k in ["cuts guidance", "cut guidance", "lowers outlook", "reduces forecast"]):
            return {"event_type": "guidance_cut", "direction": "bearish", "confidence": 0.75}
        if any(k in text for k in ["fda approved", "fda approval", "approved by fda"]):
            return {"event_type": "fda_approval", "direction": "bullish", "confidence": 0.9}
        if any(k in text for k in ["fda rejected", "complete response letter", "crl", "fda denial"]):
            return {"event_type": "fda_rejection", "direction": "bearish", "confidence": 0.9}
        if any(k in text for k in ["acquires", "acquisition", "merger", "buyout", "takeover bid"]):
            return {"event_type": "ma_activity", "direction": "bullish", "confidence": 0.7}
        if any(k in text for k in ["ceo resign", "cfo resign", "new ceo", "appoints ceo", "steps down"]):
            return {"event_type": "management_change", "direction": "neutral", "confidence": 0.7}
        if any(k in text for k in ["buyback", "share repurchase", "stock repurchase"]):
            return {"event_type": "buyback", "direction": "bullish", "confidence": 0.7}
        if any(k in text for k in ["tariff", "sanction", "geopolit", "trade war", "export ban"]):
            return {"event_type": "macro_risk", "direction": "bearish", "confidence": 0.6}
        return {"event_type": "noise", "direction": "neutral", "confidence": 0.3}
