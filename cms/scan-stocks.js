const fs = require('fs');
const path = require('path');

// 读取股票数据文件
const stockUniversePath = path.join(__dirname, '../site/data/stock-universe.json');

function scanStocks() {
  try {
    // 读取文件
    const rawData = fs.readFileSync(stockUniversePath, 'utf8');
    const data = JSON.parse(rawData);
    
    console.log('=== StockQueen 股票扫描结果 ===');
    console.log(`扫描日期: ${data.date}`);
    console.log(`市场状态: ${data.market_regime}`);
    console.log('==============================\n');
    
    // 过滤出符合进场条件的股票
    const eligibleStocks = data.stocks.filter(stock => stock['符合进场条件']);
    
    console.log(`总股票数: ${data.stocks.length}`);
    console.log(`符合进场条件: ${eligibleStocks.length}`);
    console.log('\n=== 按 Alpha 排名 Top 20 ===\n');
    
    // 按照 Alpha 值降序排序
    const sortedStocks = eligibleStocks.sort((a, b) => b.alpha - a.alpha);
    
    // 取前20名
    const top20Stocks = sortedStocks.slice(0, 20);
    
    // 格式化输出
    console.log('排名 | 代码 | 名称 | 行业 | Alpha | 贝塔 | 价格 | 成交量 | 市值(十亿美元)');
    console.log('-' . repeat(100));
    
    top20Stocks.forEach((stock, index) => {
      const rank = (index + 1).toString().padStart(4);
      const ticker = stock.ticker.padEnd(6);
      const name = stock.name.padEnd(20);
      const sector = stock.sector.padEnd(15);
      const alpha = (stock.alpha * 100).toFixed(2).padStart(6) + '%';
      const beta = stock.beta.toFixed(2).padStart(6);
      const price = '$' + stock.price.toFixed(2).padStart(8);
      const volume = (stock.volume / 1000000).toFixed(1) + 'M'.padStart(8);
      const marketCap = (stock.market_cap / 1000000000).toFixed(1) + 'B';
      
      console.log(`${rank} | ${ticker} | ${name} | ${sector} | ${alpha} | ${beta} | ${price} | ${volume} | ${marketCap}`);
    });
    
    console.log('\n=== 进场条件说明 ===');
    console.log('1. 价格 > 20日均线');
    console.log('2. 20日均线 > 50日均线');
    console.log('3. 50日均线 > 200日均线');
    console.log('4. RSI < 70 (避免超买)');
    console.log('5. 成交量 > 500K');
    console.log('6. Alpha > 0');
    
  } catch (error) {
    console.error('扫描股票时出错:', error);
  }
}

// 运行扫描
scanStocks();
