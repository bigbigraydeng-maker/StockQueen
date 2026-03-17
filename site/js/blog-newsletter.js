/**
 * Blog Newsletter Form Handler
 * Handles newsletter subscription forms on blog pages
 * Uses class="blog-newsletter-form" to support multiple forms per page
 */
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

            // Disable button during submission
            const originalText = submitBtn.textContent;
            submitBtn.disabled = true;
            submitBtn.textContent = isZh ? '提交中...' : 'Submitting...';

            try {
                // Log subscription (integrate with Resend/Supabase later)
                console.log('Blog newsletter signup:', email, 'lang:', isZh ? 'zh' : 'en');

                // Show success
                messageEl.textContent = isZh
                    ? '订阅成功！我们将每周发送市场洞察到您的邮箱。'
                    : 'Subscribed! Weekly market insights coming to your inbox.';
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
