import React from 'react';

interface InlineSpinnerProps {
  label?: string;
}

export const InlineSpinner: React.FC<InlineSpinnerProps> = ({ label }) => (
  <span className="inline-flex items-center gap-2 text-xs font-medium text-blue-600">
    <span className="inline-flex h-3.5 w-3.5 animate-spin rounded-full border-2 border-blue-300 border-t-transparent" />
    {label}
  </span>
);
