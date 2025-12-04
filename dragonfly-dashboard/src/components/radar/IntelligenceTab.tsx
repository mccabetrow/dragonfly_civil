/**
 * IntelligenceTab
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * Tab content showing the intelligence graph entities, relationships,
 * and enforcement event timeline.
 */
import React, { useMemo } from 'react';
import {
  AlertCircle,
  User,
  Building2,
  Scale,
  MapPin,
  Link2,
  Users,
  Network,
  History,
} from 'lucide-react';
import { Card, CardContent } from '../primitives';
import { useIntelligence, type IntelligenceEntity } from '../../hooks/useIntelligence';
import { cn } from '../../lib/tokens';
import { EntityTimeline } from './EntityTimeline';

// ═══════════════════════════════════════════════════════════════════════════
// TYPES
// ═══════════════════════════════════════════════════════════════════════════

interface IntelligenceTabProps {
  judgmentId: number;
}

// ═══════════════════════════════════════════════════════════════════════════
// HELPERS
// ═══════════════════════════════════════════════════════════════════════════

const entityTypeConfig: Record<
  IntelligenceEntity['type'],
  { icon: React.ElementType; label: string; color: string }
> = {
  person: {
    icon: User,
    label: 'Person',
    color: 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400',
  },
  company: {
    icon: Building2,
    label: 'Company',
    color: 'bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400',
  },
  court: {
    icon: Scale,
    label: 'Court',
    color: 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400',
  },
  address: {
    icon: MapPin,
    label: 'Address',
    color: 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400',
  },
  other: {
    icon: Link2,
    label: 'Other',
    color: 'bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-400',
  },
};

// ═══════════════════════════════════════════════════════════════════════════
// COMPONENTS
// ═══════════════════════════════════════════════════════════════════════════

interface EntityBadgeProps {
  type: IntelligenceEntity['type'];
}

const EntityBadge: React.FC<EntityBadgeProps> = ({ type }) => {
  const config = entityTypeConfig[type] || entityTypeConfig.other;
  const Icon = config.icon;

  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium',
        config.color
      )}
    >
      <Icon className="h-3 w-3" />
      {config.label}
    </span>
  );
};

interface EntityCardProps {
  entity: IntelligenceEntity;
  relationContext?: string;
}

const EntityCard: React.FC<EntityCardProps> = ({ entity, relationContext }) => {
  const config = entityTypeConfig[entity.type] || entityTypeConfig.other;
  const Icon = config.icon;

  return (
    <div className="flex items-start gap-3 p-3 rounded-lg bg-muted/30 hover:bg-muted/50 transition-colors">
      <div
        className={cn(
          'flex-shrink-0 w-8 h-8 rounded-lg flex items-center justify-center',
          config.color
        )}
      >
        <Icon className="h-4 w-4" />
      </div>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium truncate">{entity.rawName}</p>
        <div className="flex items-center gap-2 mt-1">
          <EntityBadge type={entity.type} />
          {relationContext && (
            <span className="text-xs text-muted-foreground">{relationContext}</span>
          )}
        </div>
      </div>
    </div>
  );
};

const LoadingState: React.FC = () => (
  <div className="space-y-4 animate-pulse">
    {[1, 2, 3].map((i) => (
      <div key={i} className="flex items-start gap-3 p-3 rounded-lg bg-gray-100 dark:bg-gray-800">
        <div className="w-8 h-8 rounded-lg bg-gray-200 dark:bg-gray-700" />
        <div className="flex-1 space-y-2">
          <div className="h-4 w-32 bg-gray-200 dark:bg-gray-700 rounded" />
          <div className="h-3 w-20 bg-gray-200 dark:bg-gray-700 rounded" />
        </div>
      </div>
    ))}
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
      <Network className="h-6 w-6 text-gray-400" />
    </div>
    <p className="text-sm font-medium text-muted-foreground">No Intelligence Data</p>
    <p className="text-xs text-muted-foreground mt-1">
      Entity graph will populate after enrichment
    </p>
  </div>
);

// ═══════════════════════════════════════════════════════════════════════════
// MAIN COMPONENT
// ═══════════════════════════════════════════════════════════════════════════

export const IntelligenceTab: React.FC<IntelligenceTabProps> = ({ judgmentId }) => {
  const { data, loading, error } = useIntelligence(judgmentId);

  // Group entities by type and add relationship context
  const groupedEntities = useMemo(() => {
    if (!data) return null;

    const groups: Record<string, { entity: IntelligenceEntity; context?: string }[]> = {
      defendants: [],
      plaintiffs: [],
      courts: [],
      addresses: [],
      other: [],
    };

    // Determine role from relationships
    const entityRoles = new Map<string, string>();
    for (const rel of data.relationships) {
      if (rel.relation === 'defendant_in') {
        entityRoles.set(rel.sourceEntityId, 'defendant');
      } else if (rel.relation === 'plaintiff_in') {
        entityRoles.set(rel.sourceEntityId, 'plaintiff');
      }
    }

    // Group entities
    for (const entity of data.entities) {
      const role = entityRoles.get(entity.id);

      if (entity.type === 'court') {
        groups.courts.push({ entity });
      } else if (entity.type === 'address') {
        groups.addresses.push({ entity });
      } else if (role === 'defendant') {
        groups.defendants.push({ entity, context: 'Defendant' });
      } else if (role === 'plaintiff') {
        groups.plaintiffs.push({ entity, context: 'Plaintiff' });
      } else {
        groups.other.push({ entity });
      }
    }

    return groups;
  }, [data]);

  if (loading) {
    return <LoadingState />;
  }

  if (error) {
    return <ErrorState message={error} />;
  }

  if (!data || data.entities.length === 0) {
    return <EmptyState />;
  }

  return (
    <div className="space-y-6">
      {/* Summary Stats */}
      <Card>
        <CardContent className="p-4">
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-2">
              <Users className="h-4 w-4 text-muted-foreground" />
              <span className="text-sm">
                <span className="font-bold">{data.entities.length}</span> entities
              </span>
            </div>
            <div className="flex items-center gap-2">
              <Link2 className="h-4 w-4 text-muted-foreground" />
              <span className="text-sm">
                <span className="font-bold">{data.relationships.length}</span> relationships
              </span>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Defendants */}
      {groupedEntities?.defendants && groupedEntities.defendants.length > 0 && (
        <div className="space-y-2">
          <h4 className="text-sm font-semibold text-muted-foreground uppercase tracking-wider flex items-center gap-2">
            <User className="h-4 w-4" />
            Defendants
          </h4>
          <div className="space-y-2">
            {groupedEntities.defendants.map(({ entity, context }) => (
              <EntityCard key={entity.id} entity={entity} relationContext={context} />
            ))}
          </div>
        </div>
      )}

      {/* Plaintiffs */}
      {groupedEntities?.plaintiffs && groupedEntities.plaintiffs.length > 0 && (
        <div className="space-y-2">
          <h4 className="text-sm font-semibold text-muted-foreground uppercase tracking-wider flex items-center gap-2">
            <User className="h-4 w-4" />
            Plaintiffs
          </h4>
          <div className="space-y-2">
            {groupedEntities.plaintiffs.map(({ entity, context }) => (
              <EntityCard key={entity.id} entity={entity} relationContext={context} />
            ))}
          </div>
        </div>
      )}

      {/* Courts */}
      {groupedEntities?.courts && groupedEntities.courts.length > 0 && (
        <div className="space-y-2">
          <h4 className="text-sm font-semibold text-muted-foreground uppercase tracking-wider flex items-center gap-2">
            <Scale className="h-4 w-4" />
            Courts
          </h4>
          <div className="space-y-2">
            {groupedEntities.courts.map(({ entity }) => (
              <EntityCard key={entity.id} entity={entity} />
            ))}
          </div>
        </div>
      )}

      {/* Addresses */}
      {groupedEntities?.addresses && groupedEntities.addresses.length > 0 && (
        <div className="space-y-2">
          <h4 className="text-sm font-semibold text-muted-foreground uppercase tracking-wider flex items-center gap-2">
            <MapPin className="h-4 w-4" />
            Addresses
          </h4>
          <div className="space-y-2">
            {groupedEntities.addresses.map(({ entity }) => (
              <EntityCard key={entity.id} entity={entity} />
            ))}
          </div>
        </div>
      )}

      {/* Other */}
      {groupedEntities?.other && groupedEntities.other.length > 0 && (
        <div className="space-y-2">
          <h4 className="text-sm font-semibold text-muted-foreground uppercase tracking-wider flex items-center gap-2">
            <Link2 className="h-4 w-4" />
            Other Entities
          </h4>
          <div className="space-y-2">
            {groupedEntities.other.map(({ entity }) => (
              <EntityCard key={entity.id} entity={entity} />
            ))}
          </div>
        </div>
      )}

      {/* Event Timeline */}
      <div className="space-y-2">
        <h4 className="text-sm font-semibold text-muted-foreground uppercase tracking-wider flex items-center gap-2">
          <History className="h-4 w-4" />
          Enforcement Timeline
        </h4>
        <EntityTimeline judgmentId={judgmentId} />
      </div>
    </div>
  );
};

export default IntelligenceTab;
