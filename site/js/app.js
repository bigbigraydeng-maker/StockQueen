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

// Load Yearly Performance
async function loadYearlyPerformance() {
    showLoading('yearly');
    
    try {
        const response = await fetch('data/yearly-performance.json');
        if (!response.ok) throw new Error('Failed to load');
        
        const data = await response.json();
        
        // Update total performance
        document.getElementById('total-strategy').textContent = formatPercent(data.total.strategy_return);
        document.getElementById('total-spy').textContent = formatPercent(data.total.spy_return);
        document.getElementById('total-qqq').textContent = formatPercent(data.total.qqq_return);
        document.getElementById('total-sharpe').textContent = data.total.sharpe.toFixed(2);
        
        // Update yearly table
        const tbody = document.getElementById('yearly-table');
        tbody.innerHTML = '';
        
        data.years.forEach(year => {
            const row = document.createElement('tr');
            const strategyPositive = year.strategy_return >= 0;
            const spyPositive = year.spy_return >= 0;
            const qqqPositive = year.qqq_return >= 0;
            
            row.innerHTML = `
                <td class="py-4 px-6 text-gray-300 font-medium">${year.year}</td>
                <td class="py-4 px-6 text-right ${strategyPositive ? 'text-emerald-400' : 'text-red-400'}">
                    ${strategyPositive ? '+' : ''}${formatPercent(year.strategy_return)}
                </td>
                <td class="py-4 px-6 text-right ${spyPositive ? 'text-gray-300' : 'text-red-400'}">
                    ${spyPositive ? '+' : ''}${formatPercent(year.spy_return)}
                </td>
                <td class="py-4 px-6 text-right ${qqqPositive ? 'text-gray-300' : 'text-red-400'}">
                    ${qqqPositive ? '+' : ''}${formatPercent(year.qqq_return)}
                </td>
                <td class="py-4 px-6 text-right text-cyan-400">${formatPercent(year.annualized_return)}</td>
                <td class="py-4 px-6 text-right text-indigo-400">${year.sharpe.toFixed(2)}</td>
            `;
            tbody.appendChild(row);
        });
        
        document.getElementById('yearly-updated').textContent = formatDate(data.last_updated);
        
        showContent('yearly');
    } catch (error) {
        console.error('Error loading yearly performance:', error);
        showError('yearly');
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
        const mobileContainer = document.getElementById('history-mobile');
        tbody.innerHTML = '';
        if (mobileContainer) mobileContainer.innerHTML = '';
        
        const recentWeeks = data.slice(0, 10);
        
        if (recentWeeks.length > 0) {
            recentWeeks.forEach((week, index) => {
                const isPositive = week.weekly_return >= 0;
                
                // Style regime badge
                let regimeClass = 'regime-neutral';
                if (week.regime === 'BULL') regimeClass = 'regime-bull';
                if (week.regime === 'BEAR') regimeClass = 'regime-bear';
                
                // Desktop table row
                const row = document.createElement('tr');
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
                
                // Mobile card
                if (mobileContainer) {
                    const card = document.createElement('div');
                    card.className = `p-4 border-b border-gray-700/50 last:border-b-0 ${index % 2 === 0 ? 'bg-gray-800/20' : ''}`;
                    card.innerHTML = `
                        <div class="flex justify-between items-start mb-2">
                            <span class="text-gray-300 font-medium">${week.week}</span>
                            <span class="px-2 py-1 rounded-full text-xs font-medium ${regimeClass}">${week.regime}</span>
                        </div>
                        <div class="text-gray-400 text-sm mb-2">${week.holdings}</div>
                        <div class="flex justify-between items-center">
                            <span class="text-xs text-gray-500">Weekly: <span class="${isPositive ? 'text-emerald-400' : 'text-red-400'}">${isPositive ? '+' : ''}${formatPercent(week.weekly_return)}</span></span>
                            <span class="text-xs text-gray-500">Cum: <span class="text-cyan-400">${(week.cumulative * 100 - 100).toFixed(1)}%</span></span>
                        </div>
                    `;
                    mobileContainer.appendChild(card);
                }
            });
        } else {
            tbody.innerHTML = `
                <tr>
                    <td colspan="5" class="py-8 text-center text-gray-500">No rotation history available</td>
                </tr>
            `;
            if (mobileContainer) {
                mobileContainer.innerHTML = `<div class="p-8 text-center text-gray-500">No rotation history available</div>`;
            }
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
        
        // Get form data (support both English and Chinese page field IDs)
        const expectedReturnEl = document.getElementById('expected-return') || document.getElementById('risk-tolerance');
        const emailEl = document.getElementById('inquiry-email') || document.getElementById('email');
        const messageElField = document.getElementById('inquiry-message-text');
        
        const formData = {
            country: document.getElementById('country').value,
            name: document.getElementById('name').value,
            experience: document.getElementById('experience').value,
            capital: document.getElementById('capital').value,
            expectedReturn: expectedReturnEl ? expectedReturnEl.value : '',
            email: emailEl ? emailEl.value : '',
            message: messageElField ? messageElField.value : '',
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
                    message: formData.message,
                    _subject: `New Investor Inquiry from ${formData.name}`,
                    _replyto: formData.email
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
    
    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        
        const email = document.getElementById('email-input').value;
        const submitBtn = form.querySelector('button[type="submit"]');
        const originalText = submitBtn ? submitBtn.textContent : 'Subscribe';
        
        // Disable submit button
        if (submitBtn) {
            submitBtn.disabled = true;
            submitBtn.textContent = 'Subscribing...';
        }
        
        try {
            // Send to Formspree (using a different form endpoint for early access)
            const response = await fetch('https://formspree.io/f/xgonyjwn', {
                method: 'POST',
                headers: { 
                    'Content-Type': 'application/json',
                    'Accept': 'application/json'
                },
                body: JSON.stringify({
                    email: email,
                    _subject: 'New Early Access Signup',
                    message: `Email: ${email}\nType: Early Access Subscription`,
                    _replyto: email
                })
            });
            
            if (!response.ok) {
                throw new Error('Form submission failed');
            }
            
            // Show success message
            messageEl.textContent = 'Thank you! We\'ll be in touch soon.';
            messageEl.className = 'mt-4 text-sm text-emerald-400';
            messageEl.classList.remove('hidden');
            
            // Clear input
            document.getElementById('email-input').value = '';
            
        } catch (error) {
            console.error('Error submitting early access form:', error);
            messageEl.textContent = 'Sorry, there was an error. Please try again.';
            messageEl.className = 'mt-4 text-sm text-red-400';
            messageEl.classList.remove('hidden');
        } finally {
            // Re-enable submit button
            if (submitBtn) {
                submitBtn.disabled = false;
                submitBtn.textContent = originalText;
            }
            
            // Hide message after 5 seconds
            setTimeout(() => {
                messageEl.classList.add('hidden');
            }, 5000);
        }
    });
}

// Initialize all forms and load data
document.addEventListener('DOMContentLoaded', () => {
    initInvestorForm();
    initEarlyAccessForm();
    
    // Load all data
    loadYearlyPerformance();
    loadEquityCurve();
    loadLatestSignals();
    loadSignalHistory();
    loadMetrics();
});

// Refresh data every 5 minutes
setInterval(() => {
    loadYearlyPerformance();
    loadEquityCurve();
    loadLatestSignals();
    loadSignalHistory();
    loadMetrics();
}, 5 * 60 * 1000);

// ============================================
// INTERACTIVE EFFECTS MODULE
// ============================================

// 1. Number Counter Animation
function animateCounter(element, target, duration = 2000, suffix = '') {
    const start = 0;
    const startTime = performance.now();
    
    function updateCounter(currentTime) {
        const elapsed = currentTime - startTime;
        const progress = Math.min(elapsed / duration, 1);
        
        // Easing function (ease-out)
        const easeOut = 1 - Math.pow(1 - progress, 3);
        const current = start + (target - start) * easeOut;
        
        if (suffix === '%') {
            element.textContent = current.toFixed(1) + suffix;
        } else if (suffix === 'x') {
            element.textContent = current.toFixed(2) + suffix;
        } else if (target < 1 && target > 0) {
            // For small numbers like Sharpe ratio (0.73), show 2 decimal places
            element.textContent = current.toFixed(2);
        } else if (target < 10 && target >= 1) {
            // For numbers between 1-10, show 1 decimal place
            element.textContent = current.toFixed(1);
        } else {
            element.textContent = Math.floor(current).toLocaleString();
        }
        
        if (progress < 1) {
            requestAnimationFrame(updateCounter);
        }
    }
    
    requestAnimationFrame(updateCounter);
}

// Initialize counter animations when elements come into view
function initCounterAnimations() {
    const counters = document.querySelectorAll('[data-counter]');
    
    const observer = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting && !entry.target.classList.contains('counted')) {
                entry.target.classList.add('counted');
                const target = parseFloat(entry.target.dataset.counter);
                const suffix = entry.target.dataset.suffix || '';
                animateCounter(entry.target, target, 2000, suffix);
            }
        });
    }, { threshold: 0.5 });
    
    counters.forEach(counter => observer.observe(counter));
}

// 2. Scroll Reveal Animation
function initScrollReveal() {
    const reveals = document.querySelectorAll('.reveal, .reveal-left, .reveal-right, .reveal-scale');
    
    const observer = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                entry.target.classList.add('active');
            }
        });
    }, { 
        threshold: 0.1,
        rootMargin: '0px 0px -50px 0px'
    });
    
    reveals.forEach(el => observer.observe(el));
}

// 3. Navigation Scroll Effect
function initNavScroll() {
    const nav = document.querySelector('nav');
    let lastScroll = 0;
    
    window.addEventListener('scroll', () => {
        const currentScroll = window.pageYOffset;
        
        if (currentScroll > 100) {
            nav.classList.add('nav-scrolled');
        } else {
            nav.classList.remove('nav-scrolled');
        }
        
        lastScroll = currentScroll;
    });
}

// 4. Magnetic Button Effect
function initMagneticButtons() {
    const buttons = document.querySelectorAll('.magnetic-btn');
    
    buttons.forEach(btn => {
        btn.addEventListener('mousemove', (e) => {
            const rect = btn.getBoundingClientRect();
            const x = e.clientX - rect.left - rect.width / 2;
            const y = e.clientY - rect.top - rect.height / 2;
            
            btn.style.transform = `translate(${x * 0.2}px, ${y * 0.2}px)`;
        });
        
        btn.addEventListener('mouseleave', () => {
            btn.style.transform = 'translate(0, 0)';
        });
    });
}

// 5. Spotlight Effect
function initSpotlight() {
    const spotlights = document.querySelectorAll('.spotlight');
    
    spotlights.forEach(el => {
        el.addEventListener('mousemove', (e) => {
            const rect = el.getBoundingClientRect();
            const x = e.clientX - rect.left;
            const y = e.clientY - rect.top;
            
            el.style.setProperty('--spotlight-x', `${x}px`);
            el.style.setProperty('--spotlight-y', `${y}px`);
            
            const before = el.querySelector('::before') || el;
            if (before.style) {
                before.style.left = `${x}px`;
                before.style.top = `${y}px`;
            }
        });
    });
}

// 6. Smooth Scroll for Anchor Links
function initSmoothScroll() {
    document.querySelectorAll('a[href^="#"]').forEach(anchor => {
        anchor.addEventListener('click', function(e) {
            e.preventDefault();
            const target = document.querySelector(this.getAttribute('href'));
            if (target) {
                target.scrollIntoView({
                    behavior: 'smooth',
                    block: 'start'
                });
            }
        });
    });
}

// 7. Active Navigation Highlight
function initActiveNav() {
    const sections = document.querySelectorAll('section[id]');
    const navLinks = document.querySelectorAll('nav a[href^="#"]');
    
    const observer = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                navLinks.forEach(link => {
                    link.classList.remove('nav-active');
                    if (link.getAttribute('href') === `#${entry.target.id}`) {
                        link.classList.add('nav-active');
                    }
                });
            }
        });
    }, { threshold: 0.3 });
    
    sections.forEach(section => observer.observe(section));
}

// Initialize all interactive effects
document.addEventListener('DOMContentLoaded', () => {
    initCounterAnimations();
    initScrollReveal();
    initNavScroll();
    initMagneticButtons();
    initSpotlight();
    initSmoothScroll();
    initActiveNav();
});
