/**
 * StockQueen Email Marketing Automation
 * Automated email sequences for user onboarding and retention
 */

const EmailAutomation = {
    // Email sequences configuration
    sequences: {
        // Welcome sequence for new subscribers
        welcome: {
            name: 'Welcome Series',
            emails: [
                {
                    delay: 0, // Immediately
                    subject: 'Welcome to StockQueen! 🎉',
                    template: 'welcome'
                },
                {
                    delay: 24 * 60 * 60 * 1000, // 1 day
                    subject: 'How Our AI Strategy Works',
                    template: 'strategy_explainer'
                },
                {
                    delay: 3 * 24 * 60 * 60 * 1000, // 3 days
                    subject: 'Your First Week: What to Expect',
                    template: 'first_week'
                },
                {
                    delay: 6 * 24 * 60 * 60 * 1000, // 6 days (before trial ends)
                    subject: 'Your Trial Ends Tomorrow - Special Offer Inside',
                    template: 'trial_ending'
                }
            ]
        },
        
        // Trial ending sequence
        trialEnding: {
            name: 'Trial Ending',
            emails: [
                {
                    delay: 0,
                    subject: '⏰ Your Free Trial Ends in 24 Hours',
                    template: 'trial_ending_urgent'
                },
                {
                    delay: 12 * 60 * 60 * 1000, // 12 hours
                    subject: 'Last Chance: Keep Your Access',
                    template: 'trial_ending_final'
                }
            ]
        },
        
        // Reactivation sequence for cancelled users
        reactivation: {
            name: 'Reactivation',
            emails: [
                {
                    delay: 3 * 24 * 60 * 60 * 1000, // 3 days after cancel
                    subject: 'We Miss You! Come Back for 50% Off',
                    template: 'winback_50off'
                },
                {
                    delay: 14 * 24 * 60 * 60 * 1000, // 2 weeks
                    subject: 'New Features Added - See What You\'re Missing',
                    template: 'winback_features'
                }
            ]
        },
        
        // Weekly newsletter for free users
        weeklyNewsletter: {
            name: 'Weekly Newsletter',
            schedule: 'weekly', // Every Monday
            subject: 'StockQueen Weekly: Market Regime Update',
            template: 'weekly_report'
        }
    },

    // Email templates
    templates: {
        welcome: (user) => `
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Welcome to StockQueen</title>
</head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px;">
    <div style="background: linear-gradient(135deg, #1e3a5f 0%, #0d2137 100%); padding: 30px; text-align: center; border-radius: 8px 8px 0 0;">
        <h1 style="color: #22d3ee; margin: 0; font-size: 28px;">StockQueen</h1>
        <p style="color: #94a3b8; margin: 8px 0 0 0; font-size: 14px;">Welcome to the Community!</p>
    </div>
    <div style="background: #fff; padding: 30px; border: 1px solid #e2e8f0; border-top: none;">
        <h2 style="color: #0f172a; font-size: 20px; margin-bottom: 16px;">Hi ${user.name || 'there'},</h2>
        <p style="color: #374151; font-size: 14px; line-height: 1.8; margin-bottom: 16px;">
            Welcome to StockQueen! You're now part of a community of 500+ quantitative investors using AI-powered signals to navigate the markets.
        </p>
        <div style="background: #f0fdf4; border-radius: 8px; padding: 16px; margin: 24px 0;">
            <p style="color: #166534; font-size: 14px; margin: 0;">
                <strong>Your 7-day free trial is active!</strong><br>
                You have full access to all Pro features until ${user.trialEndDate}.
            </p>
        </div>
        <h3 style="color: #0f172a; font-size: 16px; margin-bottom: 12px;">Quick Start:</h3>
        <ol style="color: #374151; font-size: 14px; line-height: 1.8; padding-left: 20px;">
            <li>Access your <a href="https://stockqueen.tech/member-dashboard.html" style="color: #0891b2;">Member Dashboard</a></li>
            <li>Read this week's <a href="https://stockqueen.tech/weekly-report/" style="color: #0891b2;">Quant Report</a></li>
            <li>Join our <a href="#" style="color: #0891b2;">Discord Community</a></li>
        </ol>
        <div style="text-align: center; margin: 30px 0;">
            <a href="https://stockqueen.tech/member-dashboard.html" 
               style="display: inline-block; background: linear-gradient(135deg, #4f46e5 0%, #0891b2 100%); 
                      color: white; padding: 14px 32px; text-decoration: none; border-radius: 8px; 
                      font-weight: 600; font-size: 14px;">
                Access Dashboard
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
        
        trial_ending: (user) => `
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Your Trial Ends Tomorrow</title>
</head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px;">
    <div style="background: linear-gradient(135deg, #1e3a5f 0%, #0d2137 100%); padding: 30px; text-align: center; border-radius: 8px 8px 0 0;">
        <h1 style="color: #22d3ee; margin: 0; font-size: 28px;">StockQueen</h1>
    </div>
    <div style="background: #fff; padding: 30px; border: 1px solid #e2e8f0; border-top: none;">
        <h2 style="color: #0f172a; font-size: 20px; margin-bottom: 16px;">⏰ Your Free Trial Ends Tomorrow</h2>
        <p style="color: #374151; font-size: 14px; line-height: 1.8; margin-bottom: 16px;">
            Hi ${user.name || 'there'}, your 7-day free trial ends tomorrow. Don't lose access to our AI-powered trading signals!
        </p>
        <div style="background: #fef3c7; border-radius: 8px; padding: 16px; margin: 24px 0;">
            <p style="color: #92400e; font-size: 14px; margin: 0;">
                <strong>What you'll lose:</strong><br>
                • Real-time trading signals<br>
                • Weekly quant reports<br>
                • Portfolio tracking tools<br>
                • Member community access
            </p>
        </div>
        <div style="text-align: center; margin: 30px 0;">
            <a href="https://stockqueen.tech/pricing.html" 
               style="display: inline-block; background: linear-gradient(135deg, #4f46e5 0%, #0891b2 100%); 
                      color: white; padding: 14px 32px; text-decoration: none; border-radius: 8px; 
                      font-weight: 600; font-size: 14px;">
                Continue with Pro - $49/month
            </a>
        </div>
        <p style="color: #6b7280; font-size: 12px; text-align: center;">
            No commitment. Cancel anytime.
        </p>
    </div>
</body>
</html>
        `,
        
        winback_50off: (user) => `
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>We Miss You - 50% Off</title>
</head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px;">
    <div style="background: linear-gradient(135deg, #1e3a5f 0%, #0d2137 100%); padding: 30px; text-align: center; border-radius: 8px 8px 0 0;">
        <h1 style="color: #22d3ee; margin: 0; font-size: 28px;">StockQueen</h1>
    </div>
    <div style="background: #fff; padding: 30px; border: 1px solid #e2e8f0; border-top: none;">
        <h2 style="color: #0f172a; font-size: 20px; margin-bottom: 16px;">We Miss You! 💙</h2>
        <p style="color: #374151; font-size: 14px; line-height: 1.8; margin-bottom: 16px;">
            Hi ${user.name || 'there'}, we noticed you cancelled your subscription. We'd love to have you back!
        </p>
        <div style="background: #f0fdf4; border-radius: 8px; padding: 20px; margin: 24px 0; text-align: center;">
            <p style="color: #166534; font-size: 24px; font-weight: bold; margin: 0 0 8px 0;">50% OFF</p>
            <p style="color: #166534; font-size: 14px; margin: 0;">Your first 3 months - just $24.50/month</p>
            <p style="color: #6b7280; font-size: 12px; margin-top: 8px;">Use code: COMEBACK50</p>
        </div>
        <div style="text-align: center; margin: 30px 0;">
            <a href="https://stockqueen.tech/pricing.html?coupon=COMEBACK50" 
               style="display: inline-block; background: linear-gradient(135deg, #4f46e5 0%, #0891b2 100%); 
                      color: white; padding: 14px 32px; text-decoration: none; border-radius: 8px; 
                      font-weight: 600; font-size: 14px;">
                Reactivate My Account
            </a>
        </div>
        <p style="color: #6b7280; font-size: 12px; text-align: center;">
            Offer expires in 7 days.
        </p>
    </div>
</body>
</html>
        `
    },

    // Schedule an email
    scheduleEmail(user, sequenceName, emailIndex = 0) {
        const sequence = this.sequences[sequenceName];
        if (!sequence || !sequence.emails[emailIndex]) return;
        
        const email = sequence.emails[emailIndex];
        const template = this.templates[email.template];
        
        if (!template) return;
        
        // Calculate send time
        const sendAt = new Date(Date.now() + email.delay);
        
        // Store in localStorage (in production, use backend database)
        const scheduledEmails = JSON.parse(localStorage.getItem('scheduledEmails') || '[]');
        scheduledEmails.push({
            userId: user.id,
            email: user.email,
            subject: email.subject,
            html: template(user),
            sendAt: sendAt.toISOString(),
            sent: false
        });
        localStorage.setItem('scheduledEmails', JSON.stringify(scheduledEmails));
        
        console.log(`Scheduled "${email.subject}" for ${user.email} at ${sendAt}`);
    },

    // Trigger welcome sequence
    triggerWelcomeSequence(user) {
        console.log('Starting welcome sequence for', user.email);
        this.scheduleEmail(user, 'welcome', 0);
        this.scheduleEmail(user, 'welcome', 1);
        this.scheduleEmail(user, 'welcome', 2);
        this.scheduleEmail(user, 'welcome', 3);
    },

    // Trigger trial ending sequence
    triggerTrialEnding(user) {
        console.log('Starting trial ending sequence for', user.email);
        this.scheduleEmail(user, 'trialEnding', 0);
        this.scheduleEmail(user, 'trialEnding', 1);
    },

    // Trigger reactivation sequence
    triggerReactivation(user) {
        console.log('Starting reactivation sequence for', user.email);
        this.scheduleEmail(user, 'reactivation', 0);
        this.scheduleEmail(user, 'reactivation', 1);
    },

    // Process scheduled emails (call this periodically)
    processScheduledEmails() {
        const scheduledEmails = JSON.parse(localStorage.getItem('scheduledEmails') || '[]');
        const now = new Date();
        
        scheduledEmails.forEach((email, index) => {
            if (!email.sent && new Date(email.sendAt) <= now) {
                this.sendEmail(email);
                scheduledEmails[index].sent = true;
            }
        });
        
        localStorage.setItem('scheduledEmails', JSON.stringify(scheduledEmails));
    },

    // Send email via Resend API
    async sendEmail(emailData) {
        try {
            const response = await fetch('https://api.resend.com/emails', {
                method: 'POST',
                headers: {
                    'Authorization': `Bearer ${RESEND_CONFIG.API_KEY}`,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    from: 'StockQueen <onboarding@resend.dev>',
                    to: emailData.email,
                    subject: emailData.subject,
                    html: emailData.html
                })
            });
            
            if (response.ok) {
                console.log('Email sent successfully:', emailData.subject);
            } else {
                console.error('Failed to send email:', await response.text());
            }
        } catch (error) {
            console.error('Error sending email:', error);
        }
    }
};

// Auto-process emails every minute
setInterval(() => {
    EmailAutomation.processScheduledEmails();
}, 60000);

// Export for use in other scripts
window.EmailAutomation = EmailAutomation;
