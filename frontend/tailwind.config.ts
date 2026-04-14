import type { Config } from 'tailwindcss';

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        'brand-indigo': '#3F51B5',
        'brand-teal': '#0F6E56',
        'brand-surface': '#F8F9FA',
        'brand-text': '#1A1A2E',
        'brand-text-secondary': '#6B7280',
        'brand-success': '#10B981',
        'brand-warning': '#F59E0B',
        'brand-error': '#EF4444',
      },
      fontFamily: {
        sans: ['"Plus Jakarta Sans"', 'system-ui', 'sans-serif'],
      },
      borderRadius: {
        brand: '8px',
      },
    },
  },
  plugins: [],
} satisfies Config;
