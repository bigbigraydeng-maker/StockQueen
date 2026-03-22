/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./app/templates/**/*.html",
    "./app/routers/*.py",
    "./app/main.py",
  ],
  theme: {
    extend: {
      colors: {
        'sq-bg':     '#0f172a',
        'sq-card':   '#1e293b',
        'sq-border': '#334155',
        'sq-green':  '#22c55e',
        'sq-red':    '#ef4444',
        'sq-gold':   '#eab308',
        'sq-accent': '#8b5cf6',
        'sq-blue':   '#3b82f6',
      }
    }
  },
  plugins: [],
}
