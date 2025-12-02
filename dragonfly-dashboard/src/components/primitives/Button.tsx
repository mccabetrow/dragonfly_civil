/**
 * Button Component
 * ═══════════════════════════════════════════════════════════════════════════
 * 
 * Enterprise-grade button with press animations and multiple variants.
 * Inspired by Stripe's button system.
 */

import * as React from 'react';
import { Slot } from '@radix-ui/react-slot';
import { cva, type VariantProps } from 'class-variance-authority';
import { motion } from 'framer-motion';
import { cn } from '../../lib/tokens';

const buttonVariants = cva(
  // Base styles
  `inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-lg text-sm font-medium
   transition-all duration-150 ease-out
   focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2
   disabled:pointer-events-none disabled:opacity-50
   [&_svg]:pointer-events-none [&_svg]:size-4 [&_svg]:shrink-0`,
  {
    variants: {
      variant: {
        primary: `
          bg-indigo-600 text-white shadow-sm
          hover:bg-indigo-700 
          focus-visible:ring-indigo-500
          active:bg-indigo-800
        `,
        secondary: `
          bg-slate-100 text-slate-900 shadow-sm
          hover:bg-slate-200
          focus-visible:ring-slate-500
          active:bg-slate-300
        `,
        outline: `
          border border-slate-300 bg-white text-slate-700 shadow-sm
          hover:bg-slate-50 hover:border-slate-400
          focus-visible:ring-slate-500
          active:bg-slate-100
        `,
        ghost: `
          text-slate-600 
          hover:bg-slate-100 hover:text-slate-900
          focus-visible:ring-slate-500
          active:bg-slate-200
        `,
        link: `
          text-indigo-600 underline-offset-4
          hover:underline hover:text-indigo-700
          focus-visible:ring-indigo-500
        `,
        danger: `
          bg-red-600 text-white shadow-sm
          hover:bg-red-700
          focus-visible:ring-red-500
          active:bg-red-800
        `,
        success: `
          bg-emerald-600 text-white shadow-sm
          hover:bg-emerald-700
          focus-visible:ring-emerald-500
          active:bg-emerald-800
        `,
      },
      size: {
        xs: 'h-7 px-2.5 text-xs rounded-md',
        sm: 'h-8 px-3 text-sm rounded-md',
        md: 'h-9 px-4 text-sm',
        lg: 'h-10 px-5 text-base',
        xl: 'h-12 px-6 text-base',
        icon: 'h-9 w-9',
        'icon-sm': 'h-8 w-8',
        'icon-lg': 'h-10 w-10',
      },
    },
    defaultVariants: {
      variant: 'primary',
      size: 'md',
    },
  }
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean;
  loading?: boolean;
  leftIcon?: React.ReactNode;
  rightIcon?: React.ReactNode;
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ 
    className, 
    variant, 
    size, 
    asChild = false, 
    loading = false,
    leftIcon,
    rightIcon,
    children,
    disabled,
    ...props 
  }, ref) => {
    const Comp = asChild ? Slot : 'button';
    
    return (
      <motion.div
        whileTap={{ scale: disabled || loading ? 1 : 0.98 }}
        transition={{ duration: 0.1 }}
        className="inline-flex"
      >
        <Comp
          className={cn(buttonVariants({ variant, size, className }))}
          ref={ref}
          disabled={disabled || loading}
          {...props}
        >
          {loading && (
            <svg 
              className="h-4 w-4 animate-spin" 
              xmlns="http://www.w3.org/2000/svg" 
              fill="none" 
              viewBox="0 0 24 24"
            >
              <circle 
                className="opacity-25" 
                cx="12" 
                cy="12" 
                r="10" 
                stroke="currentColor" 
                strokeWidth="4"
              />
              <path 
                className="opacity-75" 
                fill="currentColor" 
                d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
              />
            </svg>
          )}
          {!loading && leftIcon}
          {children}
          {!loading && rightIcon}
        </Comp>
      </motion.div>
    );
  }
);
Button.displayName = 'Button';

// Icon-only button variant
export interface IconButtonProps extends ButtonProps {
  'aria-label': string;
}

const IconButton = React.forwardRef<HTMLButtonElement, IconButtonProps>(
  ({ size = 'icon', ...props }, ref) => {
    return <Button ref={ref} size={size} {...props} />;
  }
);
IconButton.displayName = 'IconButton';

export { Button, IconButton, buttonVariants };
