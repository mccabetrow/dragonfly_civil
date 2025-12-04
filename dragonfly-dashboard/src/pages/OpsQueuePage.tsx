/**
 * OpsQueuePage
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * Stub page for viewing the enrichment job queue.
 * Will be expanded to show job details, retry failed jobs, etc.
 */
import React from 'react';
import { ListChecks, ArrowLeft, Clock, RefreshCw } from 'lucide-react';
import { Link } from 'react-router-dom';
import { Card, CardContent, CardHeader, CardTitle, Button } from '../components/primitives';
import { useRefreshBus } from '../context/RefreshContext';
import { cn } from '../lib/design-tokens';

const OpsQueuePage: React.FC = () => {
  const { triggerRefresh, isRefreshing } = useRefreshBus();

  return (
    <div className="space-y-6 p-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <Link
              to="/ops"
              className="text-muted-foreground hover:text-foreground transition-colors"
            >
              <ArrowLeft className="h-4 w-4" />
            </Link>
            <h1 className="text-2xl font-bold tracking-tight flex items-center gap-2">
              <ListChecks className="h-6 w-6 text-primary" />
              Enrichment Queue
            </h1>
          </div>
          <p className="text-sm text-muted-foreground">
            Monitor and manage enrichment jobs
          </p>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={triggerRefresh}
          disabled={isRefreshing}
          className="gap-2"
        >
          <RefreshCw className={cn('h-4 w-4', isRefreshing && 'animate-spin')} />
          Refresh
        </Button>
      </div>

      {/* Coming Soon Card */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Job Queue Management</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex flex-col items-center justify-center py-12 text-center">
            <div className="rounded-full bg-primary/10 p-4 mb-4">
              <Clock className="h-8 w-8 text-primary" />
            </div>
            <h3 className="text-lg font-semibold mb-2">Coming Soon</h3>
            <p className="text-sm text-muted-foreground max-w-md">
              This page will display the full enrichment job queue with the ability to:
            </p>
            <ul className="mt-4 text-sm text-muted-foreground space-y-1">
              <li>• View all pending, processing, and failed jobs</li>
              <li>• Retry failed jobs individually or in bulk</li>
              <li>• Cancel stuck processing jobs</li>
              <li>• View job execution logs and error details</li>
              <li>• Configure queue priorities and rate limits</li>
            </ul>
          </div>
        </CardContent>
      </Card>

      {/* Quick Stats Placeholder */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <Card>
          <CardContent className="p-4">
            <p className="text-sm font-medium text-muted-foreground">Avg Processing Time</p>
            <p className="text-2xl font-bold mt-1">—</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <p className="text-sm font-medium text-muted-foreground">Jobs Today</p>
            <p className="text-2xl font-bold mt-1">—</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <p className="text-sm font-medium text-muted-foreground">Success Rate</p>
            <p className="text-2xl font-bold mt-1">—</p>
          </CardContent>
        </Card>
      </div>
    </div>
  );
};

export default OpsQueuePage;
