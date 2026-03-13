/**
 * StockQueen Marketing Website - Data Loading Module
 * Loads JSON data and renders all sections
 */

// API base URL — live backend for real-time data
const API_BASE = 'https://stockqueen-api.onrender.com';

// Utility Functions
const formatPercent = (value) => {
    if (value === null || value === undefined) return '--';
    const percent = (value * 100).toFixed(1);
    return `${percent}%`;
};

const formatNumber = (value, decimals = 2) => {
    if (value === null || value === undefined) return '--';
    return value.toFixed(decimals);
};

const formatCurrency = (value) => {
    if (value === null || value === undefined) return '--';
    return `$${value.toFixed(2)}`;
};

const formatDate = (dateStr) => {
    if (!dateStr) return '--';
    const date = new Date(dateStr);
    return date.toLocaleDateString('en-US', { 
        year: 'numeric', 
        month: 'short', 
        day: 'numeric' 
    });
};

// Show/Hide Helpers
const showLoading = (section) => {
    document.getElementById(`${section}-loading`).classList.remove('hidden');
    document.getElementById(`${section}-error`).classList.add('hidden');
    document.getElementById(`${section}-content`)?.classList.add('hidden');
};

const showError = (section) => {
    document.getElementById(`${section}-loading`).classList.add('hidden');
    document.getElementById(`${section}-error`).classList.remove('hidden');
    document.getElementById(`${section}-content`)?.classList.add('hidden');
};

const showContent = (section) => {
    document.getElementById(`${section}-loading`).classList.add('hidden');
    document.getElementById(`${section}-error`).classList.add('hidden');
    document.getElementById(`${section}-content`)?.classList.remove('hidden');
};

// Load Backtest Summary
async function loadBacktestSummary() {
    showLoading('backtest');
    
    try {
        const response = await fetch('data/backtest-summary.json');
        if (!response.ok) throw new Error('Failed to load');
        
        const data = await response.json();
        
        // Update metrics
        document.getElementById('strategy-return').textContent = formatPercent(data.strategy_return);
        document.getElementById('spy-return').textContent = formatPercent(data.spy_return);
        document.getElementById('alpha-spy').textContent = formatPercent(data.alpha_vs_spy);
        document.getElementById('sharpe-ratio').textContent = data.sharpe?.toFixed(2) || '--';
        document.getElementById('max-drawdown').textContent = formatPercent(data.max_drawdown);
        document.getElementById('weekly-winrate').textContent = formatPercent(data.weekly_winrate);
        document.getElementById('backtest-period').textContent = 
            `${formatDate(data.period_start)} - ${formatDate(data.period_end)}`;
        document.getElementById('backtest-updated').textContent = formatDate(data.last_updated);
        
        // Color coding
        const strategyReturn = document.getElementById('strategy-return');
        if (data.strategy_return > 0) {
            strategyReturn.classList.add('text-emerald-400');
            strategyReturn.classList.remove('text-red-400');
        } else {
            strategyReturn.classList.add('text-red-400');
            strategyReturn.classList.remove('text-emerald-400');
        }
        
        showContent('backtest');
    } catch (error) {
        console.error('Error loading backtest summary:', error);
        showError('backtest');
    }
}

// Load Equity Curve
async function loadEquityCurve() {
    showLoading('chart');
    
    try {
        const response = await fetch('data/equity-curve.json');
        if (!response.ok) throw new Error('Failed to load');
        
        const data = await response.json();
        
        // Render chart
        if (typeof renderEquityChart === 'function') {
            renderEquityChart(data);
        }
        
        showContent('chart');
    } catch (error) {
        console.error('Error loading equity curve:', error);
        showError('chart');
    }
}

// Load Latest Signals (real-time from API, fallback to static JSON)
async function loadLatestSignals() {
    showLoading('signals');

    try {
        // Try live API first, fallback to static JSON
        let response;
        try {
            response = await fetch(`${API_BASE}/api/public/signals`);
        } catch (e) {
            console.warn('API unavailable, falling back to static JSON');
            response = null;
        }
        if (!response || !response.ok) {
            response = await fetch('data/latest-signals.json');
        }
        if (!response.ok) throw new Error('Failed to load');
        
        const data = await response.json();
        
        // Update market regime
        const regimeEl = document.getElementById('market-regime');
        regimeEl.textContent = data.market_regime || '--';
        
        // Style based on regime
        regimeEl.className = 'text-2xl font-bold';
        if (data.market_regime === 'BULL') {
            regimeEl.classList.add('text-emerald-400');
        } else if (data.market_regime === 'BEAR') {
            regimeEl.classList.add('text-red-400');
        } else {
            regimeEl.classList.add('text-cyan-400');
        }
        
        document.getElementById('signal-date').textContent = formatDate(data.date);

        // Update position cards
        const container = document.getElementById('positions-cards');
        container.innerHTML = '';

        if (data.positions && data.positions.length > 0) {
            data.positions.forEach(pos => {
                const isPositive = pos.return_pct >= 0;
                const returnColor = isPositive ? 'text-emerald-400' : 'text-red-400';
                const returnBg = isPositive ? 'bg-emerald-400/10' : 'bg-red-400/10';

                // Progress bar: stop_loss ← current → take_profit
                let progressBar = '';
                if (pos.stop_loss && pos.take_profit && pos.entry_price) {
                    const range = pos.take_profit - pos.stop_loss;
                    const currentPos = range > 0 ? Math.max(0, Math.min(100, ((pos.current_price - pos.stop_loss) / range) * 100)) : 50;
                    const entryPos = range > 0 ? ((pos.entry_price - pos.stop_loss) / range) * 100 : 50;
                    const barColor = currentPos >= entryPos ? 'bg-emerald-400' : 'bg-red-400';
                    progressBar = `
                        <div class="mt-4">
                            <div class="relative h-1.5 bg-gray-700 rounded-full overflow-hidden">
                                <div class="absolute top-0 h-full w-px bg-gray-400 z-10" style="left:${entryPos}%"></div>
                                <div class="h-full rounded-full ${barColor}" style="width:${currentPos}%"></div>
                            </div>
                            <div class="flex justify-between text-[10px] text-gray-500 mt-1">
                                <span>SL ${formatCurrency(pos.stop_loss)}</span>
                                <span>Entry ${formatCurrency(pos.entry_price)}</span>
                                <span>TP ${formatCurrency(pos.take_profit)}</span>
                            </div>
                        </div>`;
                }

                const card = document.createElement('div');
                card.className = 'bg-gray-800/60 border border-gray-700 rounded-xl p-5 hover:border-gray-600 transition-colors';
                card.innerHTML = `
                    <div class="flex items-center justify-between mb-4">
                        <div class="flex items-center gap-3">
                            <span class="text-xl font-bold text-white">${pos.ticker}</span>
                            <span class="px-2 py-0.5 rounded text-xs bg-cyan-900/50 text-cyan-300 border border-cyan-800">Active</span>
                        </div>
                        <div class="px-3 py-1 rounded-lg ${returnBg}">
                            <span class="font-mono font-bold text-lg ${returnColor}">
                                ${isPositive ? '+' : ''}${formatPercent(pos.return_pct)}
                            </span>
                        </div>
                    </div>
                    <div class="grid grid-cols-2 gap-3 text-sm">
                        <div>
                            <p class="text-gray-500 text-xs">Entry Price</p>
                            <p class="font-mono text-white">${formatCurrency(pos.entry_price)}</p>
                        </div>
                        <div>
                            <p class="text-gray-500 text-xs">Current Price</p>
                            <p class="font-mono text-white">${formatCurrency(pos.current_price)}</p>
                        </div>
                        <div>
                            <p class="text-red-400 text-xs">Stop Loss</p>
                            <p class="font-mono text-red-400">${pos.stop_loss ? formatCurrency(pos.stop_loss) : '--'}</p>
                        </div>
                        <div>
                            <p class="text-emerald-400 text-xs">Take Profit</p>
                            <p class="font-mono text-emerald-400">${pos.take_profit ? formatCurrency(pos.take_profit) : '--'}</p>
                        </div>
                    </div>
                    ${progressBar}
                    ${pos.signal_date ? `<p class="text-gray-500 text-xs mt-3">Signal: ${formatDate(pos.signal_date)}</p>` : ''}
                `;
                container.appendChild(card);
            });
        } else {
            container.innerHTML = `<div class="col-span-full py-8 text-center text-gray-500">No active positions</div>`;
        }
        
        showContent('signals');
    } catch (error) {
        console.error('Error loading latest signals:', error);
        showError('signals');
    }
}

// Load Signal History
async function loadSignalHistory() {
    showLoading('history');
    
    try {
        const response = await fetch('data/signal-history.json');
        if (!response.ok) throw new Error('Failed to load');
        
        const data = await response.json();
        
        // Update history table (show last 20)
        const tbody = document.getElementById('history-table');
        tbody.innerHTML = '';
        
        const recentSignals = data.slice(0, 20);
        
        if (recentSignals.length > 0) {
            recentSignals.forEach(signal => {
                const row = document.createElement('tr');
                const isPositive = signal.return >= 0;
                
                row.innerHTML = `
                    <td class="py-4 px-6 text-gray-300">${formatDate(signal.date)}</td>
                    <td class="py-4 px-6 font-semibold">${signal.ticker}</td>
                    <td class="py-4 px-6 text-right text-gray-300">${formatCurrency(signal.entry)}</td>
                    <td class="py-4 px-6 text-right text-gray-300">${formatCurrency(signal.exit)}</td>
                    <td class="py-4 px-6 text-right ${isPositive ? 'text-emerald-400' : 'text-red-400'}">
                        ${isPositive ? '+' : ''}${formatPercent(signal.return)}
                    </td>
                    <td class="py-4 px-6 text-right text-gray-300">${signal.holding_days} days</td>
                `;
                tbody.appendChild(row);
            });
        } else {
            tbody.innerHTML = `
                <tr>
                    <td colspan="6" class="py-8 text-center text-gray-500">No signal history available</td>
                </tr>
            `;
        }
        
        showContent('history');
    } catch (error) {
        console.error('Error loading signal history:', error);
        showError('history');
    }
}

// Load Live Metrics
async function loadMetrics() {
    showLoading('metrics');
    
    try {
        const response = await fetch('data/live-metrics.json');
        if (!response.ok) throw new Error('Failed to load');
        
        const data = await response.json();
        
        document.getElementById('total-signals').textContent = data.total_signals || '--';
        document.getElementById('win-rate').textContent = formatPercent(data.win_rate);
        document.getElementById('avg-return').textContent = formatPercent(data.avg_return);
        document.getElementById('avg-hold').textContent = 
            data.avg_hold_days ? `${data.avg_hold_days.toFixed(1)} days` : '--';
        
        showContent('metrics');
    } catch (error) {
        console.error('Error loading metrics:', error);
        showError('metrics');
    }
}

// Early Access Form Handler
document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('early-access-form');
    const messageEl = document.getElementById('form-message');
    
    if (form) {
        form.addEventListener('submit', (e) => {
            e.preventDefault();
            
            const email = document.getElementById('email-input').value;
            
            // Log to console (for now)
            console.log('Early access signup:', email);
            
            // Show success message
            messageEl.textContent = 'Thank you! We\'ll be in touch soon.';
            messageEl.className = 'mt-4 text-sm text-emerald-400';
            messageEl.classList.remove('hidden');
            
            // Clear input
            document.getElementById('email-input').value = '';
            
            // Hide message after 5 seconds
            setTimeout(() => {
                messageEl.classList.add('hidden');
            }, 5000);
        });
    }
    
    // Load all data
    loadBacktestSummary();
    loadEquityCurve();
    loadLatestSignals();
    loadSignalHistory();
    loadMetrics();
});

// Refresh data every 5 minutes
setInterval(() => {
    loadBacktestSummary();
    loadEquityCurve();
    loadLatestSignals();
    loadSignalHistory();
    loadMetrics();
}, 5 * 60 * 1000);
