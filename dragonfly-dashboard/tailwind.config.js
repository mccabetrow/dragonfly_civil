/** @type {import('tailwindcss').Config} */
export default {
  darkMode: 'class',
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
      // Premium Fintech Theme - Billion Dollar Dashboard
      colors: {
        // Core brand palette
        dragonfly: {
          // Deep navy foundations (dark theme)
          navy: {
            950: '#030712',
            900: '#0a0f1e',
            850: '#0d1423',
            800: '#111827',
            700: '#1e293b',
            600: '#334155',
          },
          // Premium cyan accent (Stripe/Plaid inspired)
          cyan: {
            50: '#ecfeff',
            100: '#cffafe',
            200: '#a5f3fc',
            300: '#67e8f9',
            400: '#22d3ee',
            500: '#06b6d4',
            600: '#0891b2',
            700: '#0e7490',
          },
          // Subtle gold/amber for premium highlights
          gold: {
            50: '#fffbeb',
            100: '#fef3c7',
            200: '#fde68a',
            300: '#fcd34d',
            400: '#fbbf24',
            500: '#f59e0b',
          },
          // Success green
          emerald: {
            400: '#34d399',
            500: '#10b981',
            600: '#059669',
          },
        },
        // Tremor color overrides for dark theme
        tremor: {
          brand: {
            faint: 'rgba(6, 182, 212, 0.05)',
            muted: 'rgba(6, 182, 212, 0.15)',
            subtle: '#22d3ee',
            DEFAULT: '#06b6d4',
            emphasis: '#0891b2',
            inverted: '#030712',
          },
          background: {
            muted: '#111827',
            subtle: '#0d1423',
            DEFAULT: '#0a0f1e',
            emphasis: '#1e293b',
          },
          border: {
            DEFAULT: 'rgba(255, 255, 255, 0.08)',
          },
          ring: {
            DEFAULT: 'rgba(6, 182, 212, 0.3)',
          },
          content: {
            subtle: '#64748b',
            DEFAULT: '#94a3b8',
            emphasis: '#e2e8f0',
            strong: '#f8fafc',
            inverted: '#030712',
          },
        },
      },
      boxShadow: {
        // Premium glass-morphism shadows
        'tremor-input': '0 1px 2px 0 rgb(0 0 0 / 0.3)',
        'tremor-card': '0 1px 3px 0 rgb(0 0 0 / 0.3), 0 1px 2px -1px rgb(0 0 0 / 0.2)',
        'tremor-dropdown': '0 10px 40px -10px rgb(0 0 0 / 0.5)',
        // Premium glow effects
        'glow-cyan': '0 0 20px rgba(6, 182, 212, 0.15)',
        'glow-gold': '0 0 20px rgba(251, 191, 36, 0.15)',
        'glow-emerald': '0 0 20px rgba(16, 185, 129, 0.15)',
        // Card elevations
        'card-sm': '0 2px 8px rgba(0, 0, 0, 0.3)',
        'card-md': '0 4px 16px rgba(0, 0, 0, 0.4)',
        'card-lg': '0 8px 32px rgba(0, 0, 0, 0.5)',
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
      backgroundImage: {
        // Premium gradients
        'gradient-radial': 'radial-gradient(var(--tw-gradient-stops))',
        'gradient-conic': 'conic-gradient(from 180deg at 50% 50%, var(--tw-gradient-stops))',
        'mesh-dark': 'radial-gradient(at 40% 20%, rgba(6, 182, 212, 0.05) 0px, transparent 50%), radial-gradient(at 80% 0%, rgba(251, 191, 36, 0.03) 0px, transparent 50%)',
      },
      animation: {
        'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'glow': 'glow 2s ease-in-out infinite alternate',
      },
      keyframes: {
        glow: {
          '0%': { opacity: 0.5 },
          '100%': { opacity: 1 },
        },
      },
    },
  },
  plugins: [],
};
