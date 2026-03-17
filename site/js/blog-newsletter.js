/**
 * Blog Newsletter Form Handler
 * Handles newsletter subscription forms on blog pages
 * Uses class="blog-newsletter-form" to support multiple forms per page
 * Calls backend API: POST /api/newsletter/subscribe
 */

const BLOG_SUBSCRIBE_API = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1'
    ? 'http://localhost:8001'
    : 'https://stockqueen-api.onrender.com';

document.addEventListener('DOMContentLoaded', () => {
    const forms = document.querySelectorAll('.blog-newsletter-form');

    forms.forEach(form => {
        form.addEventListener('submit', async (e) => {
            e.preventDefault();

            const emailInput = form.querySelector('input[type="email"]');
            const messageEl = form.querySelector('.blog-form-message');
            const submitBtn = form.querySelector('button[type="submit"]');
            const email = emailInput.value.trim();

            if (!email) return;

            // Detect language from page
            const isZh = document.documentElement.lang === 'zh' ||
                         window.location.pathname.includes('-zh');
            const lang = isZh ? 'zh' : 'en';

            // Disable button during submission
            const originalText = submitBtn.textContent;
            submitBtn.disabled = true;
            submitBtn.textContent = isZh ? '提交中...' : 'Submitting...';

            try {
                const response = await fetch(`${BLOG_SUBSCRIBE_API}/api/newsletter/subscribe`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ email, lang })
                });

                const data = await response.json();

                if (!response.ok || !data.success) {
                    throw new Error(data.error || 'Subscription failed');
                }

                // Show success
                messageEl.textContent = isZh
                    ? '订阅成功！请查收欢迎邮件 🎉'
                    : 'Subscribed! Check your inbox for a welcome email 🎉';
                messageEl.className = 'blog-form-message mt-2 text-xs text-emerald-400';
                emailInput.value = '';

                // Hide message after 8 seconds
                setTimeout(() => {
                    messageEl.className = 'blog-form-message mt-2 text-xs hidden';
                }, 8000);
            } catch (error) {
                console.error('Newsletter signup error:', error);
                messageEl.textContent = isZh
                    ? '订阅失败，请稍后重试。'
                    : 'Failed to subscribe. Please try again.';
                messageEl.className = 'blog-form-message mt-2 text-xs text-red-400';
            } finally {
                submitBtn.disabled = false;
                submitBtn.textContent = originalText;
            }
        });
    });
});
