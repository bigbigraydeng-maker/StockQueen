/**
 * StockQueen Marketing Website - Chart Module
 * Renders equity curve using Chart.js
 */

let equityChart = null;

function renderEquityChart(data) {
    const ctx = document.getElementById('equityChart');
    
    if (!ctx) {
        console.error('Chart canvas not found');
        return;
    }
    
    // Destroy existing chart if any
    if (equityChart) {
        equityChart.destroy();
    }
    
    // Prepare data
    const labels = data.map(d => {
        const date = new Date(d.date);
        return date.toLocaleDateString('en-US', { month: 'short', year: '2-digit' });
    });
    
    const strategyData = data.map(d => (d.strategy - 1) * 100); // Convert to percentage return
    const spyData = data.map(d => (d.spy - 1) * 100);
    const qqqData = data.map(d => (d.qqq - 1) * 100);
    
    // Chart configuration
    equityChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [
                {
                    label: 'Strategy',
                    data: strategyData,
                    borderColor: '#06b6d4', // Cyan
                    backgroundColor: 'rgba(6, 182, 212, 0.1)',
                    borderWidth: 3,
                    fill: true,
                    tension: 0.4,
                    pointRadius: 0,
                    pointHoverRadius: 6,
                    pointHoverBackgroundColor: '#06b6d4',
                    pointHoverBorderColor: '#ffffff',
                    pointHoverBorderWidth: 2
                },
                {
                    label: 'SPY',
                    data: spyData,
                    borderColor: '#9ca3af', // Gray
                    backgroundColor: 'transparent',
                    borderWidth: 2,
                    borderDash: [5, 5],
                    fill: false,
                    tension: 0.4,
                    pointRadius: 0,
                    pointHoverRadius: 4,
                    pointHoverBackgroundColor: '#9ca3af',
                    pointHoverBorderColor: '#ffffff',
                    pointHoverBorderWidth: 2
                },
                {
                    label: 'QQQ',
                    data: qqqData,
                    borderColor: '#f97316', // Orange
                    backgroundColor: 'transparent',
                    borderWidth: 2,
                    borderDash: [3, 3],
                    fill: false,
                    tension: 0.4,
                    pointRadius: 0,
                    pointHoverRadius: 4,
                    pointHoverBackgroundColor: '#f97316',
                    pointHoverBorderColor: '#ffffff',
                    pointHoverBorderWidth: 2
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: {
                mode: 'index',
                intersect: false
            },
            plugins: {
                legend: {
                    display: true,
                    position: 'top',
                    align: 'end',
                    labels: {
                        color: '#9ca3af',
                        font: {
                            family: 'Inter',
                            size: 12
                        },
                        usePointStyle: true,
                        pointStyle: 'circle',
                        padding: 20
                    }
                },
                tooltip: {
                    backgroundColor: 'rgba(11, 15, 25, 0.95)',
                    titleColor: '#ffffff',
                    bodyColor: '#9ca3af',
                    borderColor: 'rgba(255, 255, 255, 0.1)',
                    borderWidth: 1,
                    padding: 12,
                    displayColors: true,
                    callbacks: {
                        label: function(context) {
                            const label = context.dataset.label || '';
                            const value = context.parsed.y;
                            const sign = value >= 0 ? '+' : '';
                            return `${label}: ${sign}${value.toFixed(2)}%`;
                        }
                    }
                }
            },
            scales: {
                x: {
                    display: true,
                    grid: {
                        display: false,
                        drawBorder: false
                    },
                    ticks: {
                        color: '#6b7280',
                        font: {
                            family: 'Inter',
                            size: 11
                        },
                        maxTicksLimit: 8
                    }
                },
                y: {
                    display: true,
                    grid: {
                        color: 'rgba(255, 255, 255, 0.03)',
                        drawBorder: false
                    },
                    ticks: {
                        color: '#6b7280',
                        font: {
                            family: 'Inter',
                            size: 11
                        },
                        callback: function(value) {
                            const sign = value >= 0 ? '+' : '';
                            return `${sign}${value.toFixed(0)}%`;
                        }
                    }
                }
            },
            animation: {
                duration: 1500,
                easing: 'easeOutQuart'
            }
        }
    });
}

// Alternative chart for smaller displays
function renderMiniChart(data, containerId) {
    const container = document.getElementById(containerId);
    if (!container) return;
    
    // Create canvas
    const canvas = document.createElement('canvas');
    canvas.height = 60;
    container.innerHTML = '';
    container.appendChild(canvas);
    
    const ctx = canvas.getContext('2d');
    
    // Simple sparkline
    const values = data.map(d => d.strategy);
    const min = Math.min(...values);
    const max = Math.max(...values);
    const range = max - min || 1;
    
    const width = canvas.width = container.offsetWidth;
    const height = canvas.height = 60;
    
    // Draw line
    ctx.beginPath();
    ctx.strokeStyle = '#06b6d4';
    ctx.lineWidth = 2;
    
    values.forEach((value, i) => {
        const x = (i / (values.length - 1)) * width;
        const y = height - ((value - min) / range) * (height - 10) - 5;
        
        if (i === 0) {
            ctx.moveTo(x, y);
        } else {
            ctx.lineTo(x, y);
        }
    });
    
    ctx.stroke();
    
    // Add gradient fill
    ctx.lineTo(width, height);
    ctx.lineTo(0, height);
    ctx.closePath();
    
    const gradient = ctx.createLinearGradient(0, 0, 0, height);
    gradient.addColorStop(0, 'rgba(6, 182, 212, 0.3)');
    gradient.addColorStop(1, 'rgba(6, 182, 212, 0)');
    ctx.fillStyle = gradient;
    ctx.fill();
}
