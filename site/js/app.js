/**
 * StockQueen Marketing Website - Data Loading Module
 * Loads JSON data and renders all sections
 */

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
        document.getElementById('annualized-return').textContent = formatPercent(data.annualized_return);
        document.getElementById('spy-return').textContent = formatPercent(data.spy_return);
        document.getElementById('qqq-return').textContent = formatPercent(data.qqq_return);
        document.getElementById('alpha-spy').textContent = formatPercent(data.alpha_vs_spy);
        document.getElementById('alpha-qqq').textContent = formatPercent(data.alpha_vs_qqq);
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

// Load Latest Signals
async function loadLatestSignals() {
    showLoading('signals');
    
    try {
        const response = await fetch('data/latest-signals.json');
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
        
        // Update positions table
        const tbody = document.getElementById('positions-table');
        tbody.innerHTML = '';
        
        if (data.positions && data.positions.length > 0) {
            data.positions.forEach(pos => {
                const row = document.createElement('tr');
                const isPositive = pos.return_pct >= 0;
                
                row.innerHTML = `
                    <td class="py-4 px-4 font-semibold">${pos.ticker}</td>
                    <td class="py-4 px-4 text-right text-gray-300">${formatCurrency(pos.entry_price)}</td>
                    <td class="py-4 px-4 text-right text-gray-300">${formatCurrency(pos.current_price)}</td>
                    <td class="py-4 px-4 text-right ${isPositive ? 'text-emerald-400' : 'text-red-400'}">
                        ${isPositive ? '+' : ''}${formatPercent(pos.return_pct)}
                    </td>
                `;
                tbody.appendChild(row);
            });
        } else {
            tbody.innerHTML = `
                <tr>
                    <td colspan="4" class="py-8 text-center text-gray-500">No active positions</td>
                </tr>
            `;
        }
        
        showContent('signals');
    } catch (error) {
        console.error('Error loading latest signals:', error);
        showError('signals');
    }
}

// Load Signal History (Weekly Rotation)
async function loadSignalHistory() {
    showLoading('history');
    
    try {
        const response = await fetch('data/signal-history.json');
        if (!response.ok) throw new Error('Failed to load');
        
        const data = await response.json();
        
        // Update history table (show last 10 weeks)
        const tbody = document.getElementById('history-table');
        tbody.innerHTML = '';
        
        const recentWeeks = data.slice(0, 10);
        
        if (recentWeeks.length > 0) {
            recentWeeks.forEach(week => {
                const row = document.createElement('tr');
                const isPositive = week.weekly_return >= 0;
                
                // Style regime badge
                let regimeClass = 'regime-neutral';
                if (week.regime === 'BULL') regimeClass = 'regime-bull';
                if (week.regime === 'BEAR') regimeClass = 'regime-bear';
                
                row.innerHTML = `
                    <td class="py-4 px-6 text-gray-300">${week.week}</td>
                    <td class="py-4 px-6">
                        <span class="px-3 py-1 rounded-full text-xs font-medium ${regimeClass}">${week.regime}</span>
                    </td>
                    <td class="py-4 px-6 text-gray-300">${week.holdings}</td>
                    <td class="py-4 px-6 text-right ${isPositive ? 'text-emerald-400' : 'text-red-400'}">
                        ${isPositive ? '+' : ''}${formatPercent(week.weekly_return)}
                    </td>
                    <td class="py-4 px-6 text-right text-cyan-400">${(week.cumulative * 100 - 100).toFixed(1)}%</td>
                `;
                tbody.appendChild(row);
            });
        } else {
            tbody.innerHTML = `
                <tr>
                    <td colspan="5" class="py-8 text-center text-gray-500">No rotation history available</td>
                </tr>
            `;
        }
        
        showContent('history');
    } catch (error) {
        console.error('Error loading signal history:', error);
        showError('history');
    }
}

// Load Live Metrics (Static display - no fetch needed)
async function loadMetrics() {
    showLoading('metrics');
    
    try {
        // These are static values displayed directly in HTML
        // Just simulate a brief loading for UX consistency
        await new Promise(resolve => setTimeout(resolve, 300));
        
        showContent('metrics');
    } catch (error) {
        console.error('Error loading metrics:', error);
        showError('metrics');
    }
}

// Investor Inquiry Form Handler
function initInvestorForm() {
    const form = document.getElementById('investor-form');
    const messageEl = document.getElementById('inquiry-message');
    
    if (!form) return;
    
    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        
        const submitBtn = form.querySelector('button[type="submit"]');
        const originalText = submitBtn.textContent;
        
        // Get form data
        const formData = {
            country: document.getElementById('country').value,
            name: document.getElementById('name').value,
            experience: document.getElementById('experience').value,
            capital: document.getElementById('capital').value,
            riskTolerance: document.getElementById('risk-tolerance').value,
            email: document.getElementById('email').value,
            submittedAt: new Date().toISOString()
        };
        
        // Disable submit button
        submitBtn.disabled = true;
        submitBtn.textContent = 'Submitting...';
        
        try {
            // Send to Formspree
            const response = await fetch('https://formspree.io/f/xgonyjwn', {
                method: 'POST',
                headers: { 
                    'Content-Type': 'application/json',
                    'Accept': 'application/json'
                },
                body: JSON.stringify({
                    country: formData.country,
                    name: formData.name,
                    experience: formData.experience,
                    capital: formData.capital,
                    expectedReturn: formData.expectedReturn,
                    email: formData.email,
                    _subject: `New Investor Inquiry from ${formData.name}`,
                    message: `
Country: ${formData.country}
Name: ${formData.name}
Experience: ${formData.experience}
Capital: ${formData.capital}
Risk Tolerance: ${formData.riskTolerance}
Email: ${formData.email}
Submitted: ${formData.submittedAt}
                    `.trim()
                })
            });
            
            if (!response.ok) {
                throw new Error('Form submission failed');
            }
            
            // Show success message
            messageEl.textContent = 'Thank you for your inquiry. We will review your information and contact you if there is a potential fit.';
            messageEl.className = 'mt-4 text-sm text-emerald-400';
            messageEl.classList.remove('hidden');
            
            // Clear form
            form.reset();
            
        } catch (error) {
            console.error('Error submitting inquiry:', error);
            messageEl.textContent = 'Sorry, there was an error submitting your inquiry. Please try again or contact us directly.';
            messageEl.className = 'mt-4 text-sm text-red-400';
            messageEl.classList.remove('hidden');
        } finally {
            // Re-enable submit button
            submitBtn.disabled = false;
            submitBtn.textContent = originalText;
            
            // Hide message after 8 seconds
            setTimeout(() => {
                messageEl.classList.add('hidden');
            }, 8000);
        }
    });
}

// Early Access Form Handler
function initEarlyAccessForm() {
    const form = document.getElementById('early-access-form');
    const messageEl = document.getElementById('form-message');
    
    if (!form) return;
    
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

// Initialize all forms and load data
document.addEventListener('DOMContentLoaded', () => {
    initInvestorForm();
    initEarlyAccessForm();
    
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
