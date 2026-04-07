/**
 * StockQueen Resend Email Integration
 * 
 * This module handles all email sending functionality using Resend API
 * - Contact form submissions
 * - Newsletter subscriptions
 * - Early access signups
 * 
 * Setup:
 * 1. Sign up at https://resend.com
 * 2. Create API key and add to environment variables
 * 3. Verify your domain or use onboarding@resend.dev for testing
 */

// ==================== Configuration ====================

// Backend API Configuration (no more client-side API keys!)
const API_CONFIG = {
    // Backend API base URL - auto-detect from current hostname
    get BASE_URL() {
        if (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1') {
            return 'http://localhost:8001';  // Local dev
        }
        return 'https://stockqueen-api.onrender.com';  // Production
    }
};

// Legacy config kept for backward compatibility (contact form still uses it)
const RESEND_CONFIG = {
    FROM: {
        NEWSLETTER: 'StockQueen Newsletter <newsletter@stockqueen.tech>',
        CONTACT: 'StockQueen Contact <newsletter@stockqueen.tech>',
        NOREPLY: 'StockQueen <newsletter@stockqueen.tech>',
        DEFAULT: 'StockQueen <newsletter@stockqueen.tech>'
    },
    TO: {
        CONTACT: 'bigbigraydeng@gmail.com',
        NEWSLETTER: 'bigbigraydeng@gmail.com',
        SUPPORT: 'bigbigraydeng@gmail.com'
    }
};

// ==================== Email Templates ====================

const EmailTemplates = {
    /**
     * Contact Form Submission Template
     */
    contactForm: (data) => ({
        subject: `New Contact Inquiry from ${data.name}`,
        html: `
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>New Contact Form Submission</title>
</head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px;">
    <div style="background: linear-gradient(135deg, #1e3a5f 0%, #0d2137 100%); padding: 30px; text-align: center; border-radius: 8px 8px 0 0;">
        <h1 style="color: #22d3ee; margin: 0; font-size: 24px;">StockQueen</h1>
        <p style="color: #94a3b8; margin: 8px 0 0 0; font-size: 14px;">New Contact Form Submission</p>
    </div>
    <div style="background: #fff; padding: 30px; border: 1px solid #e2e8f0; border-top: none;">
        <h2 style="color: #0f172a; font-size: 18px; margin-bottom: 16px;">Contact Details</h2>
        <table style="width: 100%; border-collapse: collapse;">
            <tr style="border-bottom: 1px solid #e2e8f0;">
                <td style="padding: 12px; font-weight: bold; width: 30%;">Name:</td>
                <td style="padding: 12px;">${data.name}</td>
            </tr>
            <tr style="border-bottom: 1px solid #e2e8f0;">
                <td style="padding: 12px; font-weight: bold;">Email:</td>
                <td style="padding: 12px;">${data.email}</td>
            </tr>
            <tr style="border-bottom: 1px solid #e2e8f0;">
                <td style="padding: 12px; font-weight: bold;">Country:</td>
                <td style="padding: 12px;">${data.country || 'Not provided'}</td>
            </tr>
            <tr style="border-bottom: 1px solid #e2e8f0;">
                <td style="padding: 12px; font-weight: bold;">Experience:</td>
                <td style="padding: 12px;">${data.experience || 'Not provided'}</td>
            </tr>
            <tr style="border-bottom: 1px solid #e2e8f0;">
                <td style="padding: 12px; font-weight: bold;">Capital:</td>
                <td style="padding: 12px;">${data.capital || 'Not provided'}</td>
            </tr>
            <tr>
                <td style="padding: 12px; font-weight: bold;">Risk Tolerance:</td>
                <td style="padding: 12px;">${data.riskTolerance || 'Not provided'}</td>
            </tr>
        </table>
        <hr style="border: none; border-top: 1px solid #e2e8f0; margin: 30px 0;">
        <p style="color: #94a3b8; font-size: 12px; text-align: center; margin: 0;">
            StockQueen Contact Form<br>
            Submitted on ${new Date().toLocaleString()}
        </p>
    </div>
</body>
</html>
        `,
        text: `
New Contact Form Submission

Name: ${data.name}
Email: ${data.email}
Country: ${data.country || 'Not provided'}
Experience: ${data.experience || 'Not provided'}
Capital: ${data.capital || 'Not provided'}
Risk Tolerance: ${data.riskTolerance || 'Not provided'}

Submitted on ${new Date().toLocaleString()}
        `
    }),

    /**
     * Newsletter Welcome Email Template
     */
    newsletterWelcome: (email) => ({
        subject: 'Welcome to StockQueen Newsletter!',
        html: `
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Welcome to StockQueen</title>
</head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px;">
    <div style="background: linear-gradient(135deg, #1e3a5f 0%, #0d2137 100%); padding: 30px; text-align: center; border-radius: 8px 8px 0 0;">
        <h1 style="color: #22d3ee; margin: 0; font-size: 28px;">StockQueen</h1>
        <p style="color: #94a3b8; margin: 8px 0 0 0; font-size: 14px;">Welcome to Our Newsletter</p>
    </div>
    <div style="background: #fff; padding: 30px; border: 1px solid #e2e8f0; border-top: none;">
        <h2 style="color: #0f172a; font-size: 20px; margin-bottom: 16px;">Welcome Aboard! 🎉</h2>
        <p style="color: #374151; font-size: 14px; line-height: 1.8; margin-bottom: 16px;">
            Thank you for subscribing to the StockQueen newsletter. You'll receive our weekly quantitative strategy reports, market insights, and exclusive research directly in your inbox.
        </p>
        <div style="background: #f0fdf4; border-radius: 8px; padding: 16px; margin: 24px 0;">
            <p style="color: #166534; font-size: 14px; margin: 0;">
                <strong>What to expect:</strong><br>
                • Weekly strategy performance reports<br>
                • Market regime analysis<br>
                • AI-powered insights<br>
                • Exclusive research access
            </p>
        </div>
        <div style="text-align: center; margin: 30px 0;">
            <a href="https://stockqueen.tech/weekly-report/" 
               style="display: inline-block; background: linear-gradient(135deg, #4f46e5 0%, #0891b2 100%); 
                      color: white; padding: 14px 32px; text-decoration: none; border-radius: 8px; 
                      font-weight: 600; font-size: 14px;">
                View Latest Report
            </a>
        </div>
        <hr style="border: none; border-top: 1px solid #e2e8f0; margin: 30px 0;">
        <p style="color: #94a3b8; font-size: 12px; text-align: center; margin: 0;">
            StockQueen Quantitative Research Team | Rayde Capital<br>
            <a href="https://stockqueen.tech" style="color: #0891b2; text-decoration: none;">stockqueen.tech</a>
        </p>
    </div>
</body>
</html>
        `,
        text: `
Welcome to StockQueen Newsletter!

Thank you for subscribing. You'll receive our weekly quantitative strategy reports, market insights, and exclusive research directly in your inbox.

What to expect:
- Weekly strategy performance reports
- Market regime analysis
- AI-powered insights
- Exclusive research access

View Latest Report: https://stockqueen.tech/weekly-report/

StockQueen Quantitative Research Team | Rayde Capital
https://stockqueen.tech
        `
    }),

    /**
     * Early Access Confirmation Template
     */
    earlyAccessConfirmation: (email) => ({
        subject: 'You\'re on the StockQueen Early Access List!',
        html: `
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Early Access Confirmed</title>
</head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px;">
    <div style="background: linear-gradient(135deg, #1e3a5f 0%, #0d2137 100%); padding: 30px; text-align: center; border-radius: 8px 8px 0 0;">
        <h1 style="color: #22d3ee; margin: 0; font-size: 28px;">StockQueen</h1>
        <p style="color: #94a3b8; margin: 8px 0 0 0; font-size: 14px;">Early Access List</p>
    </div>
    <div style="background: #fff; padding: 30px; border: 1px solid #e2e8f0; border-top: none;">
        <h2 style="color: #0f172a; font-size: 20px; margin-bottom: 16px;">You\'re In! 🚀</h2>
        <p style="color: #374151; font-size: 14px; line-height: 1.8; margin-bottom: 16px;">
            Thank you for joining our early access list. You\'ll be among the first to know when we launch new features and products.
        </p>
        <div style="background: #eff6ff; border-radius: 8px; padding: 16px; margin: 24px 0;">
            <p style="color: #1e40af; font-size: 14px; margin: 0;">
                <strong>What\'s next?</strong><br>
                We\'ll notify you as soon as early access becomes available. In the meantime, follow us on social media for updates.
            </p>
        </div>
        <hr style="border: none; border-top: 1px solid #e2e8f0; margin: 30px 0;">
        <p style="color: #94a3b8; font-size: 12px; text-align: center; margin: 0;">
            StockQueen Quantitative Research Team | Rayde Capital<br>
            <a href="https://stockqueen.tech" style="color: #0891b2; text-decoration: none;">stockqueen.tech</a>
        </p>
    </div>
</body>
</html>
        `,
        text: `
You're on the StockQueen Early Access List!

Thank you for joining our early access list. You'll be among the first to know when we launch new features and products.

What's next?
We'll notify you as soon as early access becomes available. In the meantime, follow us on social media for updates.

StockQueen Quantitative Research Team | Rayde Capital
https://stockqueen.tech
        `
    })
};

// ==================== Email Service ====================

const EmailService = {
    /**
     * Send email via backend API proxy
     * Contact form submissions go through the backend to avoid exposing API keys
     */
    async sendEmail({ to, from, subject, html, text }) {
        try {
            // Contact form: use backend proxy endpoint
            const response = await fetch(`${API_CONFIG.BASE_URL}/api/contact`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ to, from, subject, html, text })
            });

            const data = await response.json();

            if (!response.ok) {
                throw new Error(data.message || data.error || 'Failed to send email');
            }

            return { success: true, id: data.id || 'sent' };
        } catch (error) {
            console.error('Email send failed:', error);
            return { success: false, error: error.message };
        }
    },

    /**
     * Handle contact form submission — via backend /api/contact
     */
    async sendContactForm(formData) {
        try {
            const response = await fetch(`${API_CONFIG.BASE_URL}/api/contact`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(formData)
            });

            const data = await response.json();

            if (!response.ok || !data.success) {
                throw new Error(data.error || 'Failed to submit inquiry');
            }

            return { adminResult: { success: true }, userResult: { success: true } };
        } catch (error) {
            console.error('Contact form error:', error);
            return { adminResult: { success: false, error: error.message }, userResult: { success: false } };
        }
    },

    /**
     * Handle newsletter subscription - via backend API (no client-side API key)
     */
    async subscribeNewsletter(email, lang) {
        try {
            // Auto-detect language if not provided
            if (!lang) {
                const userLang = navigator.language || navigator.userLanguage || '';
                lang = userLang.startsWith('zh') ? 'zh' : 'en';
            }

            const response = await fetch(`${API_CONFIG.BASE_URL}/api/newsletter/subscribe`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ email, lang })
            });

            const data = await response.json();

            if (!response.ok || !data.success) {
                throw new Error(data.error || 'Subscription failed');
            }

            return { success: true, id: data.message };
        } catch (error) {
            console.error('Newsletter subscribe failed:', error);
            return { success: false, error: error.message };
        }
    },

    /**
     * Handle early access signup - reuses newsletter subscribe backend
     */
    async signupEarlyAccess(email) {
        // Early access signup is now the same as newsletter subscription
        const result = await this.subscribeNewsletter(email);
        return { userResult: result, adminResult: { success: true } };
    }
};

// ==================== Form Handlers ====================

// Contact Form Handler
document.addEventListener('DOMContentLoaded', () => {
    const contactForm = document.getElementById('investor-form');
    const contactMessage = document.getElementById('inquiry-message');
    
    if (contactForm) {
        contactForm.addEventListener('submit', async (e) => {
            e.preventDefault();

            const formData = {
                name: document.getElementById('name').value,
                email: document.getElementById('inquiry-email').value,
                country: document.getElementById('country').value,
                experience: document.getElementById('experience').value,
                capital: document.getElementById('capital').value,
                expectedReturn: (document.getElementById('expected-return') || {}).value || '',
                message: (document.getElementById('inquiry-message-text') || {}).value || ''
            };
            
            // Show loading state
            const submitBtn = contactForm.querySelector('button[type="submit"]');
            const originalText = submitBtn.textContent;
            submitBtn.textContent = '提交中...';
            submitBtn.disabled = true;

            try {
                const result = await EmailService.sendContactForm(formData);

                if (result.adminResult.success) {
                    contactMessage.textContent = '感谢您的咨询！我们将在24-48小时内与您联系。';
                    contactMessage.className = 'mt-4 text-sm text-emerald-400';
                    contactForm.reset();
                } else {
                    throw new Error(result.adminResult.error);
                }
            } catch (error) {
                contactMessage.textContent = '提交失败，请稍后重试或直接发送邮件联系我们。';
                contactMessage.className = 'mt-4 text-sm text-red-400';
                console.error('Contact form error:', error);
            } finally {
                submitBtn.textContent = originalText;
                submitBtn.disabled = false;
                contactMessage.classList.remove('hidden');
                
                setTimeout(() => {
                    contactMessage.classList.add('hidden');
                }, 5000);
            }
        });
    }
    
    // Early Access Form Handler
    // Skip if app.js already handles this form (avoid duplicate handlers)
    const earlyAccessForm = document.getElementById('early-access-form');
    const earlyAccessMessage = document.getElementById('form-message');

    if (earlyAccessForm && !earlyAccessForm.dataset.sqSubscribeInit) {
        earlyAccessForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            
            const email = document.getElementById('email-input').value;
            
            // Show loading state
            const submitBtn = earlyAccessForm.querySelector('button[type="submit"]');
            const originalText = submitBtn.textContent;
            submitBtn.textContent = 'Subscribing...';
            submitBtn.disabled = true;
            
            try {
                const result = await EmailService.signupEarlyAccess(email);
                
                if (result.userResult.success) {
                    earlyAccessMessage.textContent = 'Welcome aboard! Check your email for confirmation.';
                    earlyAccessMessage.className = 'mt-4 text-sm text-emerald-400';
                    earlyAccessForm.reset();
                } else {
                    throw new Error(result.userResult.error);
                }
            } catch (error) {
                earlyAccessMessage.textContent = 'Something went wrong. Please try again later.';
                earlyAccessMessage.className = 'mt-4 text-sm text-red-400';
                console.error('Early access error:', error);
            } finally {
                submitBtn.textContent = originalText;
                submitBtn.disabled = false;
                earlyAccessMessage.classList.remove('hidden');
                
                setTimeout(() => {
                    earlyAccessMessage.classList.add('hidden');
                }, 5000);
            }
        });
    }
});

// Export for use in other scripts
window.EmailService = EmailService;
window.EmailTemplates = EmailTemplates;
window.RESEND_CONFIG = RESEND_CONFIG;
