import { type FC, type ReactNode } from 'react';
import { cn } from '../../lib/design-tokens';

// ═══════════════════════════════════════════════════════════════════════════
// CARD COMPONENT
// ═══════════════════════════════════════════════════════════════════════════

export type CardVariant = 'default' | 'elevated' | 'outlined' | 'ghost' | 'interactive';

export interface CardProps {
  children: ReactNode;
  className?: string;
  /** Card visual variant */
  variant?: CardVariant;
  /** @deprecated Use variant="interactive" instead */
  interactive?: boolean;
  onClick?: () => void;
  as?: 'div' | 'article' | 'section';
}

const variantStyles: Record<CardVariant, string> = {
  default: 'border border-slate-200/80 bg-white shadow-[0_1px_3px_0_rgb(0_0_0/0.04),0_1px_2px_-1px_rgb(0_0_0/0.04)]',
  elevated: 'border-0 bg-white shadow-lg shadow-slate-200/50',
  outlined: 'border-2 border-slate-200 bg-transparent shadow-none',
  ghost: 'border-0 bg-slate-50/50 shadow-none',
  interactive: 'border border-slate-200/80 bg-white shadow-[0_1px_3px_0_rgb(0_0_0/0.04)] cursor-pointer hover:shadow-[0_4px_12px_0_rgb(0_0_0/0.08)] hover:border-slate-300 hover:-translate-y-0.5 transition-all duration-200 active:scale-[0.99]',
};

export const Card: FC<CardProps> = ({
  children,
  className,
  variant = 'default',
  interactive = false,
  onClick,
  as: Component = 'div',
}) => {
  // Support legacy interactive prop
  const effectiveVariant = interactive ? 'interactive' : variant;
  const isClickable = effectiveVariant === 'interactive' || !!onClick;

  return (
    <Component
      className={cn(
        'rounded-2xl',
        variantStyles[effectiveVariant],
        isClickable && effectiveVariant !== 'interactive' && 'cursor-pointer hover:shadow-md hover:border-slate-300 hover:-translate-y-0.5 transition-all duration-200',
        className
      )}
      onClick={onClick}
      role={isClickable ? 'button' : undefined}
      tabIndex={isClickable ? 0 : undefined}
    >
      {children}
    </Component>
  );
};

// ═══════════════════════════════════════════════════════════════════════════
// CARD HEADER
// ═══════════════════════════════════════════════════════════════════════════

export interface CardHeaderProps {
  children: ReactNode;
  className?: string;
  action?: ReactNode;
}

export const CardHeader: FC<CardHeaderProps> = ({ children, className, action }) => {
  return (
    <div className={cn('flex items-start justify-between gap-4 p-6 pb-0', className)}>
      <div className="flex-1">{children}</div>
      {action && <div className="flex-shrink-0">{action}</div>}
    </div>
  );
};

// ═══════════════════════════════════════════════════════════════════════════
// CARD TITLE
// ═══════════════════════════════════════════════════════════════════════════

export interface CardTitleProps {
  children: ReactNode;
  className?: string;
  as?: 'h1' | 'h2' | 'h3' | 'h4';
}

export const CardTitle: FC<CardTitleProps> = ({
  children,
  className,
  as: Component = 'h2',
}) => {
  return (
    <Component className={cn('text-lg font-semibold text-slate-900', className)}>
      {children}
    </Component>
  );
};

// ═══════════════════════════════════════════════════════════════════════════
// CARD DESCRIPTION
// ═══════════════════════════════════════════════════════════════════════════

export interface CardDescriptionProps {
  children: ReactNode;
  className?: string;
}

export const CardDescription: FC<CardDescriptionProps> = ({ children, className }) => {
  return (
    <p className={cn('mt-1 text-sm text-slate-600', className)}>
      {children}
    </p>
  );
};

// ═══════════════════════════════════════════════════════════════════════════
// CARD CONTENT
// ═══════════════════════════════════════════════════════════════════════════

export interface CardContentProps {
  children: ReactNode;
  className?: string;
}

export const CardContent: FC<CardContentProps> = ({ children, className }) => {
  return <div className={cn('p-6', className)}>{children}</div>;
};

// ═══════════════════════════════════════════════════════════════════════════
// CARD FOOTER
// ═══════════════════════════════════════════════════════════════════════════

export interface CardFooterProps {
  children: ReactNode;
  className?: string;
}

export const CardFooter: FC<CardFooterProps> = ({ children, className }) => {
  return (
    <div className={cn('border-t border-slate-100 px-6 py-4', className)}>
      {children}
    </div>
  );
};

export default Card;
