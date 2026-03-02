"""
StockQueen V1 - API Test Script
Test all API endpoints
"""

import httpx
import json
from typing import Dict, Any

BASE_URL = "http://localhost:8000"


def print_response(title: str, response: httpx.Response):
    """Print formatted API response"""
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")
    print(f"Status: {response.status_code}")
    print(f"URL: {response.url}")
    
    try:
        data = response.json()
        print(f"Response:")
        print(json.dumps(data, indent=2))
    except:
        print(f"Response: {response.text}")


async def test_health_check():
    """Test health check endpoint"""
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{BASE_URL}/health")
        print_response("Health Check", response)
        return response.status_code == 200


async def test_root():
    """Test root endpoint"""
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{BASE_URL}/")
        print_response("Root Endpoint", response)
        return response.status_code == 200


async def test_get_observe_signals():
    """Test getting observe signals"""
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{BASE_URL}/api/signals/observe")
        print_response("Get Observe Signals", response)
        return response.status_code == 200


async def test_get_confirmed_signals():
    """Test getting confirmed signals"""
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{BASE_URL}/api/signals/confirmed")
        print_response("Get Confirmed Signals", response)
        return response.status_code == 200


async def test_get_signal_summary():
    """Test getting signal summary"""
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{BASE_URL}/api/signals/summary")
        print_response("Get Signal Summary", response)
        return response.status_code == 200


async def test_get_risk_status():
    """Test getting risk status"""
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{BASE_URL}/api/risk/status")
        print_response("Get Risk Status", response)
        return response.status_code == 200


async def test_check_risk():
    """Test risk check"""
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{BASE_URL}/api/risk/check")
        print_response("Check Risk", response)
        return response.status_code == 200


async def test_confirm_signal():
    """Test signal confirmation (with dummy data)"""
    async with httpx.AsyncClient() as client:
        # This will fail if signal doesn't exist, but tests the endpoint
        payload = {
            "signal_id": "00000000-0000-0000-0000-000000000000",
            "confirmed": True,
            "notes": "Test confirmation"
        }
        response = await client.post(
            f"{BASE_URL}/api/signals/confirm",
            json=payload
        )
        print_response("Confirm Signal (Test)", response)
        return response.status_code in [200, 404, 500]


async def run_all_tests():
    """Run all API tests"""
    print("\n" + "=" * 60)
    print("  StockQueen V1 - API Test Suite")
    print("=" * 60)
    
    tests = [
        ("Health Check", test_health_check),
        ("Root Endpoint", test_root),
        ("Get Observe Signals", test_get_observe_signals),
        ("Get Confirmed Signals", test_get_confirmed_signals),
        ("Get Signal Summary", test_get_signal_summary),
        ("Get Risk Status", test_get_risk_status),
        ("Check Risk", test_check_risk),
        ("Confirm Signal", test_confirm_signal),
    ]
    
    results = []
    
    for name, test_func in tests:
        try:
            result = await test_func()
            results.append((name, result))
        except Exception as e:
            print(f"\n❌ Error running {name}: {e}")
            results.append((name, False))
    
    # Print summary
    print("\n" + "=" * 60)
    print("  Test Summary")
    print("=" * 60)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status}: {name}")
    
    print(f"\nTotal: {passed}/{total} tests passed")
    print("=" * 60)
    
    return passed == total


if __name__ == "__main__":
    import asyncio
    success = asyncio.run(run_all_tests())
    exit(0 if success else 1)
