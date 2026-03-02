"""
StockQueen V1 - AI Classification Test Script
Test DeepSeek AI classification
"""

import sys
import os
import asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.ai_service import AIClassificationService
from app.models import NewsEventCreate
from app.services.db_service import EventService
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def test_ai_classification():
    """Test AI classification with sample news"""
    print("\n" + "=" * 60)
    print("  Testing AI Classification Service")
    print("=" * 60)
    
    service = AIClassificationService()
    
    # Test cases
    test_cases = [
        {
            "title": "XYZ Pharma Announces Positive Phase 3 Topline Results for XYZ-123",
            "summary": "XYZ Pharma today announced positive topline results from its Phase 3 clinical trial of XYZ-123 for the treatment of advanced melanoma. The trial met its primary endpoint with statistically significant improvement in overall survival.",
            "ticker": "XYZ",
            "expected_type": "Phase3_Positive",
            "expected_direction": "long"
        },
        {
            "title": "ABC Biotech Receives FDA Complete Response Letter for ABC-456",
            "summary": "ABC Biotech announced that the FDA has issued a Complete Response Letter (CRL) regarding its New Drug Application for ABC-456. The FDA requested additional data on manufacturing processes.",
            "ticker": "ABC",
            "expected_type": "CRL",
            "expected_direction": "short"
        },
        {
            "title": "DEF Therapeutics Announces FDA Approval of DEF-789",
            "summary": "DEF Therapeutics announced that the FDA has approved DEF-789 for the treatment of rheumatoid arthritis. The drug will be available in pharmacies starting next month.",
            "ticker": "DEF",
            "expected_type": "FDA_Approval",
            "expected_direction": "long"
        },
        {
            "title": "GHI Inc Reports Quarterly Financial Results",
            "summary": "GHI Inc reported Q4 revenue of $500 million, up 10% year-over-year. The company also provided guidance for the upcoming fiscal year.",
            "ticker": "GHI",
            "expected_type": "Other",
            "expected_direction": "none"
        }
    ]
    
    print(f"\nRunning {len(test_cases)} test cases...\n")
    
    results = []
    
    for i, test_case in enumerate(test_cases, 1):
        print(f"Test Case {i}: {test_case['title'][:60]}...")
        
        try:
            # Create a test event (not saving to DB)
            classification = await service.client.classify_news(
                title=test_case["title"],
                summary=test_case["summary"],
                ticker=test_case["ticker"]
            )
            
            if classification:
                print(f"  ✅ Classification successful")
                print(f"     Event Type: {classification.event_type}")
                print(f"     Direction: {classification.direction_bias}")
                print(f"     Valid: {classification.is_valid_event}")
                
                # Check if matches expected
                type_match = classification.event_type == test_case["expected_type"]
                direction_match = classification.direction_bias == test_case["expected_direction"]
                
                if type_match and direction_match:
                    print(f"  ✅ Matches expected output")
                    results.append(True)
                else:
                    print(f"  ⚠️  Mismatch!")
                    print(f"     Expected: {test_case['expected_type']} / {test_case['expected_direction']}")
                    results.append(False)
            else:
                print(f"  ❌ Classification failed")
                results.append(False)
                
        except Exception as e:
            print(f"  ❌ Error: {e}")
            results.append(False)
        
        print()
    
    # Summary
    passed = sum(results)
    total = len(results)
    
    print("=" * 60)
    print(f"Test Summary: {passed}/{total} passed")
    print("=" * 60)
    
    return passed == total


if __name__ == "__main__":
    try:
        success = asyncio.run(test_ai_classification())
        print(f"\n{'✅' if success else '❌'} Test {'passed' if success else 'failed'}")
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
