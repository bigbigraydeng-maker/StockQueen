/**
 * StockQueen Stripe Checkout Integration
 * Handles Pro membership subscription ($49/month with 7-day trial)
 */

// Stripe configuration - Replace with your publishable key
const STRIPE_CONFIG = {
    PUBLISHABLE_KEY: 'pk_test_YOUR_STRIPE_PUBLISHABLE_KEY', // Replace with actual key
    PRICE_ID: 'price_YOUR_PRICE_ID', // Replace with actual price ID
    API_ENDPOINT: '/api/create-checkout-session',
    SUCCESS_URL: 'https://stockqueen.tech/success.html',
    CANCEL_URL: 'https://stockqueen.tech/pricing.html'
};

// Initialize Stripe
let stripe = null;

document.addEventListener('DOMContentLoaded', () => {
    // Load Stripe.js
    loadStripeJS().then(() => {
        stripe = Stripe(STRIPE_CONFIG.PUBLISHABLE_KEY);
        initializeCheckoutButtons();
    });
});

/**
 * Load Stripe.js dynamically
 */
function loadStripeJS() {
    return new Promise((resolve, reject) => {
        if (window.Stripe) {
            resolve();
            return;
        }
        
        const script = document.createElement('script');
        script.src = 'https://js.stripe.com/v3/';
        script.onload = resolve;
        script.onerror = reject;
        document.head.appendChild(script);
    });
}

/**
 * Initialize checkout buttons
 */
function initializeCheckoutButtons() {
    // Pro plan checkout button
    const proButton = document.getElementById('checkout-button-pro');
    if (proButton) {
        proButton.addEventListener('click', (e) => {
            e.preventDefault();
            startCheckout('pro');
        });
    }
    
    // Alternative button IDs
    const altButtons = [
        'checkout-button',
        'stripe-checkout',
        'subscribe-pro'
    ];
    
    altButtons.forEach(id => {
        const btn = document.getElementById(id);
        if (btn) {
            btn.addEventListener('click', (e) => {
                e.preventDefault();
                startCheckout('pro');
            });
        }
    });
}

/**
 * Start Stripe Checkout session
 */
async function startCheckout(plan) {
    const button = document.getElementById('checkout-button-pro') || 
                   document.getElementById('checkout-button') ||
                   event.target;
    
    // Show loading state
    const originalText = button.textContent;
    button.textContent = 'Loading...';
    button.disabled = true;
    
    try {
        // Call backend to create checkout session
        const response = await fetch(STRIPE_CONFIG.API_ENDPOINT, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                priceId: STRIPE_CONFIG.PRICE_ID,
                plan: plan,
                successUrl: STRIPE_CONFIG.SUCCESS_URL,
                cancelUrl: STRIPE_CONFIG.CANCEL_URL
            })
        });
        
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.message || 'Failed to create checkout session');
        }
        
        const session = await response.json();
        
        // Redirect to Stripe Checkout
        const result = await stripe.redirectToCheckout({
            sessionId: session.id
        });
        
        if (result.error) {
            throw new Error(result.error.message);
        }
        
    } catch (error) {
        console.error('Checkout error:', error);
        showError('Unable to start checkout. Please try again or contact support.');
        
        // Reset button
        button.textContent = originalText;
        button.disabled = false;
    }
}

/**
 * Show error message
 */
function showError(message) {
    // Create error toast
    const toast = document.createElement('div');
    toast.style.cssText = `
        position: fixed;
        top: 20px;
        right: 20px;
        background: #ef4444;
        color: white;
        padding: 16px 24px;
        border-radius: 8px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.3);
        z-index: 9999;
        max-width: 400px;
        font-family: system-ui, sans-serif;
    `;
    toast.textContent = message;
    document.body.appendChild(toast);
    
    // Remove after 5 seconds
    setTimeout(() => {
        toast.remove();
    }, 5000);
}

/**
 * Show success message
 */
function showSuccess(message) {
    const toast = document.createElement('div');
    toast.style.cssText = `
        position: fixed;
        top: 20px;
        right: 20px;
        background: #10b981;
        color: white;
        padding: 16px 24px;
        border-radius: 8px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.3);
        z-index: 9999;
        max-width: 400px;
        font-family: system-ui, sans-serif;
    `;
    toast.textContent = message;
    document.body.appendChild(toast);
    
    setTimeout(() => {
        toast.remove();
    }, 5000);
}

/**
 * Check if user is logged in (placeholder for auth)
 */
function checkAuth() {
    // TODO: Implement actual auth check
    // Return true if user is logged in, false otherwise
    return false;
}

/**
 * Get current user email (placeholder for auth)
 */
function getUserEmail() {
    // TODO: Implement actual user email retrieval
    return null;
}

// Export for use in other scripts
window.StockQueenCheckout = {
    startCheckout,
    showError,
    showSuccess,
    config: STRIPE_CONFIG
};
