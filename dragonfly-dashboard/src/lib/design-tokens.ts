/**
 * Dragonfly Civil Design System Tokens
 * 
 * These tokens define the visual language of the entire application.
 * Use these constants instead of hardcoding Tailwind classes.
 */

// ═══════════════════════════════════════════════════════════════════════════
// COLOR TOKENS
// ═══════════════════════════════════════════════════════════════════════════

export const colors = {
  // Brand Colors – Dragonfly indigo for stronger identity
  brand: {
    primary: 'indigo-600',
    primaryHover: 'indigo-700',
    primaryLight: 'indigo-50',
    primaryMuted: 'indigo-100',
    primaryDark: 'indigo-800',
    accent: 'violet-500', // secondary accent for highlights
  },
  
  // Tier Colors (the core business concept)
  tier: {
    a: {
      bg: 'emerald-50',
      border: 'emerald-200',
      text: 'emerald-700',
      badge: 'bg-emerald-100 text-emerald-700 border-emerald-200',
      dot: 'bg-emerald-500',
    },
    b: {
      bg: 'amber-50',
      border: 'amber-200',
      text: 'amber-700',
      badge: 'bg-amber-100 text-amber-700 border-amber-200',
      dot: 'bg-amber-500',
    },
    c: {
      bg: 'slate-100',
      border: 'slate-200',
      text: 'slate-600',
      badge: 'bg-slate-100 text-slate-600 border-slate-200',
      dot: 'bg-slate-400',
    },
  },

  // Status Colors
  status: {
    success: {
      bg: 'emerald-50',
      border: 'emerald-200',
      text: 'emerald-700',
      icon: 'emerald-500',
    },
    warning: {
      bg: 'amber-50',
      border: 'amber-200',
      text: 'amber-700',
      icon: 'amber-500',
    },
    error: {
      bg: 'rose-50',
      border: 'rose-200',
      text: 'rose-700',
      icon: 'rose-500',
    },
    info: {
      bg: 'blue-50',
      border: 'blue-200',
      text: 'blue-700',
      icon: 'blue-500',
    },
    neutral: {
      bg: 'slate-50',
      border: 'slate-200',
      text: 'slate-600',
      icon: 'slate-400',
    },
  },

  // Surface Colors - Light mode
  surface: {
    page: 'slate-50',
    card: 'white',
    cardHover: 'slate-50',
    sidebar: 'slate-900',
    sidebarHover: 'slate-800',
    header: 'white/95',
    overlay: 'slate-900/50',
  },

  // Surface Colors - Dark mode (Premium Fintech)
  surfaceDark: {
    page: 'dragonfly-navy-900',
    card: 'dragonfly-navy-800',
    cardHover: 'dragonfly-navy-700',
    sidebar: 'dragonfly-navy-950',
    sidebarHover: 'dragonfly-navy-900',
    header: 'dragonfly-navy-900/80',
    overlay: 'black/60',
    elevated: 'dragonfly-navy-850',
  },

  // Text Colors
  text: {
    primary: 'slate-900',
    secondary: 'slate-600',
    tertiary: 'slate-500',
    muted: 'slate-400',
    inverse: 'white',
    link: 'blue-600',
    linkHover: 'blue-700',
  },

  // Text Colors - Dark mode
  textDark: {
    primary: 'white',
    secondary: 'slate-300',
    tertiary: 'slate-400',
    muted: 'slate-500',
    inverse: 'dragonfly-navy-950',
    link: 'cyan-400',
    linkHover: 'cyan-300',
  },

  // Accent colors for dark mode
  accent: {
    primary: 'cyan-500',
    primaryHover: 'cyan-400',
    secondary: 'amber-400',
    success: 'emerald-400',
    warning: 'amber-400',
    error: 'rose-400',
  },

  // Border Colors
  border: {
    default: 'slate-200',
    hover: 'slate-300',
    focus: 'blue-500',
    separator: 'slate-100',
  },

  // Border Colors - Dark mode
  borderDark: {
    default: 'white/5',
    hover: 'white/10',
    focus: 'cyan-500/50',
    separator: 'white/5',
    glow: 'cyan-500/20',
  },
} as const;

// ═══════════════════════════════════════════════════════════════════════════
// SPACING TOKENS
// ═══════════════════════════════════════════════════════════════════════════

export const spacing = {
  // Component internal spacing
  card: {
    padding: 'p-6',
    paddingCompact: 'p-4',
    gap: 'gap-4',
  },
  
  // Section spacing
  section: {
    gap: 'space-y-6',
    gapLarge: 'space-y-8',
  },

  // Grid gaps
  grid: {
    gap: 'gap-4',
    gapLarge: 'gap-6',
  },

  // Table spacing
  table: {
    cellPadding: 'px-4 py-3',
    headerPadding: 'px-4 py-3',
  },

  // Form spacing
  form: {
    fieldGap: 'gap-2',
    sectionGap: 'gap-6',
  },

  // Page container
  page: {
    maxWidth: 'max-w-6xl',
    padding: 'px-4 sm:px-6 lg:px-8',
    paddingY: 'py-8',
  },
} as const;

// ═══════════════════════════════════════════════════════════════════════════
// TYPOGRAPHY TOKENS
// ═══════════════════════════════════════════════════════════════════════════

export const typography = {
  // Headings - Light mode
  h1: 'text-2xl font-semibold text-slate-900 dark:text-white',
  h2: 'text-lg font-semibold text-slate-900 dark:text-white',
  h3: 'text-base font-semibold text-slate-900 dark:text-white',
  h4: 'text-sm font-semibold text-slate-900 dark:text-white',

  // Body text
  body: 'text-sm text-slate-600 dark:text-slate-300',
  bodyLarge: 'text-base text-slate-600 dark:text-slate-300',
  bodySmall: 'text-xs text-slate-600 dark:text-slate-400',

  // Labels
  label: 'text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400',
  labelSmall: 'text-[11px] font-semibold uppercase tracking-wide text-slate-400 dark:text-slate-500',

  // Metrics - Premium styling for dark mode
  metricLarge: 'text-3xl font-semibold tracking-tight text-slate-900 dark:text-white',
  metricMedium: 'text-2xl font-semibold text-slate-900 dark:text-white',
  metricSmall: 'text-xl font-semibold text-slate-900 dark:text-white',

  // Table
  tableHeader: 'text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400',
  tableCell: 'text-sm text-slate-700 dark:text-slate-200',
  tableCellMuted: 'text-sm text-slate-500 dark:text-slate-400',

  // Links
  link: 'text-blue-600 hover:text-blue-700 hover:underline dark:text-cyan-400 dark:hover:text-cyan-300',
  linkSubtle: 'text-slate-600 hover:text-slate-900 dark:text-slate-400 dark:hover:text-white',
} as const;

// ═══════════════════════════════════════════════════════════════════════════
// COMPONENT TOKENS
// ═══════════════════════════════════════════════════════════════════════════

export const components = {
  // Card styles - Light mode
  card: {
    base: 'rounded-2xl border border-slate-200 bg-white shadow-sm dark:border-white/5 dark:bg-dragonfly-navy-800/50 dark:backdrop-blur-sm',
    hover: 'hover:shadow-md hover:border-slate-300 transition-all duration-200 dark:hover:border-white/10 dark:hover:shadow-card-md',
    interactive: 'cursor-pointer hover:shadow-md hover:border-slate-300 hover:-translate-y-0.5 transition-all duration-200 dark:hover:border-cyan-500/20 dark:hover:shadow-glow-cyan',
  },

  // Premium card for dark mode
  cardDark: {
    base: 'rounded-2xl border border-white/5 bg-dragonfly-navy-800/50 backdrop-blur-sm',
    elevated: 'rounded-2xl border border-white/10 bg-dragonfly-navy-800/80 shadow-card-md backdrop-blur-sm',
    glow: 'rounded-2xl border border-cyan-500/20 bg-dragonfly-navy-800/50 shadow-glow-cyan backdrop-blur-sm',
  },

  // Button styles - with dark mode support
  button: {
    base: 'inline-flex items-center justify-center font-semibold transition-all duration-150 focus:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 active:scale-[0.98] dark:focus-visible:ring-offset-dragonfly-navy-900',
    primary: 'bg-indigo-600 text-white hover:bg-indigo-700 focus-visible:ring-indigo-500 dark:bg-cyan-500 dark:text-dragonfly-navy-950 dark:hover:bg-cyan-400 dark:focus-visible:ring-cyan-400',
    secondary: 'bg-white text-slate-700 border border-slate-300 hover:bg-slate-50 hover:border-slate-400 focus-visible:ring-slate-500 dark:bg-white/5 dark:text-white dark:border-white/10 dark:hover:bg-white/10 dark:hover:border-white/20',
    ghost: 'text-slate-600 hover:bg-slate-100 hover:text-slate-900 focus-visible:ring-slate-500',
    danger: 'bg-rose-600 text-white hover:bg-rose-700 focus-visible:ring-rose-500',
    sizes: {
      sm: 'text-xs px-3 py-1.5 rounded-lg',
      md: 'text-sm px-4 py-2 rounded-xl',
      lg: 'text-base px-5 py-2.5 rounded-xl',
    },
  },

  // Input styles
  input: {
    base: 'rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 placeholder:text-slate-400 focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/20',
    error: 'border-rose-300 focus:border-rose-500 focus:ring-rose-500/20',
    disabled: 'bg-slate-100 text-slate-500 cursor-not-allowed',
  },

  // Badge styles
  badge: {
    base: 'inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-semibold border',
    tier: {
      a: 'bg-emerald-50 text-emerald-700 border-emerald-200',
      b: 'bg-amber-50 text-amber-700 border-amber-200',
      c: 'bg-slate-100 text-slate-600 border-slate-200',
    },
  },

  // Table styles
  table: {
    container: 'overflow-hidden rounded-xl border border-slate-200',
    header: 'bg-slate-50',
    headerCell: 'px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-slate-500',
    row: 'border-t border-slate-100 bg-white transition hover:bg-slate-50',
    rowSelected: 'bg-blue-50/60',
    cell: 'px-4 py-3 text-sm text-slate-700',
  },

  // Skeleton styles
  skeleton: {
    base: 'animate-pulse rounded bg-slate-200',
    line: 'h-4 w-full',
    circle: 'rounded-full',
  },

  // Toast styles
  toast: {
    base: 'pointer-events-auto rounded-xl border shadow-lg backdrop-blur-sm',
    success: 'bg-emerald-50/95 border-emerald-200 text-emerald-800',
    error: 'bg-rose-50/95 border-rose-200 text-rose-800',
    warning: 'bg-amber-50/95 border-amber-200 text-amber-800',
    info: 'bg-blue-50/95 border-blue-200 text-blue-800',
  },
} as const;

// ═══════════════════════════════════════════════════════════════════════════
// ANIMATION TOKENS
// ═══════════════════════════════════════════════════════════════════════════

export const animation = {
  // Transitions
  fast: 'duration-150',
  normal: 'duration-200',
  slow: 'duration-300',
  drawer: 'duration-300',

  // Easing
  easeOut: 'ease-out',
  easeInOut: 'ease-in-out',
  spring: 'cubic-bezier(0.32, 0.72, 0, 1)',

  // Common transitions
  hover: 'transition-all duration-200 ease-out',
  focus: 'transition-shadow duration-150 ease-out',
  
  // Micro-interactions
  press: 'active:scale-[0.98] active:transition-transform',
  hoverScale: 'hover:scale-[1.01] transition-transform duration-150',
  lift: 'hover:-translate-y-0.5 transition-transform duration-150',
  
  // Drawer animations
  drawerSlideIn: 'animate-drawer-slide-in',
  drawerSlideOut: 'animate-drawer-slide-out',
  
  // Fade animations
  fadeIn: 'animate-fade-in',
  fadeOut: 'animate-fade-out',
  
  // Scale animations
  scaleIn: 'animate-scale-in',
} as const;

// ═══════════════════════════════════════════════════════════════════════════
// SHADOWS TOKENS
// ═══════════════════════════════════════════════════════════════════════════

export const shadows = {
  // Elevation levels – refined for depth
  sm: 'shadow-sm',
  md: 'shadow-md',
  lg: 'shadow-lg',
  xl: 'shadow-xl',
  
  // Specialty shadows – tuned for Dragonfly
  card: 'shadow-[0_1px_3px_0_rgb(0_0_0/0.04),0_1px_2px_-1px_rgb(0_0_0/0.04)]',
  cardHover: 'shadow-[0_4px_12px_0_rgb(0_0_0/0.08),0_2px_4px_-2px_rgb(0_0_0/0.04)]',
  dropdown: 'shadow-lg shadow-slate-200/60',
  drawer: 'shadow-2xl shadow-slate-900/20',
  modal: 'shadow-2xl shadow-slate-900/20',
  header: 'shadow-[0_1px_2px_0_rgb(0_0_0/0.03)]',
  
  // Color-tinted shadows
  indigo: 'shadow-lg shadow-indigo-500/10',
  emerald: 'shadow-lg shadow-emerald-500/10',
  violet: 'shadow-lg shadow-violet-500/10',
} as const;

// ═══════════════════════════════════════════════════════════════════════════
// BORDER RADIUS TOKENS
// ═══════════════════════════════════════════════════════════════════════════

export const radii = {
  sm: 'rounded-lg',
  md: 'rounded-xl',
  lg: 'rounded-2xl',
  full: 'rounded-full',
  
  // Component-specific
  card: 'rounded-2xl',
  button: 'rounded-xl',
  input: 'rounded-xl',
  badge: 'rounded-full',
  avatar: 'rounded-full',
} as const;

// ═══════════════════════════════════════════════════════════════════════════
// RESPONSIVE BREAKPOINTS
// ═══════════════════════════════════════════════════════════════════════════

export const breakpoints = {
  sm: '640px',
  md: '768px',
  lg: '1024px',
  xl: '1280px',
  '2xl': '1536px',
} as const;

// ═══════════════════════════════════════════════════════════════════════════
// Z-INDEX SCALE
// ═══════════════════════════════════════════════════════════════════════════

export const zIndex = {
  dropdown: 'z-10',
  sticky: 'z-20',
  drawer: 'z-30',
  modal: 'z-40',
  toast: 'z-50',
  tooltip: 'z-[60]',
} as const;

// ═══════════════════════════════════════════════════════════════════════════
// HELPER FUNCTIONS
// ═══════════════════════════════════════════════════════════════════════════

type TierColor = typeof colors.tier.a | typeof colors.tier.b | typeof colors.tier.c;

export function getTierColor(tier: 'A' | 'B' | 'C' | string): TierColor {
  const normalized = tier.toUpperCase();
  if (normalized === 'A') return colors.tier.a;
  if (normalized === 'B') return colors.tier.b;
  return colors.tier.c;
}

export function getTierBadgeClass(tier: 'A' | 'B' | 'C' | string): string {
  const normalized = tier.toUpperCase();
  if (normalized === 'A') return components.badge.tier.a;
  if (normalized === 'B') return components.badge.tier.b;
  return components.badge.tier.c;
}

// ═══════════════════════════════════════════════════════════════════════════
// CLASS NAME HELPERS
// ═══════════════════════════════════════════════════════════════════════════

export function cn(...classes: (string | boolean | undefined | null)[]): string {
  return classes.filter(Boolean).join(' ');
}
