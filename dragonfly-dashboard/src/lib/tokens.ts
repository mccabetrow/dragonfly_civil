/**
 * Dragonfly Civil Design Tokens
 * ═══════════════════════════════════════════════════════════════════════════
 * 
 * Hedge-fund-grade design system tokens for the enforcement terminal.
 * Inspired by Bloomberg Terminal × Stripe Dashboard × Palantir Foundry × Ramp.
 */

// ═══════════════════════════════════════════════════════════════════════════
// BRAND COLORS
// ═══════════════════════════════════════════════════════════════════════════

export const brand = {
  // Primary brand color - Dragonfly indigo
  primary: {
    50: '#eef2ff',
    100: '#e0e7ff',
    200: '#c7d2fe',
    300: '#a5b4fc',
    400: '#818cf8',
    500: '#6366f1',
    600: '#4f46e5', // Primary action color
    700: '#4338ca',
    800: '#3730a3',
    900: '#312e81',
    950: '#1e1b4b',
  },
  // Accent - Success/Tier A green
  accent: {
    50: '#ecfdf5',
    100: '#d1fae5',
    200: '#a7f3d0',
    300: '#6ee7b7',
    400: '#34d399',
    500: '#10b981', // Primary accent
    600: '#059669',
    700: '#047857',
    800: '#065f46',
    900: '#064e3b',
  },
  // Warning - Tier B amber
  warning: {
    50: '#fffbeb',
    100: '#fef3c7',
    200: '#fde68a',
    300: '#fcd34d',
    400: '#fbbf24',
    500: '#f59e0b',
    600: '#d97706',
    700: '#b45309',
    800: '#92400e',
    900: '#78350f',
  },
  // Danger - Alerts/errors
  danger: {
    50: '#fef2f2',
    100: '#fee2e2',
    200: '#fecaca',
    300: '#fca5a5',
    400: '#f87171',
    500: '#ef4444',
    600: '#dc2626',
    700: '#b91c1c',
    800: '#991b1b',
    900: '#7f1d1d',
  },
  // Neutral - Slate for Tier C and UI chrome
  neutral: {
    50: '#f8fafc',
    100: '#f1f5f9',
    200: '#e2e8f0',
    300: '#cbd5e1',
    400: '#94a3b8',
    500: '#64748b',
    600: '#475569',
    700: '#334155',
    800: '#1e293b',
    900: '#0f172a',
    950: '#020617',
  },
} as const;

// ═══════════════════════════════════════════════════════════════════════════
// TIER COLORS (Core business concept)
// ═══════════════════════════════════════════════════════════════════════════

export const tier = {
  A: {
    bg: 'bg-emerald-500/10',
    bgSolid: 'bg-emerald-500',
    border: 'border-emerald-500/30',
    text: 'text-emerald-400',
    textSolid: 'text-emerald-500',
    ring: 'ring-emerald-500/20',
    glow: 'shadow-emerald-500/25',
    gradient: 'from-emerald-500 to-teal-600',
    hex: '#10b981',
  },
  B: {
    bg: 'bg-amber-500/10',
    bgSolid: 'bg-amber-500',
    border: 'border-amber-500/30',
    text: 'text-amber-400',
    textSolid: 'text-amber-500',
    ring: 'ring-amber-500/20',
    glow: 'shadow-amber-500/25',
    gradient: 'from-amber-500 to-orange-600',
    hex: '#f59e0b',
  },
  C: {
    bg: 'bg-slate-500/10',
    bgSolid: 'bg-slate-500',
    border: 'border-slate-500/30',
    text: 'text-slate-400',
    textSolid: 'text-slate-500',
    ring: 'ring-slate-500/20',
    glow: 'shadow-slate-500/25',
    gradient: 'from-slate-500 to-slate-600',
    hex: '#64748b',
  },
} as const;

// ═══════════════════════════════════════════════════════════════════════════
// SHADOWS (Stripe-inspired depth system)
// ═══════════════════════════════════════════════════════════════════════════

export const shadow = {
  // Subtle elevation
  xs: '0 1px 2px 0 rgb(0 0 0 / 0.05)',
  sm: '0 1px 3px 0 rgb(0 0 0 / 0.1), 0 1px 2px -1px rgb(0 0 0 / 0.1)',
  
  // Card shadows (Stripe-style)
  card: '0 0 0 1px rgb(0 0 0 / 0.03), 0 2px 4px rgb(0 0 0 / 0.05), 0 12px 24px rgb(0 0 0 / 0.05)',
  cardHover: '0 0 0 1px rgb(0 0 0 / 0.03), 0 4px 8px rgb(0 0 0 / 0.08), 0 16px 32px rgb(0 0 0 / 0.08)',
  cardActive: '0 0 0 1px rgb(0 0 0 / 0.03), 0 1px 2px rgb(0 0 0 / 0.06)',
  
  // Elevated elements
  md: '0 4px 6px -1px rgb(0 0 0 / 0.1), 0 2px 4px -2px rgb(0 0 0 / 0.1)',
  lg: '0 10px 15px -3px rgb(0 0 0 / 0.1), 0 4px 6px -4px rgb(0 0 0 / 0.1)',
  xl: '0 20px 25px -5px rgb(0 0 0 / 0.1), 0 8px 10px -6px rgb(0 0 0 / 0.1)',
  
  // Floating elements (modals, dropdowns)
  float: '0 25px 50px -12px rgb(0 0 0 / 0.25)',
  
  // Inset for inputs
  inset: 'inset 0 1px 2px rgb(0 0 0 / 0.05)',
  
  // Glow effects for focus states
  glow: {
    primary: '0 0 0 3px rgb(99 102 241 / 0.15)',
    success: '0 0 0 3px rgb(16 185 129 / 0.15)',
    warning: '0 0 0 3px rgb(245 158 11 / 0.15)',
    danger: '0 0 0 3px rgb(239 68 68 / 0.15)',
  },
} as const;

// ═══════════════════════════════════════════════════════════════════════════
// BORDER RADIUS
// ═══════════════════════════════════════════════════════════════════════════

export const radius = {
  none: '0',
  sm: '0.25rem',    // 4px
  md: '0.375rem',   // 6px
  lg: '0.5rem',     // 8px
  xl: '0.75rem',    // 12px
  '2xl': '1rem',    // 16px
  '3xl': '1.5rem',  // 24px
  full: '9999px',
} as const;

// ═══════════════════════════════════════════════════════════════════════════
// MOTION (Microinteractions)
// ═══════════════════════════════════════════════════════════════════════════

export const motion = {
  // Durations
  duration: {
    instant: 75,
    fast: 150,
    normal: 200,
    slow: 300,
    slower: 500,
  },
  
  // Easing curves
  ease: {
    default: [0.4, 0, 0.2, 1],
    in: [0.4, 0, 1, 1],
    out: [0, 0, 0.2, 1],
    inOut: [0.4, 0, 0.2, 1],
    bounce: [0.68, -0.55, 0.265, 1.55],
    spring: { type: 'spring', stiffness: 400, damping: 25 },
  },
  
  // Scale transforms
  scale: {
    press: 0.98,
    hover: 1.02,
    tap: 0.95,
  },
  
  // Opacity
  opacity: {
    hover: 0.8,
    disabled: 0.5,
    fade: 0.6,
  },
} as const;

// ═══════════════════════════════════════════════════════════════════════════
// TYPOGRAPHY
// ═══════════════════════════════════════════════════════════════════════════

export const typography = {
  fontFamily: {
    sans: ['Inter', 'system-ui', '-apple-system', 'sans-serif'],
    mono: ['Geist Mono', 'JetBrains Mono', 'Menlo', 'monospace'],
    display: ['Inter', 'system-ui', 'sans-serif'],
  },
  
  fontSize: {
    xs: ['0.75rem', { lineHeight: '1rem' }],
    sm: ['0.875rem', { lineHeight: '1.25rem' }],
    base: ['1rem', { lineHeight: '1.5rem' }],
    lg: ['1.125rem', { lineHeight: '1.75rem' }],
    xl: ['1.25rem', { lineHeight: '1.75rem' }],
    '2xl': ['1.5rem', { lineHeight: '2rem' }],
    '3xl': ['1.875rem', { lineHeight: '2.25rem' }],
    '4xl': ['2.25rem', { lineHeight: '2.5rem' }],
    '5xl': ['3rem', { lineHeight: '1' }],
  },
  
  fontWeight: {
    normal: '400',
    medium: '500',
    semibold: '600',
    bold: '700',
  },
  
  letterSpacing: {
    tighter: '-0.05em',
    tight: '-0.025em',
    normal: '0',
    wide: '0.025em',
    wider: '0.05em',
    widest: '0.1em',
  },
} as const;

// ═══════════════════════════════════════════════════════════════════════════
// SPACING
// ═══════════════════════════════════════════════════════════════════════════

export const spacing = {
  page: {
    x: 'px-6 lg:px-8',
    y: 'py-6 lg:py-8',
    all: 'p-6 lg:p-8',
  },
  section: {
    gap: 'space-y-6',
    gapLg: 'space-y-8',
  },
  card: {
    padding: 'p-5',
    paddingLg: 'p-6',
  },
} as const;

// ═══════════════════════════════════════════════════════════════════════════
// Z-INDEX
// ═══════════════════════════════════════════════════════════════════════════

export const zIndex = {
  base: 0,
  dropdown: 10,
  sticky: 20,
  overlay: 30,
  modal: 40,
  popover: 50,
  toast: 60,
  tooltip: 70,
  max: 9999,
} as const;

// ═══════════════════════════════════════════════════════════════════════════
// COMPONENT VARIANTS
// ═══════════════════════════════════════════════════════════════════════════

export const variants = {
  button: {
    primary: 'bg-indigo-600 text-white hover:bg-indigo-700 active:bg-indigo-800',
    secondary: 'bg-slate-100 text-slate-900 hover:bg-slate-200 active:bg-slate-300',
    ghost: 'text-slate-600 hover:bg-slate-100 hover:text-slate-900',
    danger: 'bg-red-600 text-white hover:bg-red-700 active:bg-red-800',
    success: 'bg-emerald-600 text-white hover:bg-emerald-700 active:bg-emerald-800',
    outline: 'border border-slate-300 bg-white text-slate-700 hover:bg-slate-50',
  },
  
  badge: {
    default: 'bg-slate-100 text-slate-700',
    primary: 'bg-indigo-100 text-indigo-700',
    success: 'bg-emerald-100 text-emerald-700',
    warning: 'bg-amber-100 text-amber-700',
    danger: 'bg-red-100 text-red-700',
  },
} as const;

// ═══════════════════════════════════════════════════════════════════════════
// CHART COLORS (Tremor-compatible)
// ═══════════════════════════════════════════════════════════════════════════

export const chartColors = {
  primary: ['#6366f1', '#8b5cf6', '#a78bfa', '#c4b5fd'],
  tiers: ['#10b981', '#f59e0b', '#64748b'], // A, B, C
  categorical: [
    '#6366f1', // indigo
    '#8b5cf6', // violet  
    '#ec4899', // pink
    '#f59e0b', // amber
    '#10b981', // emerald
    '#06b6d4', // cyan
    '#f97316', // orange
    '#84cc16', // lime
  ],
  sequential: {
    indigo: ['#e0e7ff', '#c7d2fe', '#a5b4fc', '#818cf8', '#6366f1', '#4f46e5'],
    emerald: ['#d1fae5', '#a7f3d0', '#6ee7b7', '#34d399', '#10b981', '#059669'],
  },
} as const;

// ═══════════════════════════════════════════════════════════════════════════
// UTILITY FUNCTIONS
// ═══════════════════════════════════════════════════════════════════════════

import { type ClassValue, clsx } from 'clsx';
import { twMerge } from 'tailwind-merge';

/**
 * Merge Tailwind classes with clsx
 */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

/**
 * Format currency for display
 */
export function formatCurrency(value: number, compact = false): string {
  if (compact) {
    if (value >= 1_000_000) return `$${(value / 1_000_000).toFixed(1)}M`;
    if (value >= 1_000) return `$${(value / 1_000).toFixed(0)}K`;
  }
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  }).format(value);
}

/**
 * Format percentage with trend indicator
 */
export function formatPercent(value: number, showSign = true): string {
  const sign = showSign && value > 0 ? '+' : '';
  return `${sign}${value.toFixed(1)}%`;
}

/**
 * Format large numbers compactly
 */
export function formatNumber(value: number, compact = false): string {
  if (compact) {
    if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
    if (value >= 1_000) return `${(value / 1_000).toFixed(0)}K`;
  }
  return new Intl.NumberFormat('en-US').format(value);
}

/**
 * Get tier color configuration
 */
export function getTierConfig(tierLetter: 'A' | 'B' | 'C') {
  return tier[tierLetter];
}

// Export all tokens as a single object for convenience
export const tokens = {
  brand,
  tier,
  shadow,
  radius,
  motion,
  typography,
  spacing,
  zIndex,
  variants,
  chartColors,
} as const;

export default tokens;
