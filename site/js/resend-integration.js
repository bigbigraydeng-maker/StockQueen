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

// Resend API Configuration
const RESEND_CONFIG = {
    // Your Resend API key - should be stored securely, not in client-side code
    // For production, use a backend proxy or serverless function
    API_KEY: 're_YOUR_API_KEY_HERE', // Replace with your actual API key
    
    // Email addresses
    FROM: {
        NEWSLETTER: 'newsletter@stockqueen.io',      // For newsletter emails
        CONTACT: 'contact@stockqueen.io',            // For contact form replies
        NOREPLY: 'noreply@stockqueen.io',            // For system notifications
        // Fallback for testing (Resend's default)
        DEFAULT: 'onboarding@resend.dev'
    },
    
    // Recipient addresses (your team emails)
    TO: {
        CONTACT: 'bigbigraydeng@gmail.com',          // Where contact forms are sent
        NEWSLETTER: 'bigbigraydeng@gmail.com',       // Newsletter admin
        SUPPORT: 'bigbigraydeng@gmail.com'           // Support inquiries
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
            <a href="https://stockqueen-site.onrender.com/weekly-report/" 
               style="display: inline-block; background: linear-gradient(135deg, #4f46e5 0%, #0891b2 100%); 
                      color: white; padding: 14px 32px; text-decoration: none; border-radius: 8px; 
                      font-weight: 600; font-size: 14px;">
                View Latest Report
            </a>
        </div>
        <hr style="border: none; border-top: 1px solid #e2e8f0; margin: 30px 0;">
        <p style="color: #94a3b8; font-size: 12px; text-align: center; margin: 0;">
            StockQueen Quantitative Research Team | Rayde Capital<br>
            <a href="https://stockqueen-site.onrender.com" style="color: #0891b2; text-decoration: none;">stockqueen.io</a>
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

View Latest Report: https://stockqueen-site.onrender.com/weekly-report/

StockQueen Quantitative Research Team | Rayde Capital
https://stockqueen-site.onrender.com
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
            <a href="https://stockqueen-site.onrender.com" style="color: #0891b2; text-decoration: none;">stockqueen.io</a>
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
https://stockqueen-site.onrender.com
        `
    })
};

// ==================== Email Service ====================

const EmailService = {
    /**
     * Send email via Resend API
     * Note: In production, this should be done via a backend proxy
     * to protect your API key
     */
    async sendEmail({ to, from, subject, html, text }) {
        try {
            const response = await fetch('https://api.resend.com/emails', {
                method: 'POST',
                headers: {
                    'Authorization': `Bearer ${RESEND_CONFIG.API_KEY}`,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    from: from || RESEND_CONFIG.FROM.DEFAULT,
                    to: Array.isArray(to) ? to : [to],
                    subject,
                    html,
                    text
                })
            });

            const data = await response.json();

            if (!response.ok) {
                throw new Error(data.message || 'Failed to send email');
            }

            return { success: true, id: data.id };
        } catch (error) {
            console.error('Email send failed:', error);
            return { success: false, error: error.message };
        }
    },

    /**
     * Handle contact form submission
     */
    async sendContactForm(formData) {
        const template = EmailTemplates.contactForm(formData);
        
        // Send notification to admin
        const adminResult = await this.sendEmail({
            to: RESEND_CONFIG.TO.CONTACT,
            from: RESEND_CONFIG.FROM.CONTACT,
            subject: template.subject,
            html: template.html,
            text: template.text
        });

        // Send confirmation to user
        const userResult = await this.sendEmail({
            to: formData.email,
            from: RESEND_CONFIG.FROM.CONTACT,
            subject: 'We received your inquiry - StockQueen',
            html: `
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Inquiry Received</title>
</head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px;">
    <div style="background: linear-gradient(135deg, #1e3a5f 0%, #0d2137 100%); padding: 30px; text-align: center; border-radius: 8px 8px 0 0;">
        <h1 style="color: #22d3ee; margin: 0; font-size: 24px;">StockQueen</h1>
    </div>
    <div style="background: #fff; padding: 30px; border: 1px solid #e2e8f0; border-top: none;">
        <h2 style="color: #0f172a; font-size: 18px; margin-bottom: 16px;">Thank You for Your Inquiry</h2>
        <p style="color: #374151; font-size: 14px; line-height: 1.8;">
            Hi ${formData.name},
        </p>
        <p style="color: #374151; font-size: 14px; line-height: 1.8;">
            We have received your inquiry and will get back to you within 24-48 hours.
        </p>
        <hr style="border: none; border-top: 1px solid #e2e8f0; margin: 30px 0;">
        <p style="color: #94a3b8; font-size: 12px; text-align: center; margin: 0;">
            StockQueen Quantitative Research Team
        </p>
    </div>
</body>
</html>
            `
        });

        return { adminResult, userResult };
    },

    /**
     * Handle newsletter subscription
     */
    async subscribeNewsletter(email) {
        const template = EmailTemplates.newsletterWelcome(email);
        
        return await this.sendEmail({
            to: email,
            from: RESEND_CONFIG.FROM.NEWSLETTER,
            subject: template.subject,
            html: template.html,
            text: template.text
        });
    },

    /**
     * Handle early access signup
     */
    async signupEarlyAccess(email) {
        const template = EmailTemplates.earlyAccessConfirmation(email);
        
        // Send confirmation to user
        const userResult = await this.sendEmail({
            to: email,
            from: RESEND_CONFIG.FROM.NOREPLY,
            subject: template.subject,
            html: template.html,
            text: template.text
        });

        // Notify admin
        const adminResult = await this.sendEmail({
            to: RESEND_CONFIG.TO.CONTACT,
            from: RESEND_CONFIG.FROM.NOREPLY,
            subject: 'New Early Access Signup',
            html: `<p>New early access signup: ${email}</p>`,
            text: `New early access signup: ${email}`
        });

        return { userResult, adminResult };
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
                email: document.getElementById('email').value,
                country: document.getElementById('country').value,
                experience: document.getElementById('experience').value,
                capital: document.getElementById('capital').value,
                riskTolerance: document.getElementById('risk-tolerance').value
            };
            
            // Show loading state
            const submitBtn = contactForm.querySelector('button[type="submit"]');
            const originalText = submitBtn.textContent;
            submitBtn.textContent = 'Sending...';
            submitBtn.disabled = true;
            
            try {
                // Note: In production, this should call your backend API
                // instead of directly using the Resend API key
                const result = await EmailService.sendContactForm(formData);
                
                if (result.adminResult.success) {
                    contactMessage.textContent = 'Thank you! We\'ll be in touch soon.';
                    contactMessage.className = 'mt-4 text-sm text-emerald-400';
                    contactForm.reset();
                } else {
                    throw new Error(result.adminResult.error);
                }
            } catch (error) {
                contactMessage.textContent = 'Something went wrong. Please try again later.';
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
    const earlyAccessForm = document.getElementById('early-access-form');
    const earlyAccessMessage = document.getElementById('form-message');
    
    if (earlyAccessForm) {
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
