/**
 * StockQueen Stripe Checkout Integration
 *
 * Usage in pricing/subscribe pages:
 *   <button data-plan="monthly" data-checkout>Subscribe $49/mo</button>
 *   <button data-plan="quarterly" data-checkout>Subscribe $129/quarter</button>
 *   <button data-plan="yearly" data-checkout>Subscribe $399/year</button>
 *   <script src="/js/checkout.js"></script>
 */

(function () {
    'use strict';

    // Stripe Publishable Key (safe to expose in frontend)
    const STRIPE_PK = 'pk_live_51TBuW02LGfwIkD1C8jheNKMMz09pAVkmrg1kPLIPna1oqdhWaSpI3tl8lyTbkNUGzdtNBKAxNrYYJcvQ50Nqevm700Tb9DIJpt';

    const API_BASE = (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1')
        ? 'http://localhost:8001'
        : 'https://stockqueen-api.onrender.com';

    const CHECKOUT_URL = `${API_BASE}/api/payments/create-checkout`;
    const PORTAL_URL = `${API_BASE}/api/payments/portal`;
    const STATUS_URL = `${API_BASE}/api/payments/status`;

    function detectLang() {
        const htmlLang = document.documentElement.lang;
        if (htmlLang && htmlLang.startsWith('zh')) return 'zh';
        if (window.location.pathname.includes('-zh')) return 'zh';
        return 'en';
    }

    function findEmailInput() {
        return document.querySelector('#checkout-email')
            || document.querySelector('#email-input')
            || document.querySelector('input[type="email"]');
    }

    async function handleCheckout(plan) {
        const emailInput = findEmailInput();
        if (!emailInput) {
            alert(detectLang() === 'zh' ? '请输入邮箱地址' : 'Please enter your email');
            return;
        }

        const email = emailInput.value.trim();
        if (!email || !email.includes('@')) {
            alert(detectLang() === 'zh' ? '请输入有效的邮箱地址' : 'Please enter a valid email');
            emailInput.focus();
            return;
        }

        const lang = detectLang();
        const btn = document.querySelector(`[data-plan="${plan}"][data-checkout]`);
        const originalText = btn ? btn.textContent : '';

        if (btn) {
            btn.disabled = true;
            btn.textContent = lang === 'zh' ? '跳转中...' : 'Redirecting...';
        }

        try {
            // Fire tracking events before redirect
            const valueMap = { monthly: 49, quarterly: 129, yearly: 399 };
            const value = valueMap[plan] || 49;
            if (typeof gtag === 'function') {
                gtag('event', 'begin_checkout', {
                    value, currency: 'USD',
                    items: [{ item_id: 'sq_premium_' + plan, item_name: 'StockQueen Premium ' + plan, price: value, quantity: 1 }]
                });
            }
            if (typeof fbq === 'function') {
                fbq('track', 'InitiateCheckout', {
                    value, currency: 'USD',
                    content_name: 'StockQueen Premium',
                    content_ids: ['sq_premium_' + plan],
                    num_items: 1
                });
            }

            const resp = await fetch(CHECKOUT_URL, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ plan, email, lang }),
            });

            const data = await resp.json();
            if (!resp.ok || !data.url) {
                throw new Error(data.error || 'Checkout failed');
            }

            // Redirect to Stripe Checkout
            window.location.href = data.url;

        } catch (error) {
            console.error('[SQ Checkout]', error);
            alert(lang === 'zh'
                ? `支付跳转失败: ${error.message}`
                : `Checkout failed: ${error.message}`);
            if (btn) {
                btn.disabled = false;
                btn.textContent = originalText;
            }
        }
    }

    async function handlePortal(email) {
        try {
            const resp = await fetch(PORTAL_URL, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ email }),
            });
            const data = await resp.json();
            if (data.url) {
                window.location.href = data.url;
            } else {
                alert(data.error || 'Could not open billing portal');
            }
        } catch (error) {
            console.error('[SQ Portal]', error);
        }
    }

    // Auto-bind checkout buttons
    function init() {
        document.querySelectorAll('[data-checkout]').forEach(btn => {
            if (btn.dataset.sqCheckoutInit) return;
            btn.dataset.sqCheckoutInit = 'true';

            btn.addEventListener('click', (e) => {
                e.preventDefault();
                const plan = btn.dataset.plan || 'monthly';
                handleCheckout(plan);
            });
        });

        // Bind portal buttons
        document.querySelectorAll('[data-billing-portal]').forEach(btn => {
            if (btn.dataset.sqPortalInit) return;
            btn.dataset.sqPortalInit = 'true';

            btn.addEventListener('click', (e) => {
                e.preventDefault();
                const email = btn.dataset.email || findEmailInput()?.value || '';
                if (email) {
                    handlePortal(email);
                }
            });
        });
    }

    // Expose global API
    window.StockQueenCheckout = { handleCheckout, handlePortal, STATUS_URL };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
