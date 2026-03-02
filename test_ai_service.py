#!/usr/bin/env python3
"""
Test script for AI classification module
"""

import asyncio
from app.services.ai_service import AIClassificationService
from app.models import NewsEvent

async def test_ai_classification():
    print("Testing AI classification module...")
    
    # Create a test news event
    from datetime import datetime
    test_event = NewsEvent(
        id="1",
        title="BioTech Company Announces Positive Phase 3 Trial Results for Cancer Drug",
        summary="BioTech Inc. today announced positive top-line results from its Phase 3 clinical trial of BT-1001, a novel cancer immunotherapy. The trial met its primary endpoint, showing a 30% improvement in progression-free survival compared to standard of care.",
        url="https://example.com/news/1",
        source="pr_newswire",
        published_at=datetime.utcnow(),
        ticker="BTI",
        status="pending"
    )
    
    # Test AI classification service
    service = AIClassificationService()
    classification = await service.classify_single_event(test_event)
    
    print("\nAI classification results:")
    if classification:
        print(f"Is valid event: {classification.is_valid_event}")
        print(f"Event type: {classification.event_type}")
        print(f"Direction bias: {classification.direction_bias}")
    else:
        print("Classification failed")

if __name__ == "__main__":
    asyncio.run(test_ai_classification())
