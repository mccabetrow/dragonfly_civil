import React from 'react';
import { isDemoMode } from '../config';

const DemoBanner: React.FC = () => {
  if (!isDemoMode) {
    return null;
  }

  return (
    <div className="border-b border-blue-100 bg-blue-50 text-blue-800">
      <div className="mx-auto flex max-w-7xl flex-col items-center justify-center gap-1 px-4 py-2 text-sm text-center sm:flex-row sm:gap-2 sm:px-6 lg:px-8">
        <span className="inline-flex h-2 w-2 rounded-full bg-blue-400" aria-hidden="true" />
        <span className="font-semibold tracking-tight">You are viewing Dragonfly Civil in demo mode.</span>
        <span className="text-xs text-blue-700">
          All records are sample judgments. Real plaintiffs will see their actual cases and agency responses here.
        </span>
      </div>
    </div>
  );
};

export default DemoBanner;
