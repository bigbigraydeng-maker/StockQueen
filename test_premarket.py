"""
Test script for premarket data fetching
"""
import asyncio
import yfinance as yf
from app.services.market_service import YahooFinanceClient


async def test_premarket_data():
    """Test premarket data fetching for sample stocks"""
    client = YahooFinanceClient()
    
    # Test stocks - mix of biotech and regular stocks
    test_tickers = ["AAPL", "TSLA", "NVDA", "AMD"]
    
    print("=" * 60)
    print("📊 盘前数据测试")
    print("=" * 60)
    
    for ticker in test_tickers:
        print(f"\n🔍 测试股票: {ticker}")
        print("-" * 40)
        
        try:
            # Get premarket data
            premarket = await client.get_premarket_data(ticker)
            
            if premarket:
                if premarket.get('has_premarket'):
                    print(f"✅ 有盘前数据")
                    print(f"   盘前价格: ${premarket['premarket_price']:.2f}")
                    print(f"   昨收价格: ${premarket['previous_close']:.2f}")
                    print(f"   盘前涨幅: {premarket['premarket_change_pct']:.2f}%")
                    
                    # Risk assessment
                    change = premarket['premarket_change_pct']
                    if change > 50:
                        print(f"   🔴 风险: 盘前暴涨 {change:.1f}%，追高风险极高！")
                    elif change > 30:
                        print(f"   🟠 风险: 盘前大涨 {change:.1f}%，谨慎追入")
                    elif change > 10:
                        print(f"   🟡 提示: 盘前上涨 {change:.1f}%，可观察开盘")
                    else:
                        print(f"   🟢 状态: 盘前涨幅 {change:.1f}%，仍有空间")
                else:
                    print(f"⚠️ 无盘前数据")
                    print(f"   原因: {premarket.get('message', '市场已开盘或无盘前交易')}")
            else:
                print(f"❌ 获取盘前数据失败")
                
        except Exception as e:
            print(f"❌ 错误: {e}")
    
    print("\n" + "=" * 60)
    print("测试完成")
    print("=" * 60)


def test_yfinance_direct():
    """Direct test of yfinance premarket data"""
    print("\n" + "=" * 60)
    print("📊 直接测试 yfinance 盘前数据")
    print("=" * 60)
    
    test_tickers = ["AAPL", "TSLA", "NVDA"]
    
    for ticker in test_tickers:
        print(f"\n🔍 {ticker}:")
        try:
            stock = yf.Ticker(ticker)
            info = stock.info
            
            # Check available fields
            premarket_price = info.get('preMarketPrice')
            previous_close = info.get('previousClose')
            regular_market_price = info.get('regularMarketPrice')
            
            print(f"   preMarketPrice: {premarket_price}")
            print(f"   previousClose: {previous_close}")
            print(f"   regularMarketPrice: {regular_market_price}")
            
            if premarket_price and previous_close:
                change = (premarket_price - previous_close) / previous_close * 100
                print(f"   计算涨幅: {change:.2f}%")
            
        except Exception as e:
            print(f"   错误: {e}")


if __name__ == "__main__":
    # Run async test
    asyncio.run(test_premarket_data())
    
    # Run direct test
    test_yfinance_direct()
