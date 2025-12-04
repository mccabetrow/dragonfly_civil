/** @type {import('tailwindcss').Config} */
export default {
  content: [
    './index.html',
    './src/**/*.{js,jsx,ts,tsx}',
    // Tremor module
    './node_modules/@tremor/**/*.{js,ts,jsx,tsx}',
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        mono: ['Geist Mono', 'ui-monospace', 'monospace'],
      },
      // Dragonfly theme colors
      colors: {
        dragonfly: {
          // Deep blue for primary
          navy: '#0f172a',
          'navy-light': '#1e293b',
          // Emerald accents
          emerald: '#10b981',
          'emerald-light': '#34d399',
          'emerald-dark': '#059669',
          // Steel gray backgrounds
          steel: '#f1f5f9',
          'steel-dark': '#e2e8f0',
          'steel-light': '#f8fafc',
        },
        // Tremor color overrides
        tremor: {
          brand: {
            faint: '#eff6ff',
            muted: '#bfdbfe',
            subtle: '#60a5fa',
            DEFAULT: '#3b82f6',
            emphasis: '#1d4ed8',
            inverted: '#ffffff',
          },
          background: {
            muted: '#f1f5f9',
            subtle: '#f8fafc',
            DEFAULT: '#ffffff',
            emphasis: '#0f172a',
          },
          border: {
            DEFAULT: '#e2e8f0',
          },
          ring: {
            DEFAULT: '#e2e8f0',
          },
          content: {
            subtle: '#64748b',
            DEFAULT: '#475569',
            emphasis: '#0f172a',
            strong: '#0f172a',
            inverted: '#ffffff',
          },
        },
      },
      boxShadow: {
        // Tremor shadows
        'tremor-input': '0 1px 2px 0 rgb(0 0 0 / 0.05)',
        'tremor-card': '0 1px 3px 0 rgb(0 0 0 / 0.1), 0 1px 2px -1px rgb(0 0 0 / 0.1)',
        'tremor-dropdown': '0 4px 6px -1px rgb(0 0 0 / 0.1), 0 2px 4px -2px rgb(0 0 0 / 0.1)',
      },
      borderRadius: {
        'tremor-small': '0.375rem',
        'tremor-default': '0.5rem',
        'tremor-full': '9999px',
      },
      fontSize: {
        'tremor-label': ['0.75rem', { lineHeight: '1rem' }],
        'tremor-default': ['0.875rem', { lineHeight: '1.25rem' }],
        'tremor-title': ['1.125rem', { lineHeight: '1.75rem' }],
        'tremor-metric': ['1.875rem', { lineHeight: '2.25rem' }],
      },
    },
  },
  plugins: [],
};
