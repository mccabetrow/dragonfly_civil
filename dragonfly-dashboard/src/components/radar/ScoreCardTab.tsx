/**
 * ScoreCardTab
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * Tab content showing the explainable score breakdown for a judgment.
 * Uses Tremor-style metrics and progress bars.
 */
import React from 'react';
import { AlertCircle, TrendingUp, Building2, Clock, Landmark } from 'lucide-react';
import { Card, CardContent } from '../primitives';
import { useScoreCard, SCORE_LIMITS, type ScoreCardData } from '../../hooks/useScoreCard';
import { cn } from '../../lib/tokens';

// ═══════════════════════════════════════════════════════════════════════════
// TYPES
// ═══════════════════════════════════════════════════════════════════════════

interface ScoreCardTabProps {
  judgmentId: number;
}

// ═══════════════════════════════════════════════════════════════════════════
// HELPERS
// ═══════════════════════════════════════════════════════════════════════════

function getScoreColor(score: number | null, maxScore: number = 100): string {
  if (score === null) return 'text-gray-400';
  const percentage = (score / maxScore) * 100;
  if (percentage >= 70) return 'text-green-600 dark:text-green-400';
  if (percentage >= 40) return 'text-amber-600 dark:text-amber-400';
  return 'text-gray-500 dark:text-gray-400';
}

function getProgressColor(score: number, maxScore: number): string {
  const percentage = (score / maxScore) * 100;
  if (percentage >= 70) return 'bg-green-500';
  if (percentage >= 40) return 'bg-amber-500';
  return 'bg-gray-400';
}

function getProgressBgColor(score: number, maxScore: number): string {
  const percentage = (score / maxScore) * 100;
  if (percentage >= 70) return 'bg-green-100 dark:bg-green-900/30';
  if (percentage >= 40) return 'bg-amber-100 dark:bg-amber-900/30';
  return 'bg-gray-100 dark:bg-gray-800';
}

// ═══════════════════════════════════════════════════════════════════════════
// COMPONENTS
// ═══════════════════════════════════════════════════════════════════════════

interface ScoreBarProps {
  label: string;
  icon: React.ElementType;
  score: number;
  maxScore: number;
  description: string;
}

const ScoreBar: React.FC<ScoreBarProps> = ({
  label,
  icon: Icon,
  score,
  maxScore,
  description,
}) => {
  const percentage = (score / maxScore) * 100;
  const progressColor = getProgressColor(score, maxScore);
  const bgColor = getProgressBgColor(score, maxScore);

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Icon className="h-4 w-4 text-muted-foreground" />
          <span className="text-sm font-medium">{label}</span>
        </div>
        <span className="text-sm font-bold tabular-nums">
          {score}/{maxScore}
        </span>
      </div>
      <div className={cn('h-2 rounded-full overflow-hidden', bgColor)}>
        <div
          className={cn('h-full rounded-full transition-all duration-500', progressColor)}
          style={{ width: `${percentage}%` }}
        />
      </div>
      <p className="text-xs text-muted-foreground">{description}</p>
    </div>
  );
};

const LoadingState: React.FC = () => (
  <div className="space-y-4 animate-pulse">
    <div className="h-24 bg-gray-100 dark:bg-gray-800 rounded-lg" />
    <div className="space-y-3">
      {[1, 2, 3, 4].map((i) => (
        <div key={i} className="space-y-2">
          <div className="h-4 w-32 bg-gray-100 dark:bg-gray-800 rounded" />
          <div className="h-2 bg-gray-100 dark:bg-gray-800 rounded-full" />
        </div>
      ))}
    </div>
  </div>
);

const ErrorState: React.FC<{ message: string }> = ({ message }) => (
  <div className="flex flex-col items-center justify-center py-8 text-center">
    <AlertCircle className="h-8 w-8 text-red-500 mb-2" />
    <p className="text-sm text-muted-foreground">{message}</p>
  </div>
);

const EmptyState: React.FC = () => (
  <div className="flex flex-col items-center justify-center py-8 text-center">
    <div className="h-12 w-12 rounded-full bg-gray-100 dark:bg-gray-800 flex items-center justify-center mb-3">
      <TrendingUp className="h-6 w-6 text-gray-400" />
    </div>
    <p className="text-sm font-medium text-muted-foreground">No Score Data</p>
    <p className="text-xs text-muted-foreground mt-1">
      This judgment hasn't been scored yet
    </p>
  </div>
);

const ScoreCardContent: React.FC<{ data: ScoreCardData }> = ({ data }) => (
  <div className="space-y-6">
    {/* Big Total Score */}
    <Card className="border-2">
      <CardContent className="p-6">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm text-muted-foreground">Total Collectability Score</p>
            <p
              className={cn(
                'text-4xl font-bold tabular-nums mt-1',
                getScoreColor(data.totalScore)
              )}
            >
              {data.totalScore ?? '—'}
              <span className="text-lg text-muted-foreground font-normal">/100</span>
            </p>
          </div>
          <div
            className={cn(
              'h-16 w-16 rounded-full flex items-center justify-center',
              data.totalScore !== null && data.totalScore >= 70
                ? 'bg-green-100 dark:bg-green-900/30'
                : data.totalScore !== null && data.totalScore >= 40
                  ? 'bg-amber-100 dark:bg-amber-900/30'
                  : 'bg-gray-100 dark:bg-gray-800'
            )}
          >
            <TrendingUp
              className={cn(
                'h-8 w-8',
                getScoreColor(data.totalScore)
              )}
            />
          </div>
        </div>
        {!data.breakdownMatchesTotal && data.totalScore !== null && (
          <p className="text-xs text-amber-600 mt-3 flex items-center gap-1">
            <AlertCircle className="h-3 w-3" />
            Breakdown sum ({data.breakdownSum}) differs from total
          </p>
        )}
      </CardContent>
    </Card>

    {/* Score Breakdown Bars */}
    <div className="space-y-5">
      <h4 className="text-sm font-semibold text-muted-foreground uppercase tracking-wider">
        Score Breakdown
      </h4>

      <ScoreBar
        label="Employment"
        icon={Building2}
        score={data.scoreEmployment}
        maxScore={SCORE_LIMITS.employment}
        description="Defendant's employment status and income signals"
      />

      <ScoreBar
        label="Assets"
        icon={Landmark}
        score={data.scoreAssets}
        maxScore={SCORE_LIMITS.assets}
        description="Known real property, vehicles, and financial accounts"
      />

      <ScoreBar
        label="Recency"
        icon={Clock}
        score={data.scoreRecency}
        maxScore={SCORE_LIMITS.recency}
        description="Time since judgment — fresher cases score higher"
      />

      <ScoreBar
        label="Banking"
        icon={Landmark}
        score={data.scoreBanking}
        maxScore={SCORE_LIMITS.banking}
        description="Known bank accounts and financial institution links"
      />
    </div>

    {/* Legend */}
    <div className="pt-4 border-t">
      <p className="text-xs text-muted-foreground mb-2">Score Interpretation:</p>
      <div className="flex flex-wrap gap-3 text-xs">
        <span className="flex items-center gap-1">
          <span className="w-2 h-2 rounded-full bg-green-500" />
          70+ High confidence
        </span>
        <span className="flex items-center gap-1">
          <span className="w-2 h-2 rounded-full bg-amber-500" />
          40-69 Medium
        </span>
        <span className="flex items-center gap-1">
          <span className="w-2 h-2 rounded-full bg-gray-400" />
          0-39 Low
        </span>
      </div>
    </div>
  </div>
);

// ═══════════════════════════════════════════════════════════════════════════
// MAIN COMPONENT
// ═══════════════════════════════════════════════════════════════════════════

export const ScoreCardTab: React.FC<ScoreCardTabProps> = ({ judgmentId }) => {
  const { data, loading, error } = useScoreCard(judgmentId);

  if (loading) {
    return <LoadingState />;
  }

  if (error) {
    return <ErrorState message={error} />;
  }

  if (!data) {
    return <EmptyState />;
  }

  return <ScoreCardContent data={data} />;
};

export default ScoreCardTab;
