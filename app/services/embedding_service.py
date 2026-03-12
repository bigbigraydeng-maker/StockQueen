"""
StockQueen V2 - Embedding Service
Text vectorization via OpenAI Embedding API for RAG knowledge base
"""

import httpx
import logging
import asyncio
from typing import List, Optional

from app.config import settings

logger = logging.getLogger(__name__)


class EmbeddingService:
    """Text embedding service using OpenAI API"""

    def __init__(self):
        self.api_key = settings.openai_api_key
        self.base_url = settings.openai_base_url
        self.model = settings.embedding_model
        self.dimension = settings.embedding_dimension
        self.timeout = 30.0
        self.max_retries = 3
        self.batch_size = 20

    async def embed_text(self, text: str) -> Optional[List[float]]:
        """
        Embed a single text string into a vector.
        Returns list of floats (embedding vector) or None on failure.
        """
        if not text or not text.strip():
            logger.warning("Empty text provided for embedding")
            return None

        # Truncate very long texts (most embedding models have token limits)
        text = text[:8000]

        for attempt in range(self.max_retries):
            try:
                headers = {
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                }

                payload = {
                    "model": self.model,
                    "input": text,
                    "encoding_format": "float"
                }

                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.post(
                        f"{self.base_url}/embeddings",
                        headers=headers,
                        json=payload
                    )
                    response.raise_for_status()

                    result = response.json()
                    embedding = result["data"][0]["embedding"]

                    if len(embedding) != self.dimension:
                        logger.warning(
                            f"Embedding dimension mismatch: got {len(embedding)}, "
                            f"expected {self.dimension}"
                        )

                    return embedding

            except httpx.HTTPStatusError as e:
                logger.error(f"Embedding API HTTP error: {e.response.status_code}")
                if e.response.status_code == 429:
                    await self._backoff(attempt)
                elif attempt < self.max_retries - 1:
                    await self._backoff(attempt)
                else:
                    return None

            except httpx.RequestError as e:
                logger.error(f"Embedding API request error: {e}")
                if attempt < self.max_retries - 1:
                    await self._backoff(attempt)
                else:
                    return None

            except Exception as e:
                logger.error(f"Unexpected embedding error: {e}")
                return None

        return None

    async def embed_batch(self, texts: List[str]) -> List[Optional[List[float]]]:
        """
        Embed multiple texts. Returns list of embeddings (None for failures).
        Processes in batches to avoid API limits.
        """
        if not texts:
            return []

        results: List[Optional[List[float]]] = []

        for i in range(0, len(texts), self.batch_size):
            batch = texts[i:i + self.batch_size]

            # Filter empty texts but track indices
            valid_indices = []
            valid_texts = []
            for j, text in enumerate(batch):
                if text and text.strip():
                    valid_indices.append(j)
                    valid_texts.append(text[:8000])

            # Initialize batch results with None
            batch_results: List[Optional[List[float]]] = [None] * len(batch)

            if not valid_texts:
                results.extend(batch_results)
                continue

            try:
                headers = {
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                }

                payload = {
                    "model": self.model,
                    "input": valid_texts,
                    "encoding_format": "float"
                }

                async with httpx.AsyncClient(timeout=self.timeout * 2) as client:
                    response = await client.post(
                        f"{self.base_url}/embeddings",
                        headers=headers,
                        json=payload
                    )
                    response.raise_for_status()

                    result = response.json()
                    embeddings = result["data"]

                    for emb_data in embeddings:
                        idx = emb_data["index"]
                        if idx < len(valid_indices):
                            original_idx = valid_indices[idx]
                            batch_results[original_idx] = emb_data["embedding"]

                logger.info(
                    f"Batch embedded {len(valid_texts)} texts "
                    f"(batch {i // self.batch_size + 1})"
                )

            except Exception as e:
                logger.error(f"Batch embedding error: {e}")
                # Fall back to individual embedding
                for j, text in zip(valid_indices, valid_texts):
                    embedding = await self.embed_text(text)
                    batch_results[j] = embedding

            results.extend(batch_results)

            # Rate limit between batches
            if i + self.batch_size < len(texts):
                await asyncio.sleep(1)

        return results

    async def _backoff(self, attempt: int):
        """Exponential backoff between retries"""
        wait_time = 2 ** attempt
        logger.info(f"Embedding API retry in {wait_time}s...")
        await asyncio.sleep(wait_time)


# Global singleton
_embedding_service: Optional[EmbeddingService] = None


def get_embedding_service() -> EmbeddingService:
    """Get or create embedding service singleton"""
    global _embedding_service
    if _embedding_service is None:
        _embedding_service = EmbeddingService()
    return _embedding_service
