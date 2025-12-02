/**
 * CommandPalette - Cmd/Ctrl+K quick navigation
 * 
 * Ultra-fast keyboard-driven navigation for power users.
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import type { FC } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import {
  LayoutDashboard,
  Headphones,
  Target,
  Briefcase,
  Settings,
  HelpCircle,
  Search,
  Command,
  ArrowRight,
} from 'lucide-react';
import { cn } from '../../lib/design-tokens';

interface CommandItem {
  id: string;
  label: string;
  description?: string;
  icon: typeof LayoutDashboard;
  action: () => void;
  keywords?: string[];
}

interface CommandPaletteProps {
  className?: string;
}

const CommandPalette: FC<CommandPaletteProps> = ({ className }) => {
  const [isOpen, setIsOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [selectedIndex, setSelectedIndex] = useState(0);
  const navigate = useNavigate();
  const location = useLocation();

  // Define all commands
  const commands = useMemo<CommandItem[]>(() => [
    {
      id: 'overview',
      label: 'Go to Overview',
      description: 'Daily snapshot and key metrics',
      icon: LayoutDashboard,
      action: () => navigate('/overview'),
      keywords: ['dashboard', 'home', 'metrics', 'summary'],
    },
    {
      id: 'ops',
      label: 'Go to Ops Console',
      description: 'Call queue and daily tasks',
      icon: Headphones,
      action: () => navigate('/ops'),
      keywords: ['calls', 'queue', 'tasks', 'operations', 'mom'],
    },
    {
      id: 'collectability',
      label: 'Go to Collectability',
      description: 'Tier-based case prioritization',
      icon: Target,
      action: () => navigate('/collectability'),
      keywords: ['tiers', 'priority', 'score', 'ranking'],
    },
    {
      id: 'cases',
      label: 'Go to Cases',
      description: 'Browse and manage all judgments',
      icon: Briefcase,
      action: () => navigate('/cases'),
      keywords: ['judgments', 'browse', 'search', 'debtors'],
    },
    {
      id: 'settings',
      label: 'Go to Settings',
      description: 'Configure preferences',
      icon: Settings,
      action: () => navigate('/settings'),
      keywords: ['preferences', 'config', 'options'],
    },
    {
      id: 'help',
      label: 'Go to Help',
      description: 'Documentation and guides',
      icon: HelpCircle,
      action: () => navigate('/help'),
      keywords: ['docs', 'documentation', 'guide', 'support'],
    },
  ], [navigate]);

  // Filter commands based on query
  const filteredCommands = useMemo(() => {
    if (!query.trim()) return commands;
    
    const q = query.toLowerCase();
    return commands.filter((cmd) => {
      const matchLabel = cmd.label.toLowerCase().includes(q);
      const matchDesc = cmd.description?.toLowerCase().includes(q);
      const matchKeywords = cmd.keywords?.some((kw) => kw.includes(q));
      return matchLabel || matchDesc || matchKeywords;
    });
  }, [commands, query]);

  // Reset selection when filter changes
  useEffect(() => {
    setSelectedIndex(0);
  }, [filteredCommands.length]);

  // Global keyboard shortcut
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Cmd/Ctrl + K to open
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        setIsOpen(true);
        setQuery('');
        setSelectedIndex(0);
      }
      
      // Escape to close
      if (e.key === 'Escape' && isOpen) {
        e.preventDefault();
        setIsOpen(false);
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen]);

  // Close on location change
  useEffect(() => {
    setIsOpen(false);
  }, [location.pathname]);

  // Handle keyboard navigation within palette
  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    switch (e.key) {
      case 'ArrowDown':
        e.preventDefault();
        setSelectedIndex((prev) => 
          prev < filteredCommands.length - 1 ? prev + 1 : 0
        );
        break;
      case 'ArrowUp':
        e.preventDefault();
        setSelectedIndex((prev) => 
          prev > 0 ? prev - 1 : filteredCommands.length - 1
        );
        break;
      case 'Enter':
        e.preventDefault();
        if (filteredCommands[selectedIndex]) {
          filteredCommands[selectedIndex].action();
          setIsOpen(false);
        }
        break;
    }
  }, [filteredCommands, selectedIndex]);

  const executeCommand = useCallback((cmd: CommandItem) => {
    cmd.action();
    setIsOpen(false);
  }, []);

  if (!isOpen) {
    return null;
  }

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 z-50 bg-slate-900/50 backdrop-blur-sm animate-fade-in"
        onClick={() => setIsOpen(false)}
        aria-hidden="true"
      />

      {/* Palette */}
      <div
        className={cn(
          'fixed left-1/2 top-[20%] z-50 w-full max-w-lg -translate-x-1/2',
          'rounded-2xl border border-slate-200 bg-white shadow-2xl',
          'animate-scale-in',
          className
        )}
        role="dialog"
        aria-modal="true"
        aria-label="Command palette"
      >
        {/* Search input */}
        <div className="flex items-center gap-3 border-b border-slate-100 px-4 py-3">
          <Search className="h-5 w-5 text-slate-400" />
          <input
            type="text"
            placeholder="Search commands..."
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={handleKeyDown}
            className="flex-1 bg-transparent text-sm text-slate-900 placeholder:text-slate-400 focus:outline-none"
            autoFocus
          />
          <kbd className="hidden rounded bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-500 sm:inline">
            esc
          </kbd>
        </div>

        {/* Results */}
        <div className="max-h-80 overflow-y-auto p-2">
          {filteredCommands.length === 0 ? (
            <div className="px-4 py-8 text-center">
              <p className="text-sm text-slate-500">No commands found</p>
              <p className="mt-1 text-xs text-slate-400">Try a different search term</p>
            </div>
          ) : (
            <ul role="listbox">
              {filteredCommands.map((cmd, index) => {
                const Icon = cmd.icon;
                const isSelected = index === selectedIndex;

                return (
                  <li key={cmd.id} role="option" aria-selected={isSelected}>
                    <button
                      type="button"
                      onClick={() => executeCommand(cmd)}
                      onMouseEnter={() => setSelectedIndex(index)}
                      className={cn(
                        'flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left transition-colors',
                        isSelected
                          ? 'bg-blue-50 text-blue-900'
                          : 'text-slate-700 hover:bg-slate-50'
                      )}
                    >
                      <span
                        className={cn(
                          'flex h-9 w-9 items-center justify-center rounded-lg',
                          isSelected ? 'bg-blue-100' : 'bg-slate-100'
                        )}
                      >
                        <Icon
                          className={cn(
                            'h-4 w-4',
                            isSelected ? 'text-blue-600' : 'text-slate-500'
                          )}
                        />
                      </span>
                      <div className="flex-1 min-w-0">
                        <p className="font-medium text-sm truncate">{cmd.label}</p>
                        {cmd.description && (
                          <p className="text-xs text-slate-500 truncate">
                            {cmd.description}
                          </p>
                        )}
                      </div>
                      {isSelected && (
                        <ArrowRight className="h-4 w-4 text-blue-500 shrink-0" />
                      )}
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between border-t border-slate-100 px-4 py-2.5 text-xs text-slate-500">
          <div className="flex items-center gap-4">
            <span className="flex items-center gap-1">
              <kbd className="rounded bg-slate-100 px-1.5 py-0.5 font-medium">↑↓</kbd>
              <span>navigate</span>
            </span>
            <span className="flex items-center gap-1">
              <kbd className="rounded bg-slate-100 px-1.5 py-0.5 font-medium">↵</kbd>
              <span>select</span>
            </span>
          </div>
          <span className="flex items-center gap-1">
            <Command className="h-3 w-3" />
            <span>K to open</span>
          </span>
        </div>
      </div>
    </>
  );
};

export default CommandPalette;
