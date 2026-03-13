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

// Show/Hide Helpers (null-safe: skip silently if element missing)
const showLoading = (section) => {
    document.getElementById(`${section}-loading`)?.classList.remove('hidden');
    document.getElementById(`${section}-error`)?.classList.add('hidden');
    document.getElementById(`${section}-content`)?.classList.add('hidden');
};

const showError = (section) => {
    document.getElementById(`${section}-loading`)?.classList.add('hidden');
    document.getElementById(`${section}-error`)?.classList.remove('hidden');
    document.getElementById(`${section}-content`)?.classList.add('hidden');
};

const showContent = (section) => {
    document.getElementById(`${section}-loading`)?.classList.add('hidden');
    document.getElementById(`${section}-error`)?.classList.add('hidden');
    document.getElementById(`${section}-content`)?.classList.remove('hidden');
};

// Load Yearly Performance (Backtest Performance section)
async function loadYearlyPerformance() {
    showLoading('yearly');

    try {
        const response = await fetch('data/yearly-performance.json');
        if (!response.ok) throw new Error('Failed to load');

        const data = await response.json();
        const setEl = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };

        // Total summary
        if (data.total) {
            const t = data.total;
            setEl('total-strategy', formatPercent(t.strategy_return));
            setEl('total-spy', formatPercent(t.spy_return));
            setEl('total-qqq', formatPercent(t.qqq_return));
            setEl('total-sharpe', t.sharpe?.toFixed(2) || '--');
        }

        // Yearly breakdown table
        const tbody = document.getElementById('yearly-table');
        if (tbody && data.years) {
            tbody.innerHTML = '';
            data.years.forEach(y => {
                const row = document.createElement('tr');
                row.className = 'border-b border-gray-700/50 hover:bg-gray-800/30';
                const stratColor = y.strategy_return > (y.spy_return || 0) ? 'text-emerald-400' : 'text-red-400';
                row.innerHTML = `
                    <td class="py-4 px-6 font-semibold text-white">${y.year}</td>
                    <td class="py-4 px-6 text-right font-mono ${stratColor}">${formatPercent(y.strategy_return)}</td>
                    <td class="py-4 px-6 text-right font-mono text-gray-300">${formatPercent(y.spy_return)}</td>
                    <td class="py-4 px-6 text-right font-mono text-gray-300">${formatPercent(y.qqq_return)}</td>
                    <td class="py-4 px-6 text-right font-mono text-gray-400">${y.annualized_return != null ? formatPercent(y.annualized_return) : '--'}</td>
                    <td class="py-4 px-6 text-right font-mono text-indigo-400">${y.sharpe != null ? y.sharpe.toFixed(2) : '--'}</td>
                `;
                tbody.appendChild(row);
            });
        }

        setEl('yearly-updated', data.last_updated || '--');
        showContent('yearly');
    } catch (error) {
        console.error('Error loading yearly performance:', error);
        showError('yearly');
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
        // Try live API first (5s timeout), fallback to static JSON
        let response;
        try {
            const controller = new AbortController();
            const timeout = setTimeout(() => controller.abort(), 5000);
            response = await fetch(`${API_BASE}/api/public/signals`, { signal: controller.signal });
            clearTimeout(timeout);
        } catch (e) {
            console.warn('API unavailable or timeout, falling back to static JSON');
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
                    ${pos.quantity ? `
                    <div class="mt-3 px-3 py-2 bg-gray-700/40 rounded-lg flex items-center justify-between text-xs">
                        <span class="text-gray-400">Position Size</span>
                        <span class="font-mono text-cyan-300 font-semibold">${pos.quantity} shares ≈ ${formatCurrency(pos.quantity * pos.entry_price)}</span>
                    </div>` : ''}
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

// Signal Tab Switching
let currentSignalTab = 'active';
function switchSignalTab(tab) {
    currentSignalTab = tab;
    const activeBtn = document.getElementById('tab-active');
    const historyBtn = document.getElementById('tab-history');
    const activeContent = document.getElementById('signals-content');
    const historyContent = document.getElementById('history-trades-content');

    if (tab === 'active') {
        activeBtn.className = 'px-6 py-2.5 rounded-lg font-semibold text-sm bg-gradient-to-r from-indigo-600 to-cyan-600 text-white transition-all';
        historyBtn.className = 'px-6 py-2.5 rounded-lg font-semibold text-sm bg-gray-800 text-gray-400 hover:bg-gray-700 transition-all';
        if (activeContent) activeContent.classList.remove('hidden');
        if (historyContent) historyContent.classList.add('hidden');
    } else {
        historyBtn.className = 'px-6 py-2.5 rounded-lg font-semibold text-sm bg-gradient-to-r from-indigo-600 to-cyan-600 text-white transition-all';
        activeBtn.className = 'px-6 py-2.5 rounded-lg font-semibold text-sm bg-gray-800 text-gray-400 hover:bg-gray-700 transition-all';
        if (activeContent) activeContent.classList.add('hidden');
        if (historyContent) historyContent.classList.remove('hidden');
    }
}

// Load Trade History (closed positions)
async function loadTradeHistory() {
    try {
        let response;
        try {
            const controller = new AbortController();
            const timeout = setTimeout(() => controller.abort(), 5000);
            response = await fetch(`${API_BASE}/api/public/signal-history`, { signal: controller.signal });
            clearTimeout(timeout);
        } catch (e) {
            response = null;
        }
        if (!response || !response.ok) {
            response = await fetch('data/signal-track-record.json');
        }
        if (!response || !response.ok) return;

        const data = await response.json();

        // Render summary stats
        if (data.summary) {
            const s = data.summary;
            const setEl = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };
            setEl('stat-total', s.total_trades || 0);
            setEl('stat-winrate', s.total_trades > 0 ? (s.win_rate * 100).toFixed(1) + '%' : '--');
            setEl('stat-avgreturn', s.total_trades > 0 ? (s.avg_return >= 0 ? '+' : '') + (s.avg_return * 100).toFixed(1) + '%' : '--');
            setEl('stat-holddays', s.avg_hold_days || '--');
            document.getElementById('track-summary')?.classList.remove('hidden');
        }

        // Render closed trade cards
        const container = document.getElementById('closed-trades-cards');
        if (!container || !data.trades) return;
        container.innerHTML = '';

        if (data.trades.length === 0) {
            container.innerHTML = '<div class="col-span-full py-8 text-center text-gray-500">No closed trades yet</div>';
            return;
        }

        data.trades.forEach(trade => {
            const isPositive = trade.return_pct >= 0;
            const returnColor = isPositive ? 'text-emerald-400' : 'text-red-400';
            const returnBg = isPositive ? 'bg-emerald-400/10' : 'bg-red-400/10';

            // Exit reason badge
            let reasonBadge = '';
            if (trade.exit_reason === 'take_profit') {
                reasonBadge = '<span class="px-2 py-0.5 rounded text-xs bg-emerald-900/50 text-emerald-300 border border-emerald-800">Take Profit</span>';
            } else if (trade.exit_reason === 'stop_loss') {
                reasonBadge = '<span class="px-2 py-0.5 rounded text-xs bg-red-900/50 text-red-300 border border-red-800">Stop Loss</span>';
            } else if (trade.exit_reason === 'rotation_exit') {
                reasonBadge = '<span class="px-2 py-0.5 rounded text-xs bg-cyan-900/50 text-cyan-300 border border-cyan-800">Rotation</span>';
            } else {
                reasonBadge = '<span class="px-2 py-0.5 rounded text-xs bg-gray-700 text-gray-400">Closed</span>';
            }

            const card = document.createElement('div');
            card.className = 'bg-gray-800/60 border border-gray-700 rounded-xl p-4 hover:border-gray-600 transition-colors';
            card.innerHTML = `
                <div class="flex items-center justify-between mb-3">
                    <div class="flex items-center gap-2">
                        <span class="text-lg font-bold text-white">${trade.ticker}</span>
                        ${reasonBadge}
                    </div>
                    <div class="px-3 py-1 rounded-lg ${returnBg}">
                        <span class="font-mono font-bold ${returnColor}">
                            ${isPositive ? '+' : ''}${(trade.return_pct * 100).toFixed(1)}%
                        </span>
                    </div>
                </div>
                <div class="grid grid-cols-2 gap-2 text-sm">
                    <div>
                        <p class="text-gray-500 text-xs">Entry</p>
                        <p class="font-mono text-gray-300">$${trade.entry_price.toFixed(2)}</p>
                    </div>
                    <div>
                        <p class="text-gray-500 text-xs">Exit</p>
                        <p class="font-mono text-gray-300">$${trade.exit_price.toFixed(2)}</p>
                    </div>
                </div>
                <div class="flex justify-between items-center mt-2 text-xs text-gray-500">
                    <span>${trade.entry_date} → ${trade.exit_date}</span>
                    <span>${trade.hold_days}d</span>
                </div>
            `;
            container.appendChild(card);
        });
    } catch (error) {
        console.error('Error loading trade history:', error);
    }
}

// Load Weekly Rotation History
async function loadSignalHistory() {
    showLoading('history');

    try {
        const response = await fetch('data/signal-history.json');
        if (!response.ok) throw new Error('Failed to load');

        const data = await response.json();

        // Desktop table
        const tbody = document.getElementById('history-table');
        // Mobile cards
        const mobile = document.getElementById('history-mobile');

        if (tbody) tbody.innerHTML = '';
        if (mobile) mobile.innerHTML = '';

        const recent = data.slice(0, 20);

        if (recent.length > 0) {
            recent.forEach(item => {
                const isPositive = (item.weekly_return || 0) >= 0;
                const returnColor = isPositive ? 'text-emerald-400' : 'text-red-400';

                // Regime badge color
                let regimeColor = 'text-cyan-400';
                if (item.regime === 'BULL') regimeColor = 'text-emerald-400';
                else if (item.regime === 'BEAR') regimeColor = 'text-red-400';

                // Desktop row
                if (tbody) {
                    const row = document.createElement('tr');
                    row.className = 'border-b border-gray-700/50 hover:bg-gray-800/30';
                    row.innerHTML = `
                        <td class="py-4 px-6 text-gray-300">${item.week || '--'}</td>
                        <td class="py-4 px-6 font-semibold ${regimeColor}">${item.regime || '--'}</td>
                        <td class="py-4 px-6 text-gray-300">${item.holdings || '--'}</td>
                        <td class="py-4 px-6 text-right font-mono ${returnColor}">
                            ${isPositive ? '+' : ''}${formatPercent(item.weekly_return)}
                        </td>
                        <td class="py-4 px-6 text-right font-mono text-cyan-400">
                            ${item.cumulative != null ? (item.cumulative * 100 - 100).toFixed(1) + '%' : '--'}
                        </td>
                    `;
                    tbody.appendChild(row);
                }

                // Mobile card
                if (mobile) {
                    const card = document.createElement('div');
                    card.className = 'p-4 border-b border-gray-700/50';
                    card.innerHTML = `
                        <div class="flex justify-between items-center mb-2">
                            <span class="text-gray-400 text-sm">${item.week || '--'}</span>
                            <span class="font-semibold ${regimeColor}">${item.regime || '--'}</span>
                        </div>
                        <p class="text-gray-300 text-sm mb-1">${item.holdings || '--'}</p>
                        <div class="flex justify-between">
                            <span class="font-mono ${returnColor}">${isPositive ? '+' : ''}${formatPercent(item.weekly_return)}</span>
                            <span class="font-mono text-cyan-400 text-sm">Cum: ${item.cumulative != null ? (item.cumulative * 100 - 100).toFixed(1) + '%' : '--'}</span>
                        </div>
                    `;
                    mobile.appendChild(card);
                }
            });
        } else {
            if (tbody) tbody.innerHTML = `<tr><td colspan="5" class="py-8 text-center text-gray-500">No rotation history available</td></tr>`;
        }

        showContent('history');
    } catch (error) {
        console.error('Error loading rotation history:', error);
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
        
        const setM = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };
        setM('total-signals', data.total_signals || '--');
        setM('win-rate', formatPercent(data.win_rate));
        setM('avg-return', formatPercent(data.avg_return));
        setM('avg-hold', data.avg_hold_days ? `${data.avg_hold_days.toFixed(1)} days` : '--');
        
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
    
    // Load all data (each independent, one failure doesn't block others)
    loadYearlyPerformance().catch(() => {});
    loadEquityCurve().catch(() => {});
    loadLatestSignals().catch(() => {});
    loadTradeHistory().catch(() => {});
    loadSignalHistory().catch(() => {});
    loadMetrics().catch(() => {});
});

// Refresh data every 5 minutes
setInterval(() => {
    loadYearlyPerformance().catch(() => {});
    loadEquityCurve().catch(() => {});
    loadLatestSignals().catch(() => {});
    loadTradeHistory().catch(() => {});
    loadSignalHistory().catch(() => {});
    loadMetrics().catch(() => {});
}, 5 * 60 * 1000);
