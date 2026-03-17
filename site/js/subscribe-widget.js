/**
 * StockQueen Universal Subscribe Widget
 *
 * Drop this script into ANY page, it will auto-detect and connect ALL
 * newsletter subscription forms to the backend API.
 *
 * Supported form selectors (auto-detected):
 *   - #newsletter-form
 *   - #early-access-form
 *   - #hero-form
 *   - #bottom-form
 *   - #blog-subscribe-form
 *   - .blog-newsletter-form
 *   - [data-subscribe-form]        ← recommended for new pages
 *
 * Usage in new blog/report pages:
 *   <form data-subscribe-form>
 *     <input type="email" placeholder="your@email.com" required>
 *     <button type="submit">Subscribe</button>
 *   </form>
 *   <div data-subscribe-message></div>
 *   <script src="/js/subscribe-widget.js"></script>
 *
 * The widget auto-detects language from:
 *   1. <html lang="zh"> attribute
 *   2. URL containing "-zh"
 *   3. Radio input[name="newsletter-lang"] or input[name="language"]
 *   4. Falls back to "en"
 */

(function () {
    'use strict';

    const API_BASE = (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1')
        ? 'http://localhost:8001'
        : 'https://stockqueen-api.onrender.com';

    const SUBSCRIBE_URL = `${API_BASE}/api/newsletter/subscribe`;

    // All known form selectors
    const FORM_SELECTORS = [
        '#newsletter-form',
        '#early-access-form',
        '#hero-form',
        '#bottom-form',
        '#blog-subscribe-form',
        '.blog-newsletter-form',
        '[data-subscribe-form]'
    ].join(',');

    function detectLang(form) {
        // 1. Check radio buttons in the form
        const radio = form.querySelector('input[name="newsletter-lang"]:checked, input[name="language"]:checked');
        if (radio) return radio.value === 'zh' ? 'zh' : 'en';

        // 2. Check <html lang>
        const htmlLang = document.documentElement.lang;
        if (htmlLang && htmlLang.startsWith('zh')) return 'zh';

        // 3. Check URL
        if (window.location.pathname.includes('-zh')) return 'zh';

        return 'en';
    }

    function findEmailInput(form) {
        return form.querySelector('input[type="email"]')
            || form.querySelector('#email-input')
            || form.querySelector('#newsletter-email')
            || form.querySelector('#email')
            || form.querySelector('#hero-email')
            || form.querySelector('#bottom-email')
            || form.querySelector('input[placeholder*="email" i]');
    }

    function findMessageEl(form) {
        // Look for message element: data-subscribe-message, sibling, or known IDs
        return form.closest('div,section')?.querySelector('[data-subscribe-message]')
            || form.parentElement?.querySelector('.blog-form-message')
            || document.getElementById('form-message')
            || document.getElementById('newsletter-message')
            || document.getElementById('subscribe-message')
            || form.closest('div,section')?.querySelector('[id*="message"]');
    }

    function initForm(form) {
        // Skip if already initialized
        if (form.dataset.sqSubscribeInit) return;
        form.dataset.sqSubscribeInit = 'true';

        form.addEventListener('submit', async (e) => {
            e.preventDefault();

            const emailInput = findEmailInput(form);
            const messageEl = findMessageEl(form);
            const submitBtn = form.querySelector('button[type="submit"]');
            if (!emailInput || !submitBtn) return;

            const email = emailInput.value.trim();
            if (!email) return;

            const lang = detectLang(form);
            const isZh = lang === 'zh';
            const originalText = submitBtn.textContent;

            submitBtn.disabled = true;
            submitBtn.textContent = isZh ? '提交中...' : 'Subscribing...';

            try {
                const resp = await fetch(SUBSCRIBE_URL, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ email, lang })
                });
                const data = await resp.json();

                if (!resp.ok || !data.success) {
                    throw new Error(data.error || 'Subscription failed');
                }

                // Success
                if (messageEl) {
                    messageEl.textContent = isZh
                        ? '订阅成功！请查收欢迎邮件 🎉'
                        : 'Subscribed! Check your inbox for a welcome email 🎉';
                    messageEl.style.color = '#34d399';
                    messageEl.style.background = 'rgba(52, 211, 153, 0.1)';
                    messageEl.style.display = 'block';
                    messageEl.classList.remove('hidden');
                    if (messageEl.classList.contains('blog-form-message')) {
                        messageEl.className = 'blog-form-message mt-2 text-xs text-emerald-400';
                    }
                }
                emailInput.value = '';
                form.reset();
            } catch (error) {
                console.error('[SQ Subscribe]', error);
                if (messageEl) {
                    messageEl.textContent = isZh
                        ? '订阅失败，请稍后重试。'
                        : 'Subscription failed. Please try again.';
                    messageEl.style.color = '#f87171';
                    messageEl.style.background = 'rgba(248, 113, 113, 0.1)';
                    messageEl.style.display = 'block';
                    messageEl.classList.remove('hidden');
                    if (messageEl.classList.contains('blog-form-message')) {
                        messageEl.className = 'blog-form-message mt-2 text-xs text-red-400';
                    }
                }
            } finally {
                submitBtn.disabled = false;
                submitBtn.textContent = originalText;
                if (messageEl) {
                    setTimeout(() => {
                        messageEl.style.display = 'none';
                        messageEl.classList.add('hidden');
                    }, 5000);
                }
            }
        });
    }

    // Initialize on DOM ready
    function init() {
        const forms = document.querySelectorAll(FORM_SELECTORS);
        forms.forEach(initForm);

        // Also watch for dynamically added forms (SPA support)
        if (typeof MutationObserver !== 'undefined') {
            new MutationObserver(() => {
                document.querySelectorAll(FORM_SELECTORS).forEach(initForm);
            }).observe(document.body, { childList: true, subtree: true });
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
