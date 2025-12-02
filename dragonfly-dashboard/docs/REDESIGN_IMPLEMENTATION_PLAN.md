# Dragonfly Civil Dashboard — Billion-Dollar Redesign

## Implementation Blueprint

**Date:** December 2024  
**Version:** 2.0 Enterprise-Grade Redesign  
**Target:** Production-ready, mom-friendly Operations Console

---

## 1. Executive Summary

This document outlines the enterprise-grade redesign of the Dragonfly Civil Operations Console. The redesign introduces a comprehensive design system, reusable component library, improved type safety, and a foundation for scaling to tens of thousands of cases.

### Key Deliverables Created

| Category             | Files Created                    | Purpose                                                 |
| -------------------- | -------------------------------- | ------------------------------------------------------- |
| Design System        | `src/lib/design-tokens.ts`       | Centralized colors, spacing, typography, shadows        |
| UI Primitives        | `src/components/ui/*.tsx`        | Button, Card, Badge, Skeleton, Drawer, Toast, DataTable |
| Dashboard Components | `src/components/dashboard/*.tsx` | MetricCard, TierCard, ActionList                        |
| Layout               | `src/layouts/AppShellNew.tsx`    | Modern responsive shell with mobile nav                 |
| Types                | `src/types/index.ts`             | Centralized TypeScript type definitions                 |
| Utilities            | `src/lib/utils/formatters.ts`    | Unified date, currency, number formatters               |

---

## 2. Architecture Overview

```
dragonfly-dashboard/src/
├── components/
│   ├── ui/                      # Primitive components
│   │   ├── Badge.tsx            # ✅ Tier/status badges
│   │   ├── Button.tsx           # ✅ Primary/secondary/ghost variants
│   │   ├── Card.tsx             # ✅ Card with variant system
│   │   ├── DataTable.tsx        # ✅ Sortable/paginated tables
│   │   ├── Drawer.tsx           # ✅ Accessible slide-out panel
│   │   ├── Skeleton.tsx         # ✅ Loading skeletons
│   │   ├── Toast.tsx            # ✅ Notification toasts
│   │   └── index.ts             # ✅ Barrel exports
│   │
│   ├── dashboard/               # Domain-specific components
│   │   ├── ActionList.tsx       # ✅ Priority action items
│   │   ├── MetricCard.tsx       # ✅ Metrics with trends
│   │   ├── TierCard.tsx         # ✅ Tier summary cards
│   │   └── index.ts             # ✅ Barrel exports
│   │
│   └── (existing components)    # WelcomeCard, StatusMessage, etc.
│
├── layouts/
│   ├── AppShell.tsx             # Current layout (legacy)
│   └── AppShellNew.tsx          # ✅ New enterprise layout
│
├── lib/
│   ├── design-tokens.ts         # ✅ Design system tokens
│   ├── supabaseClient.ts        # Existing Supabase client
│   └── utils/
│       └── formatters.ts        # ✅ Unified formatters
│
├── types/
│   └── index.ts                 # ✅ Centralized types
│
└── pages/                       # (To be migrated)
    ├── OverviewPage.tsx
    ├── CollectabilityPage.tsx
    ├── CasesPage.tsx
    ├── HelpPage.tsx
    └── SettingsPage.tsx
```

---

## 3. Design System Reference

### 3.1 Color Palette

```typescript
// Import from design-tokens.ts
import { colors } from "../lib/design-tokens";

// Brand colors
colors.brand.blue; // Primary blue (#3B82F6)

// Tier colors for collectability
colors.tier.a; // Emerald (high priority)
colors.tier.b; // Amber (medium priority)
colors.tier.c; // Slate (lower priority)

// Semantic colors
colors.semantic.success; // Emerald for success states
colors.semantic.warning; // Amber for warnings
colors.semantic.error; // Rose for errors
colors.semantic.info; // Blue for informational
```

### 3.2 Typography

```typescript
import { typography } from "../lib/design-tokens";

// Font sizes
typography.fontSize.xs; // 12px
typography.fontSize.sm; // 14px
typography.fontSize.base; // 16px
typography.fontSize.lg; // 18px
typography.fontSize.xl; // 20px
typography.fontSize["2xl"]; // 24px
typography.fontSize["3xl"]; // 30px
```

### 3.3 Spacing Scale

```typescript
import { spacing } from "../lib/design-tokens";

// Consistent spacing (in Tailwind units)
spacing[0]; // 0
spacing[1]; // 0.25rem (4px)
spacing[2]; // 0.5rem (8px)
spacing[4]; // 1rem (16px)
spacing[6]; // 1.5rem (24px)
spacing[8]; // 2rem (32px)
```

### 3.4 Helper Functions

```typescript
import { cn, getTierColor } from "../lib/design-tokens";

// Merge class names (replaces clsx/classnames)
cn("base-class", condition && "conditional-class", className);

// Get tier-specific colors
const tierColors = getTierColor("A"); // Returns emerald color set
```

---

## 4. Component Reference

### 4.1 UI Primitives

#### Button

```tsx
import { Button, IconButton } from '../components/ui';

// Variants: primary, secondary, ghost, danger
<Button variant="primary" size="md" onClick={handleClick}>
  Save Changes
</Button>

// With icon
<Button leftIcon={<Plus className="h-4 w-4" />}>
  Add Case
</Button>

// Icon-only button
<IconButton variant="ghost" aria-label="Refresh">
  <RefreshCw className="h-4 w-4" />
</IconButton>
```

#### Card

```tsx
import { Card, CardHeader, CardTitle, CardContent } from "../components/ui";

// Variants: default, elevated, outlined, ghost, interactive
<Card variant="interactive" onClick={handleClick}>
  <CardHeader>
    <CardTitle>Dashboard</CardTitle>
  </CardHeader>
  <CardContent>Content goes here</CardContent>
</Card>;
```

#### Badge

```tsx
import { Badge, TierBadge, StatusBadge } from '../components/ui';

// Variants: default, success, warning, error, info
<Badge variant="success" dot>Active</Badge>

// Tier badge (automatic colors)
<TierBadge tier="A" />  // Green
<TierBadge tier="B" />  // Amber
<TierBadge tier="C" />  // Slate

// Status badge
<StatusBadge status="pending" />
```

#### DataTable

```tsx
import { DataTable, type Column } from "../components/ui";

const columns: Column<CaseRow>[] = [
  { key: "case_number", header: "Case #", sortable: true },
  { key: "defendant_name", header: "Defendant", sortable: true },
  {
    key: "judgment_amount",
    header: "Amount",
    sortable: true,
    render: (row) => formatCurrency(row.judgment_amount),
  },
  {
    key: "tier",
    header: "Tier",
    render: (row) => <TierBadge tier={row.tier} />,
  },
];

<DataTable
  data={cases}
  columns={columns}
  pageSize={10}
  loading={isLoading}
  emptyMessage="No cases found"
  onRowClick={(row) => openCaseDetail(row.case_id)}
/>;
```

### 4.2 Dashboard Components

#### MetricCard

```tsx
import { MetricCard, MetricCardGrid } from "../components/dashboard";

<MetricCardGrid columns={3}>
  <MetricCard
    label="Total Cases"
    value={1234}
    format="number"
    previousValue={1200}
    tooltip="All active and pending cases"
    icon={<Briefcase className="h-5 w-5" />}
  />
  <MetricCard
    label="Portfolio Value"
    value={2500000}
    format="currency"
    trendLabel="12% this month"
    trendDirection="up"
    upIsGood={true}
  />
</MetricCardGrid>;
```

#### TierCard

```tsx
import { TierCard, TierSummaryRow } from '../components/dashboard';

// Full tier card
<TierCard
  tier="A"
  caseCount={45}
  totalValue={1250000}
  countChange={3}
  onClick={() => navigateToTier('A')}
/>

// Compact row layout
<TierSummaryRow
  tiers={[
    { tier: 'A', caseCount: 45, totalValue: 1250000 },
    { tier: 'B', caseCount: 120, totalValue: 3400000 },
    { tier: 'C', caseCount: 210, totalValue: 890000 },
  ]}
  onTierClick={(tier) => navigateToTier(tier)}
/>
```

#### ActionList

```tsx
import { ActionList, type ActionItem } from "../components/dashboard";

const actions: ActionItem[] = [
  {
    id: "1",
    type: "call",
    title: "Follow up with Smith",
    caseNumber: "CV-2024-001234",
    defendant: "John Smith",
    amount: 15000,
    tier: "A",
    dueDate: new Date(),
    urgency: "high",
  },
];

<ActionList
  title="Next Actions"
  items={actions}
  maxItems={5}
  onItemClick={(item) => openCase(item.id)}
  onSeeAll={() => navigateToAllActions()}
/>;
```

---

## 5. Migration Checklist

### Phase 1: Foundation (Completed ✅)

- [x] Create design tokens (`design-tokens.ts`)
- [x] Create UI primitives (Button, Card, Badge, etc.)
- [x] Create dashboard components (MetricCard, TierCard, ActionList)
- [x] Create centralized types (`types/index.ts`)
- [x] Create formatters utility (`formatters.ts`)
- [x] Create new AppShell layout
- [x] Verify build passes

### Phase 2: Page Migration (Recommended Next Steps)

#### OverviewPage Migration

1. Replace inline `MetricCard` with new `MetricCard` from `components/dashboard`
2. Replace tier cards section with `TierSummaryRow`
3. Replace "Next Actions" table with `ActionList`
4. Replace local `StatusMessage` with imported version
5. Use `formatCurrency`, `formatNumber` from `lib/utils/formatters`

```tsx
// Before (inline component)
const MetricCard = ({ label, value, ... }) => { ... }

// After (imported component)
import { MetricCard, MetricCardGrid } from '../components/dashboard';
```

#### CollectabilityPage Migration

1. Replace inline table with `DataTable` component
2. Use `TierBadge` from `components/ui`
3. Replace inline skeleton with `Skeleton` from `components/ui`
4. Use centralized formatters

#### CasesPage Migration

1. Replace case table with `DataTable`
2. Replace case detail drawer with new `Drawer`
3. Use `Button`, `Badge` from `components/ui`
4. Extract case types to `types/index.ts`

### Phase 3: Layout Switch

1. Update `App.tsx` to use `AppShellNew` instead of `AppShell`
2. Test mobile navigation
3. Verify breadcrumbs work correctly
4. Test "What's New" modal integration

### Phase 4: Polish & QA

1. Add loading skeletons to all data-fetching pages
2. Add error boundaries
3. Test all interactive states
4. Performance audit
5. Accessibility audit

---

## 6. Code Patterns & Best Practices

### 6.1 Import Pattern

```tsx
// ✅ Recommended: Import from barrels
import { Button, Card, Badge } from "../components/ui";
import { MetricCard, TierCard } from "../components/dashboard";
import { formatCurrency, formatDate } from "../lib/utils/formatters";
import type { Judgment, Tier } from "../types";

// ❌ Avoid: Deep imports
import { Button } from "../components/ui/Button";
```

### 6.2 Loading States

```tsx
// Always show loading skeleton during data fetch
if (loading) {
  return (
    <div className="space-y-4">
      <Skeleton className="h-8 w-48" />
      <SkeletonText lines={3} />
    </div>
  );
}
```

### 6.3 Error Handling

```tsx
// Use toast for user feedback
const { toast } = useToast();

try {
  await saveData();
  toast({ type: "success", message: "Saved successfully!" });
} catch (error) {
  toast({ type: "error", message: "Failed to save. Please try again." });
}
```

### 6.4 Type Safety

```tsx
// Always type component props
interface CaseCardProps {
  case: Judgment;
  onClick?: (id: string) => void;
  loading?: boolean;
}

// Use centralized types
import type { Tier, CaseStatus, ActionItem } from "../types";
```

---

## 7. Testing Instructions

### Build Verification

```powershell
cd dragonfly-dashboard
npm run build
```

### Dev Server

```powershell
npm run dev
```

### Component Testing Checklist

1. **Button**: Test all variants (primary/secondary/ghost/danger), sizes, loading state
2. **Card**: Test all variants, interactive hover, click handling
3. **Badge**: Test all variants, tier badges, dot indicator
4. **DataTable**: Test sorting, pagination, empty state, loading, row click
5. **Drawer**: Test open/close, backdrop click, escape key, focus trap
6. **Toast**: Test all types, auto-dismiss, manual dismiss
7. **MetricCard**: Test with/without trend, loading skeleton
8. **TierCard**: Test all tiers, click interaction
9. **ActionList**: Test item click, "see all" button, empty state

---

## 8. Performance Notes

### Bundle Size Considerations

- All components use Tailwind utilities (tree-shaken)
- No external UI library dependencies added
- Icons from lucide-react (only imports what's used)

### Optimization Opportunities

1. Lazy load `Drawer` component (not used on initial render)
2. Lazy load `Toast` provider wrapper
3. Consider virtualization for DataTable with 1000+ rows

---

## 9. Accessibility Compliance

All new components include:

- ✅ Semantic HTML elements
- ✅ Proper ARIA labels where needed
- ✅ Keyboard navigation support
- ✅ Focus management (drawers, modals)
- ✅ Color contrast compliance
- ✅ Screen reader announcements for dynamic content

---

## 10. Next Recommended Actions

### Immediate (This Week)

1. Switch to `AppShellNew` in `App.tsx` to enable mobile navigation
2. Migrate `OverviewPage` to use new `MetricCard` and `TierCard`
3. Add loading skeletons to pages that don't have them

### Short-term (This Month)

1. Migrate `CollectabilityPage` to use `DataTable`
2. Migrate `CasesPage` to use `DataTable` and new `Drawer`
3. Add error boundaries around page components

### Long-term (This Quarter)

1. Implement query caching/deduplication for Supabase
2. Add optimistic updates for mutations
3. Performance profiling for large datasets
4. Add end-to-end tests

---

## Summary

This redesign provides:

- **Consistency**: Unified design tokens and component library
- **Scalability**: Type-safe components ready for thousands of cases
- **Accessibility**: WCAG-compliant, keyboard navigable
- **Maintainability**: Centralized types, formatters, and patterns
- **Mobile Support**: New responsive AppShell with mobile navigation
- **Developer Experience**: Clear patterns, barrel exports, documentation

The foundation is complete. Pages can now be migrated incrementally using the new components while maintaining backward compatibility with existing code.
