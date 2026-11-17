/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      fontFamily: { sans: ['Inter', 'ui-sans-serif', 'system-ui', 'Segoe UI', 'sans-serif'] },
      boxShadow: { card: '0 1px 2px rgba(16,24,40,.04), 0 1px 3px rgba(16,24,40,.06)' },
      keyframes: {
        rise: { '0%': { opacity: 0, transform: 'translateY(6px)' }, '100%': { opacity: 1, transform: 'none' } },
        pulseRing: { '0%': { boxShadow: '0 0 0 0 rgba(2,132,199,.35)' }, '100%': { boxShadow: '0 0 0 10px rgba(2,132,199,0)' } },
      },
      animation: { rise: 'rise .35s ease-out both', pulseRing: 'pulseRing 1.4s ease-out infinite' },
    },
  },
  plugins: [],
}
