import React, { useState, useRef, useEffect } from 'react';
import { HelpCircle } from 'lucide-react';

export interface HelpTooltipProps {
  text: string;
  className?: string;
}

/**
 * A small "?" icon that shows a tooltip on hover/focus.
 * Used to provide inline help for mom without cluttering the UI.
 */
const HelpTooltip: React.FC<HelpTooltipProps> = ({ text, className = '' }) => {
  const [isVisible, setIsVisible] = useState(false);
  const [position, setPosition] = useState<'top' | 'bottom'>('top');
  const buttonRef = useRef<HTMLButtonElement>(null);
  const tooltipRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (isVisible && buttonRef.current) {
      const rect = buttonRef.current.getBoundingClientRect();
      // If there's not enough space above, show tooltip below
      const spaceAbove = rect.top;
      setPosition(spaceAbove < 100 ? 'bottom' : 'top');
    }
  }, [isVisible]);

  return (
    <span className={['relative inline-flex items-center', className].filter(Boolean).join(' ')}>
      <button
        ref={buttonRef}
        type="button"
        className="ml-1 inline-flex items-center justify-center rounded-full p-0.5 text-slate-400 transition-colors hover:text-slate-600 focus:outline-none focus:ring-2 focus:ring-blue-500/40"
        onMouseEnter={() => setIsVisible(true)}
        onMouseLeave={() => setIsVisible(false)}
        onFocus={() => setIsVisible(true)}
        onBlur={() => setIsVisible(false)}
        aria-label="Help"
      >
        <HelpCircle className="h-4 w-4" aria-hidden="true" />
      </button>
      {isVisible && (
        <div
          ref={tooltipRef}
          role="tooltip"
          className={[
            'absolute z-50 w-56 rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs leading-relaxed text-slate-600 shadow-lg',
            position === 'top' ? 'bottom-full left-1/2 mb-2 -translate-x-1/2' : 'left-1/2 top-full mt-2 -translate-x-1/2',
          ].join(' ')}
        >
          {text}
          <span
            className={[
              'absolute left-1/2 h-2 w-2 -translate-x-1/2 rotate-45 border border-slate-200 bg-white',
              position === 'top' ? '-bottom-1 border-l-0 border-t-0' : '-top-1 border-b-0 border-r-0',
            ].join(' ')}
            aria-hidden="true"
          />
        </div>
      )}
    </span>
  );
};

export default HelpTooltip;
