/**
 * Card Component
 * ═══════════════════════════════════════════════════════════════════════════
 * 
 * Enterprise-grade card with Stripe-style shadows and hover effects.
 */

import * as React from 'react';
import { motion } from 'framer-motion';
import { cn } from '../../lib/tokens';

export interface CardProps extends React.HTMLAttributes<HTMLDivElement> {
  /** Enable hover lift effect */
  hoverable?: boolean;
  /** Enable press effect */
  pressable?: boolean;
  /** Padding size */
  padding?: 'none' | 'sm' | 'md' | 'lg';
  /** Border style */
  border?: 'none' | 'subtle' | 'strong';
  /** Background variant */
  variant?: 'default' | 'elevated' | 'filled' | 'ghost';
}

const paddingClasses = {
  none: '',
  sm: 'p-4',
  md: 'p-5',
  lg: 'p-6',
};

const borderClasses = {
  none: '',
  subtle: 'border border-slate-200/60',
  strong: 'border border-slate-200',
};

const variantClasses = {
  default: 'bg-white',
  elevated: 'bg-white shadow-lg',
  filled: 'bg-slate-50',
  ghost: 'bg-transparent',
};

const Card = React.forwardRef<HTMLDivElement, CardProps>(
  ({ 
    className, 
    hoverable = false, 
    pressable = false,
    padding = 'md',
    border = 'subtle',
    variant = 'default',
    children,
    ...props 
  }, ref) => {
    const baseClasses = cn(
      'rounded-xl transition-all duration-200',
      paddingClasses[padding],
      borderClasses[border],
      variantClasses[variant],
      // Card shadow
      variant !== 'ghost' && '[box-shadow:0_0_0_1px_rgb(0_0_0/0.03),0_2px_4px_rgb(0_0_0/0.05),0_12px_24px_rgb(0_0_0/0.05)]',
      // Hover states
      hoverable && 'cursor-pointer hover:[box-shadow:0_0_0_1px_rgb(0_0_0/0.03),0_4px_8px_rgb(0_0_0/0.08),0_16px_32px_rgb(0_0_0/0.08)] hover:-translate-y-0.5',
      // Press states
      pressable && 'active:translate-y-0 active:[box-shadow:0_0_0_1px_rgb(0_0_0/0.03),0_1px_2px_rgb(0_0_0/0.06)]',
      className
    );

    if (hoverable || pressable) {
      return (
        <motion.div
          ref={ref as React.Ref<HTMLDivElement>}
          className={baseClasses}
          whileHover={hoverable ? { y: -2 } : undefined}
          whileTap={pressable ? { scale: 0.99 } : undefined}
          transition={{ duration: 0.15, ease: 'easeOut' }}
          {...(props as any)}
        >
          {children}
        </motion.div>
      );
    }

    return (
      <div ref={ref} className={baseClasses} {...props}>
        {children}
      </div>
    );
  }
);
Card.displayName = 'Card';

// Card Header
export interface CardHeaderProps extends React.HTMLAttributes<HTMLDivElement> {
  /** Add bottom border */
  bordered?: boolean;
}

const CardHeader = React.forwardRef<HTMLDivElement, CardHeaderProps>(
  ({ className, bordered = false, ...props }, ref) => (
    <div
      ref={ref}
      className={cn(
        'flex flex-col gap-1.5',
        bordered && 'border-b border-slate-100 pb-4 mb-4',
        className
      )}
      {...props}
    />
  )
);
CardHeader.displayName = 'CardHeader';

// Card Title
const CardTitle = React.forwardRef<HTMLHeadingElement, React.HTMLAttributes<HTMLHeadingElement>>(
  ({ className, ...props }, ref) => (
    <h3
      ref={ref}
      className={cn('text-lg font-semibold leading-tight text-slate-900', className)}
      {...props}
    />
  )
);
CardTitle.displayName = 'CardTitle';

// Card Description
const CardDescription = React.forwardRef<HTMLParagraphElement, React.HTMLAttributes<HTMLParagraphElement>>(
  ({ className, ...props }, ref) => (
    <p
      ref={ref}
      className={cn('text-sm text-slate-500', className)}
      {...props}
    />
  )
);
CardDescription.displayName = 'CardDescription';

// Card Content
const CardContent = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div ref={ref} className={cn('', className)} {...props} />
  )
);
CardContent.displayName = 'CardContent';

// Card Footer
const CardFooter = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div
      ref={ref}
      className={cn('flex items-center gap-3 pt-4 border-t border-slate-100 mt-4', className)}
      {...props}
    />
  )
);
CardFooter.displayName = 'CardFooter';

export { Card, CardHeader, CardTitle, CardDescription, CardContent, CardFooter };
