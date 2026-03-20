/**
 * StockQueen Marketing Website - Data Loading Module
 * Loads JSON data and renders all sections
 */

// API base URL — live backend for real-time data
const API_BASE = 'https://stockqueen-api.onrender.com';

// Utility: fetch with timeout, API first then static fallback
async function apiFetch(apiPath, staticPath, timeoutMs = 15000) {
    let response = null;
    let isLive = false;
    try {
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), timeoutMs);
        response = await fetch(`${API_BASE}${apiPath}`, { signal: controller.signal });
        clearTimeout(timer);
        if (response.ok) isLive = true;
    } catch (e) {
        console.warn(`API ${apiPath} unavailable, falling back to ${staticPath || 'none'}`);
        response = null;
    }
    if ((!response || !response.ok) && staticPath) {
        response = await fetch(staticPath);
    }
    if (!response || !response.ok) throw new Error('Failed to load');
    const data = await response.json();
    return { data, isLive };
}

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

// Detect language
const isZh = () => (document.documentElement.lang || '').startsWith('zh');

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

// =================================================================
// Load Yearly Performance — API first, fallback to static JSON
// =================================================================
async function loadYearlyPerformance() {
    showLoading('yearly');

    try {
        let data;
        try {
            const result = await apiFetch('/api/public/yearly-performance', null, 10000);
            data = result.data;
            // If API returned fallback flag, use static JSON
            if (data.fallback) throw new Error('API returned fallback');
        } catch (e) {
            const response = await fetch('data/yearly-performance.json');
            if (!response.ok) throw new Error('Failed to load');
            data = await response.json();
        }

        const setEl = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };

        // Total summary
        if (data.total) {
            const t = data.total;
            setEl('total-strategy', formatPercent(t.strategy_return));
            setEl('total-spy', t.spy_return != null ? formatPercent(t.spy_return) : '--');
            setEl('total-qqq', t.qqq_return != null ? formatPercent(t.qqq_return) : '--');
            setEl('total-sharpe', t.sharpe?.toFixed(2) || '--');
            setEl('total-alpha-spy', t.alpha_vs_spy != null ? '+' + formatPercent(t.alpha_vs_spy) : '--');
            setEl('total-alpha-qqq', t.alpha_vs_qqq != null ? '+' + formatPercent(t.alpha_vs_qqq) : '--');
            setEl('total-maxdd', t.max_drawdown != null ? formatPercent(t.max_drawdown) : '--');
            setEl('total-winrate', t.win_rate != null ? formatPercent(t.win_rate) : '--');
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

        // Show source badge
        const srcEl = document.getElementById('yearly-source');
        if (srcEl) {
            if (data.source === 'database') {
                srcEl.innerHTML = '<span class="ml-2 px-2 py-0.5 text-xs rounded bg-emerald-900/50 text-emerald-300 border border-emerald-800">Auto</span>';
            } else {
                srcEl.innerHTML = '<span class="ml-2 px-2 py-0.5 text-xs rounded bg-gray-700 text-gray-400">Static</span>';
            }
        }

        showContent('yearly');
    } catch (error) {
        console.error('Error loading yearly performance:', error);
        showError('yearly');
    }
}

// =================================================================
// Load Equity Curve
// =================================================================
async function loadEquityCurve() {
    showLoading('chart');

    try {
        let points, source = 'static', lastUpdated = null;
        try {
            const result = await apiFetch('/api/public/equity-curve', null, 10000);
            const resp = result.data;
            if (resp.points && resp.points.length) {
                points = resp.points;
                source = resp.source || 'static';
                lastUpdated = resp.last_updated;
            } else {
                throw new Error('No points');
            }
        } catch (e) {
            const response = await fetch('data/equity-curve.json');
            if (!response.ok) throw new Error('Failed to load');
            points = await response.json();
        }

        const updatedEl = document.getElementById('chart-updated');
        if (updatedEl) updatedEl.textContent = lastUpdated || '--';
        const srcEl = document.getElementById('chart-source');
        if (srcEl) {
            srcEl.innerHTML = source === 'database'
                ? '<span class="ml-2 px-2 py-0.5 text-xs rounded bg-emerald-900/50 text-emerald-300 border border-emerald-800">Auto</span>'
                : '<span class="ml-2 px-2 py-0.5 text-xs rounded bg-gray-700 text-gray-400">Static</span>';
        }

        // showContent first, then wait for browser reflow before Chart.js reads canvas dimensions
        showContent('chart');
        await new Promise(resolve => requestAnimationFrame(resolve));
        if (typeof renderEquityChart === 'function') {
            renderEquityChart(points);
        }
    } catch (error) {
        console.error('Error loading equity curve:', error);
        showError('chart');
    }
}

// =================================================================
// Load Latest Signals (real-time from API, fallback to static JSON)
// =================================================================
async function loadLatestSignals() {
    showLoading('signals');

    try {
        const { data, isLive } = await apiFetch('/api/public/signals', 'data/latest-signals.json');

        // Update market regime
        const regimeEl = document.getElementById('market-regime');
        if (regimeEl) {
            regimeEl.textContent = data.market_regime || '--';
            regimeEl.className = 'text-2xl font-bold';
            if (data.market_regime === 'BULL' || data.market_regime === 'STRONG_BULL') {
                regimeEl.classList.add('text-emerald-400');
            } else if (data.market_regime === 'BEAR') {
                regimeEl.classList.add('text-red-400');
            } else {
                regimeEl.classList.add('text-cyan-400');
            }
        }

        const signalDateEl = document.getElementById('signal-date');
        if (signalDateEl) {
            const badge = isLive
                ? '<span class="ml-2 px-2 py-0.5 text-xs rounded bg-emerald-900/50 text-emerald-300 border border-emerald-800">Live</span>'
                : '<span class="ml-2 px-2 py-0.5 text-xs rounded bg-gray-700 text-gray-400">Cached</span>';
            signalDateEl.innerHTML = formatDate(data.date) + badge;
        }

        // Update position cards
        const container = document.getElementById('positions-cards');
        if (!container) {
            console.warn('positions-cards element not found — check HTML structure');
            showContent('signals');
            return;
        }
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
                            <div class="relative h-3 bg-gray-700 rounded-full">
                                <div class="absolute top-0 h-full w-0.5 bg-white/40 z-10 rounded-full" style="left:${entryPos}%"></div>
                                <div class="absolute top-0 h-full rounded-full ${barColor}" style="width:${currentPos}%"></div>
                                <div class="absolute top-1/2 w-3 h-3 rounded-full border-2 z-20 ${barColor === 'bg-emerald-400' ? 'border-emerald-400 bg-emerald-400/30' : 'border-red-400 bg-red-400/30'}" style="left:${currentPos}%; transform:translate(-50%,-50%)"></div>
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
            container.innerHTML = `<div class="col-span-full py-8 text-center text-gray-500">${isZh() ? '暂无活跃持仓' : 'No active positions'}</div>`;
        }

        showContent('signals');
    } catch (error) {
        console.error('Error loading latest signals:', error);
        showError('signals');
    }
}

// =================================================================
// Load Weekly Rotation History — API first, fallback to static JSON
// Merged with Signal Track Record
// =================================================================
async function loadSignalHistory() {
    showLoading('history');

    try {
        let historyItems = [];
        let isLive = false;

        // Try API first
        try {
            const result = await apiFetch('/api/public/rotation-history', null, 10000);
            const apiData = result.data;
            isLive = result.isLive;

            if (apiData.history && apiData.history.length > 0) {
                historyItems = apiData.history;
            } else {
                throw new Error('Empty API response');
            }
        } catch (e) {
            // Fallback to static JSON
            const response = await fetch('data/signal-history.json');
            if (!response.ok) throw new Error('Failed to load');
            historyItems = await response.json();
        }

        // Desktop table
        const tbody = document.getElementById('history-table');
        // Mobile cards
        const mobile = document.getElementById('history-mobile');

        if (tbody) tbody.innerHTML = '';
        if (mobile) mobile.innerHTML = '';

        const recent = historyItems.slice(0, 20);

        if (recent.length > 0) {
            recent.forEach((item, idx) => {
                const isPositive = (item.return_1w || 0) >= 0;
                const returnColor = isPositive ? 'text-emerald-400' : 'text-red-400';
                const isLatest = item.is_latest || idx === 0;

                // Regime badge color
                let regimeColor = 'text-cyan-400';
                let regimeBg = 'bg-cyan-900/30 border-cyan-800';
                if (item.regime === 'BULL' || item.regime === 'STRONG_BULL') {
                    regimeColor = 'text-emerald-400';
                    regimeBg = 'bg-emerald-900/30 border-emerald-800';
                } else if (item.regime === 'BEAR') {
                    regimeColor = 'text-red-400';
                    regimeBg = 'bg-red-900/30 border-red-800';
                }

                // Holdings: API returns array, static returns comma string
                let holdParts;
                if (Array.isArray(item.holdings)) {
                    holdParts = item.holdings;
                } else {
                    holdParts = (item.holdings || '').split(',').map(s => s.trim());
                }
                const maskedHoldings = holdParts.length > 1
                    ? holdParts[0] + ', ' + holdParts.slice(1).map(() => '***').join(', ')
                    : holdParts[0] || '--';

                // (hold_days removed — not meaningful for weekly display)

                // Latest week highlight
                const latestBadge = isLatest
                    ? `<span class="ml-2 px-1.5 py-0.5 text-[10px] rounded bg-amber-500/20 text-amber-300 border border-amber-500/30 animate-pulse">${isZh() ? '本周' : 'THIS WEEK'}</span>`
                    : '';

                const rowBorder = isLatest
                    ? 'border-b-2 border-amber-500/40 bg-amber-500/5'
                    : 'border-b border-gray-700/50 hover:bg-gray-800/30';

                // Desktop row
                if (tbody) {
                    const row = document.createElement('tr');
                    row.className = rowBorder;
                    row.innerHTML = `
                        <td class="py-4 px-6 text-gray-300">${formatDate(item.week) || item.week || '--'}${latestBadge}</td>
                        <td class="py-4 px-6">
                            <span class="px-2 py-1 rounded text-xs font-semibold ${regimeColor} ${regimeBg} border">${item.regime || '--'}</span>
                        </td>
                        <td class="py-4 px-6 text-gray-300 font-mono text-sm">${maskedHoldings}</td>
                        <td class="py-4 px-6 text-right font-mono ${returnColor}">
                            ${item.return_1w != null ? (isPositive ? '+' : '') + formatPercent(item.return_1w) : '--'}
                        </td>
                    `;
                    tbody.appendChild(row);
                }

                // Mobile card
                if (mobile) {
                    const card = document.createElement('div');
                    card.className = isLatest
                        ? 'p-4 border-b-2 border-amber-500/40 bg-amber-500/5'
                        : 'p-4 border-b border-gray-700/50';
                    card.innerHTML = `
                        <div class="flex justify-between items-center mb-2">
                            <span class="text-gray-400 text-sm">${formatDate(item.week) || item.week || '--'}${latestBadge}</span>
                            <span class="px-2 py-0.5 rounded text-xs font-semibold ${regimeColor} ${regimeBg} border">${item.regime || '--'}</span>
                        </div>
                        <p class="text-gray-300 text-sm mb-1 font-mono">${maskedHoldings}</p>
                        <div class="flex justify-between">
                            <span class="font-mono ${returnColor}">${item.return_1w != null ? (isPositive ? '+' : '') + formatPercent(item.return_1w) : '--'}</span>
                        </div>
                    `;
                    mobile.appendChild(card);
                }
            });
        } else {
            if (tbody) tbody.innerHTML = `<tr><td colspan="4" class="py-8 text-center text-gray-500">${isZh() ? '暂无轮动历史' : 'No rotation history available'}</td></tr>`;
        }

        // Source badge
        const histSrcEl = document.getElementById('history-source');
        if (histSrcEl) {
            histSrcEl.innerHTML = isLive
                ? '<span class="px-2 py-0.5 text-xs rounded bg-emerald-900/50 text-emerald-300 border border-emerald-800">Live</span>'
                : '<span class="px-2 py-0.5 text-xs rounded bg-gray-700 text-gray-400">Cached</span>';
        }

        showContent('history');
    } catch (error) {
        console.error('Error loading rotation history:', error);
        showError('history');
    }
}

// =================================================================
// Load Regime State Machine — visual regime dashboard
// =================================================================
async function loadRegimeStateMachine() {
    showLoading('regime');

    try {
        const { data } = await apiFetch('/api/public/regime-details', 'data/regime-details.json', 10000);

        if (data.error && !data.regime) {
            throw new Error(data.error);
        }

        const regime = (data.regime || 'unknown').toLowerCase();
        const score = data.score || 0;
        const signals = data.signals || [];
        const spyPrice = data.spy_price || 0;
        const thresholds = data.regime_thresholds || [];

        // Regime display config
        const regimeConfig = {
            strong_bull: { label: isZh() ? '强牛市' : 'STRONG BULL', color: 'text-emerald-300', bg: 'from-emerald-600/30 to-emerald-900/30', border: 'border-emerald-500', icon: '🚀' },
            bull:        { label: isZh() ? '牛市' : 'BULL', color: 'text-emerald-400', bg: 'from-emerald-600/20 to-emerald-900/20', border: 'border-emerald-600', icon: '📈' },
            choppy:      { label: isZh() ? '震荡' : 'CHOPPY', color: 'text-cyan-400', bg: 'from-cyan-600/20 to-cyan-900/20', border: 'border-cyan-600', icon: '📊' },
            bear:        { label: isZh() ? '熊市' : 'BEAR', color: 'text-red-400', bg: 'from-red-600/20 to-red-900/20', border: 'border-red-600', icon: '🐻' },
        };
        const cfg = regimeConfig[regime] || regimeConfig.choppy;

        const container = document.getElementById('regime-content');
        if (!container) { showContent('regime'); return; }

        // Build regime state machine HTML
        let signalsHtml = '';
        signals.forEach(sig => {
            const contribColor = sig.contribution > 0 ? 'text-emerald-400' : sig.contribution < 0 ? 'text-red-400' : 'text-gray-400';
            const contribSign = sig.contribution > 0 ? '+' : '';
            signalsHtml += `
                <div class="flex items-center justify-between py-2 px-3 rounded-lg bg-gray-800/40">
                    <div class="flex-1">
                        <span class="text-sm text-gray-300">${sig.name}</span>
                        <span class="text-xs text-gray-500 ml-2">${sig.description || ''}</span>
                    </div>
                    <div class="flex items-center gap-3">
                        <span class="font-mono text-sm text-gray-300">${sig.value}${sig.unit || ''}</span>
                        <span class="font-mono text-sm font-bold ${contribColor}">${contribSign}${sig.contribution}</span>
                    </div>
                </div>`;
        });

        // Score bar visualization: -5 to +5
        const scoreMin = -5, scoreMax = 5;
        const scorePercent = Math.max(0, Math.min(100, ((score - scoreMin) / (scoreMax - scoreMin)) * 100));

        // Threshold markers on the bar
        const thresholdMarkers = [
            { score: -2, label: isZh() ? '熊' : 'Bear' },
            { score: -1, label: '' },
            { score: 1, label: isZh() ? '牛' : 'Bull' },
            { score: 4, label: isZh() ? '强牛' : 'Strong' },
        ];
        let markersHtml = '';
        thresholdMarkers.forEach(m => {
            const pct = ((m.score - scoreMin) / (scoreMax - scoreMin)) * 100;
            markersHtml += `<div class="absolute top-0 h-full w-px bg-gray-500/50" style="left:${pct}%"></div>`;
        });

        // State machine visualization (horizontal states)
        const states = [
            { key: 'bear', label: isZh() ? '熊市' : 'Bear', range: '≤-2', color: 'red' },
            { key: 'choppy', label: isZh() ? '震荡' : 'Choppy', range: '-1~0', color: 'cyan' },
            { key: 'bull', label: isZh() ? '牛市' : 'Bull', range: '1~3', color: 'emerald' },
            { key: 'strong_bull', label: isZh() ? '强牛' : 'Strong Bull', range: '≥4', color: 'emerald' },
        ];

        let statesHtml = '<div class="flex gap-2 justify-center flex-wrap">';
        states.forEach(s => {
            const isActive = s.key === regime;
            const activeClass = isActive
                ? `ring-2 ring-${s.color}-400 bg-${s.color}-500/20 border-${s.color}-400`
                : 'bg-gray-800/40 border-gray-700 opacity-60';
            const textClass = isActive ? `text-${s.color}-400 font-bold` : 'text-gray-500';
            statesHtml += `
                <div class="flex-1 min-w-[80px] max-w-[140px] p-3 rounded-xl border ${activeClass} text-center transition-all">
                    <p class="${textClass} text-sm">${s.label}</p>
                    <p class="text-[10px] text-gray-500 mt-1">${isZh() ? '分数' : 'Score'}: ${s.range}</p>
                    ${isActive ? '<div class="w-2 h-2 rounded-full bg-current mx-auto mt-2 animate-pulse"></div>' : ''}
                </div>`;
        });
        statesHtml += '</div>';

        container.innerHTML = `
            <!-- Current Regime Hero -->
            <div class="glass-card p-6 rounded-2xl mb-6 bg-gradient-to-r ${cfg.bg} border ${cfg.border}">
                <div class="flex items-center justify-between flex-wrap gap-4">
                    <div>
                        <p class="text-gray-400 text-sm mb-1">${isZh() ? '当前市场状态' : 'Current Market Regime'}</p>
                        <div class="flex items-center gap-3">
                            <span class="text-3xl">${cfg.icon}</span>
                            <span class="text-3xl font-bold ${cfg.color}">${cfg.label}</span>
                        </div>
                    </div>
                    <div class="text-right">
                        <p class="text-gray-400 text-sm">${isZh() ? '综合评分' : 'Composite Score'}</p>
                        <p class="text-4xl font-bold font-mono ${cfg.color}">${score >= 0 ? '+' : ''}${score}</p>
                        <p class="text-xs text-gray-500">SPY $${spyPrice}</p>
                    </div>
                </div>
            </div>

            <!-- State Machine Visualization -->
            <div class="glass-card p-5 rounded-2xl mb-6">
                <h4 class="text-sm font-semibold text-gray-400 mb-4">${isZh() ? '状态机' : 'State Machine'}</h4>
                ${statesHtml}
                <!-- Score Bar -->
                <div class="mt-5">
                    <div class="relative h-3 bg-gray-700 rounded-full overflow-visible">
                        ${markersHtml}
                        <div class="absolute top-1/2 -translate-y-1/2 w-4 h-4 rounded-full border-2 border-white shadow-lg z-10 transition-all"
                             style="left:${scorePercent}%; background: ${score >= 1 ? '#34d399' : score >= -1 ? '#22d3ee' : '#f87171'}; transform: translate(-50%, -50%);">
                        </div>
                    </div>
                    <div class="flex justify-between text-[10px] text-gray-500 mt-1">
                        <span>-5</span>
                        <span>0</span>
                        <span>+5</span>
                    </div>
                </div>
            </div>

            <!-- Signal Breakdown -->
            <div class="glass-card p-5 rounded-2xl">
                <h4 class="text-sm font-semibold text-gray-400 mb-3">${isZh() ? '信号分解' : 'Signal Breakdown'}</h4>
                <div class="space-y-2">
                    ${signalsHtml}
                </div>
            </div>
        `;

        showContent('regime');
    } catch (error) {
        console.error('Error loading regime state machine:', error);
        showError('regime');
    }
}

// =================================================================
// Load Live Metrics
// =================================================================
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

// Newsletter Subscribe API
const SUBSCRIBE_API = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1'
    ? 'http://localhost:8001'
    : 'https://stockqueen-api.onrender.com';

// Early Access / Newsletter Form Handler
document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('early-access-form');
    const messageEl = document.getElementById('form-message');

    if (form) {
        form.addEventListener('submit', async (e) => {
            e.preventDefault();

            const emailInput = document.getElementById('email-input');
            const email = emailInput.value;
            const submitBtn = form.querySelector('button[type="submit"]');
            const originalText = submitBtn.textContent;

            // Auto-detect language
            const lang = (document.documentElement.lang || navigator.language || '').startsWith('zh') ? 'zh' : 'en';

            // Show loading
            submitBtn.textContent = lang === 'zh' ? '订阅中...' : 'Subscribing...';
            submitBtn.disabled = true;

            try {
                const response = await fetch(`${SUBSCRIBE_API}/api/newsletter/subscribe`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ email, lang })
                });

                const data = await response.json();

                if (response.ok && data.success) {
                    messageEl.textContent = lang === 'zh'
                        ? '订阅成功！请查收欢迎邮件 🎉'
                        : 'Subscribed! Check your inbox for a welcome email 🎉';
                    messageEl.className = 'mt-4 text-sm text-emerald-400';
                    emailInput.value = '';
                } else {
                    throw new Error(data.error || 'Subscription failed');
                }
            } catch (error) {
                console.error('Subscribe error:', error);
                messageEl.textContent = lang === 'zh'
                    ? '订阅失败，请稍后重试'
                    : 'Something went wrong. Please try again later.';
                messageEl.className = 'mt-4 text-sm text-red-400';
            } finally {
                submitBtn.textContent = originalText;
                submitBtn.disabled = false;
                messageEl.classList.remove('hidden');
                setTimeout(() => messageEl.classList.add('hidden'), 5000);
            }
        });
    }

    // Load all data (each independent, one failure doesn't block others)
    loadYearlyPerformance().catch(() => {});
    loadEquityCurve().catch(() => {});
    loadLatestSignals().catch(() => {});
    loadSignalHistory().catch(() => {});
    loadRegimeStateMachine().catch(() => {});
    loadMetrics().catch(() => {});
});

// Refresh data every 5 minutes
setInterval(() => {
    loadYearlyPerformance().catch(() => {});
    loadEquityCurve().catch(() => {});
    loadLatestSignals().catch(() => {});
    loadSignalHistory().catch(() => {});
    loadRegimeStateMachine().catch(() => {});
    loadMetrics().catch(() => {});
}, 5 * 60 * 1000);
