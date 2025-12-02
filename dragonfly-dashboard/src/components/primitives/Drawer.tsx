/**
 * Drawer Component
 * ═══════════════════════════════════════════════════════════════════════════
 * 
 * Bloomberg-style analytics sidebar drawer using Radix Dialog.
 * Slides in from the right with smooth animations.
 */

import * as React from 'react';
import * as DialogPrimitive from '@radix-ui/react-dialog';
import { cn } from '../../lib/tokens';
import { X } from 'lucide-react';

const DrawerRoot = DialogPrimitive.Root;
const DrawerTrigger = DialogPrimitive.Trigger;
const DrawerClose = DialogPrimitive.Close;
const DrawerPortal = DialogPrimitive.Portal;

// Overlay
const DrawerOverlay = React.forwardRef<
  React.ElementRef<typeof DialogPrimitive.Overlay>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Overlay>
>(({ className, ...props }, ref) => (
  <DialogPrimitive.Overlay
    ref={ref}
    className={cn(
      'fixed inset-0 z-50 bg-black/40 backdrop-blur-sm',
      'data-[state=open]:animate-in data-[state=closed]:animate-out',
      'data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0',
      className
    )}
    {...props}
  />
));
DrawerOverlay.displayName = 'DrawerOverlay';

// Main Drawer Content
export interface DrawerContentProps
  extends React.ComponentPropsWithoutRef<typeof DialogPrimitive.Content> {
  /** Side to slide from */
  side?: 'left' | 'right';
  /** Width of the drawer */
  size?: 'sm' | 'md' | 'lg' | 'xl' | 'full';
}

const sizeClasses = {
  sm: 'max-w-sm',
  md: 'max-w-md',
  lg: 'max-w-lg',
  xl: 'max-w-xl',
  full: 'max-w-full',
};

const DrawerContent = React.forwardRef<
  React.ElementRef<typeof DialogPrimitive.Content>,
  DrawerContentProps
>(({ className, side = 'right', size = 'lg', children, ...props }, ref) => (
  <DrawerPortal>
    <DrawerOverlay />
    <DialogPrimitive.Content
      ref={ref}
      className={cn(
        'fixed z-50 h-full bg-white shadow-xl outline-none',
        'flex flex-col',
        // Position
        side === 'right' ? 'right-0 top-0' : 'left-0 top-0',
        // Size
        'w-full',
        sizeClasses[size],
        // Animations
        'data-[state=open]:animate-in data-[state=closed]:animate-out',
        side === 'right'
          ? 'data-[state=closed]:slide-out-to-right data-[state=open]:slide-in-from-right'
          : 'data-[state=closed]:slide-out-to-left data-[state=open]:slide-in-from-left',
        'duration-300 ease-out',
        className
      )}
      {...props}
    >
      {children}
    </DialogPrimitive.Content>
  </DrawerPortal>
));
DrawerContent.displayName = 'DrawerContent';

// Drawer Header
export interface DrawerHeaderProps extends React.HTMLAttributes<HTMLDivElement> {
  /** Show close button */
  showClose?: boolean;
}

const DrawerHeader = React.forwardRef<HTMLDivElement, DrawerHeaderProps>(
  ({ className, showClose = true, children, ...props }, ref) => (
    <div
      ref={ref}
      className={cn(
        'flex items-center justify-between gap-4 px-6 py-4 border-b border-slate-200 shrink-0',
        className
      )}
      {...props}
    >
      <div className="flex-1 min-w-0">{children}</div>
      {showClose && (
        <DrawerClose asChild>
          <button
            className={cn(
              'flex items-center justify-center h-8 w-8 rounded-lg',
              'text-slate-400 hover:text-slate-600 hover:bg-slate-100',
              'transition-colors outline-none focus-visible:ring-2 focus-visible:ring-indigo-500'
            )}
          >
            <X className="h-4 w-4" />
            <span className="sr-only">Close</span>
          </button>
        </DrawerClose>
      )}
    </div>
  )
);
DrawerHeader.displayName = 'DrawerHeader';

// Drawer Title
const DrawerTitle = React.forwardRef<
  React.ElementRef<typeof DialogPrimitive.Title>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Title>
>(({ className, ...props }, ref) => (
  <DialogPrimitive.Title
    ref={ref}
    className={cn('text-lg font-semibold text-slate-900 truncate', className)}
    {...props}
  />
));
DrawerTitle.displayName = 'DrawerTitle';

// Drawer Description
const DrawerDescription = React.forwardRef<
  React.ElementRef<typeof DialogPrimitive.Description>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Description>
>(({ className, ...props }, ref) => (
  <DialogPrimitive.Description
    ref={ref}
    className={cn('text-sm text-slate-500 mt-1', className)}
    {...props}
  />
));
DrawerDescription.displayName = 'DrawerDescription';

// Drawer Body (scrollable content area)
const DrawerBody = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div
      ref={ref}
      className={cn('flex-1 overflow-y-auto px-6 py-4', className)}
      {...props}
    />
  )
);
DrawerBody.displayName = 'DrawerBody';

// Drawer Footer
const DrawerFooter = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div
      ref={ref}
      className={cn(
        'flex items-center justify-end gap-3 px-6 py-4 border-t border-slate-200 bg-slate-50 shrink-0',
        className
      )}
      {...props}
    />
  )
);
DrawerFooter.displayName = 'DrawerFooter';

// Drawer Section (for organizing content)
export interface DrawerSectionProps extends React.HTMLAttributes<HTMLDivElement> {
  title?: string;
  description?: string;
}

const DrawerSection = React.forwardRef<HTMLDivElement, DrawerSectionProps>(
  ({ title, description, className, children, ...props }, ref) => (
    <div ref={ref} className={cn('py-4', className)} {...props}>
      {title && (
        <div className="mb-3">
          <h3 className="text-sm font-medium text-slate-900">{title}</h3>
          {description && (
            <p className="text-xs text-slate-500 mt-0.5">{description}</p>
          )}
        </div>
      )}
      {children}
    </div>
  )
);
DrawerSection.displayName = 'DrawerSection';

export {
  DrawerRoot as Drawer,
  DrawerTrigger,
  DrawerContent,
  DrawerHeader,
  DrawerTitle,
  DrawerDescription,
  DrawerBody,
  DrawerFooter,
  DrawerSection,
  DrawerClose,
};
