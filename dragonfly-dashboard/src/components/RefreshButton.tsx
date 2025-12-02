import React from 'react';

interface RefreshButtonProps {
  onClick: () => void | Promise<void>;
  isLoading: boolean;
  hasData: boolean;
  label?: string;
  className?: string;
  disabled?: boolean;
}

const BASE_CLASSES =
  'inline-flex items-center gap-2 rounded-full border border-slate-300 bg-white px-4 py-2 text-xs font-semibold uppercase tracking-wide text-slate-700 shadow-sm transition hover:bg-slate-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-indigo-500 disabled:cursor-not-allowed disabled:opacity-60';

const RefreshButton: React.FC<RefreshButtonProps> = ({
  onClick,
  isLoading,
  hasData,
  label = 'Refresh',
  className = '',
  disabled = false,
}) => {
  const showSpinner = isLoading && hasData;
  const isDisabled = disabled || (isLoading && !hasData);

  return (
    <button type="button" onClick={onClick} disabled={isDisabled} className={[BASE_CLASSES, className].join(' ').trim()}>
      {showSpinner ? (
        <span className="inline-flex items-center gap-2">
          <span
            aria-hidden="true"
            className="inline-flex h-3.5 w-3.5 animate-spin rounded-full border-2 border-slate-300 border-t-transparent"
          />
          <span>Refreshing</span>
        </span>
      ) : (
        label
      )}
    </button>
  );
};

export default RefreshButton;
