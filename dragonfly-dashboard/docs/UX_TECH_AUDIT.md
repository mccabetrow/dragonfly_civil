# Dragonfly Civil Dashboard — UX & Technical Audit

**Date:** December 2, 2025  
**Auditor:** Principal Product Engineer  
**Scope:** Full codebase review for production readiness

---

## Executive Summary

The dashboard has a solid foundation with enterprise-grade components (`src/components/ui/*`), a proper design system (`design-tokens.ts`), and demo-safe Supabase wrappers. However, **key pages don't use the new primitives**, creating visual inconsistency and duplicated code. The refresh mechanism is broken (does full page reload), and there are no tier trend indicators or "Today's priorities" actionable list.

**Overall Readiness:** 🟡 **70% ready** — needs 1-2 focused days of polish.

---

## 1. Major UX Gaps

### 1.1 Missing "Today's Priorities" List 🔴 Critical

**Location:** `ExecutiveDashboardPageNew.tsx`

Mom's #1 question when she logs in: _"What should I do today?"_

**Current state:**

- Scoreboard shows metrics, but no actionable case list
- "What changed today" section shows counts, not clickable cases
- No clear "Call these 5 plaintiffs first" guidance

**Fix:** Add a `PriorityActionList` component showing:

- Top 5 Tier A cases by judgment amount
- Cases with follow-up due today
- Click → opens case drawer

---

### 1.2 Refresh Button Does Full Page Reload 🔴 Critical

**Location:** `AppShellNew.tsx:99`

```tsx
const handleRefresh = () => {
  setLastRefresh(new Date());
  window.location.reload(); // ← Full browser reload!
};
```

**Impact:**

- Loses scroll position, filter state, search terms
- Jarring user experience
- Not wired to page-level hooks

**Fix:** Create a `RefreshContext` that pages subscribe to, calling their `refetch()` functions.

---

### 1.3 No Tier Trend Indicators 🟡 High

**Location:** `CollectabilityPage.tsx`, `ExecutiveDashboardPageNew.tsx`

Scoreboard shows "Active cases: 232" but not:

- "↑ 12 from last week"
- "Tier A: 45 (+5)" with green arrow

**Current state:** Trend data exists in `v_metrics_enforcement` but isn't derived for tier breakdowns.

**Fix:** Add week-over-week comparison to scoreboard and tier summary cards.

---

### 1.4 Loading States Are Inconsistent 🟡 High

**CollectabilityPage:** Uses plain `<StatusMessage message="Loading…" />` (unstyled text block)  
**ExecutiveDashboardPageNew:** Uses proper `<MetricsGate>` with skeleton fallback  
**CasesPage:** Uses `<StatusMessage>` (inconsistent with new patterns)

**Fix:** Migrate all pages to use `MetricsGate` + `Skeleton` components.

---

### 1.5 Case Detail Drawer Not Using Design System 🟡 High

**Location:** `CasesPage.tsx:404-560` — `CaseDetailDrawer` component

The drawer is custom-built instead of using `src/components/ui/Drawer.tsx`:

- Manual `fixed inset-0` overlay
- Manual escape key handling
- No animation or accessible focus trap

**Fix:** Refactor to use `<Drawer>` primitive with `Card` components inside.

---

### 1.6 Empty States Missing in Some Flows 🟡 Medium

**CollectabilityPage:** Uses `ZeroStateCard` ✅  
**CasesPage:** Uses `ZeroStateCard` ✅  
**ExecutiveDashboardPageNew:** Uses `EmptyState` for chart ✅  
**ExecutiveDashboardPageNew → "What changed today":** Falls back to plain text ⚠️

**Fix:** Use `ZeroStateCard` consistently for empty data states.

---

## 2. Major Visual Issues

### 2.1 Tables Not Using DataTable Component 🔴 Critical

**Location:** `CollectabilityPage.tsx:301-340`, `CasesPage.tsx:293-330`

Hand-rolled `<table>` with:

- Custom `HeaderCell`, `DataCell`, `SortableHeaderCell` components
- Manual pagination buttons with inconsistent styling
- Custom `tierPillClass()` function instead of `TierBadge`

**New primitives exist but aren't used:**

- `src/components/ui/DataTable.tsx` — full sorting, pagination, row selection
- `src/components/ui/Badge.tsx` — `TierBadge` component

**Fix:** Replace custom tables with `<DataTable>` and use `<TierBadge>` for tiers.

---

### 2.2 Card Styling Inconsistency 🟡 High

**Pattern A (new):** `<Card variant="default">` from `src/components/ui/Card.tsx`  
**Pattern B (legacy):** `<article className="rounded-2xl border border-slate-200 bg-white...">`

**Examples:**

- `CollectabilityPage:362` — `SummaryCard` uses raw classes, not `<Card>`
- `CasesPage:220` — Section wrapper uses raw classes
- `SettingsPage` — Uses raw card styling

**Fix:** Replace raw card divs with `<Card>` + `<CardHeader>` + `<CardContent>`.

---

### 2.3 Button Styling Inconsistency 🟡 Medium

**Pagination buttons** in `CollectabilityPage.tsx:344-360`:

- Manual hover states, disabled states
- Different radius than `Button` component

**Refresh buttons** in `ExecutiveDashboardPageNew.tsx`:

- One uses `<button>` with custom classes
- One uses `<button>` styled as secondary

**Fix:** Use `<Button variant="secondary" size="sm">` for all pagination/actions.

---

### 2.4 Spacing Not Using Design Tokens 🟡 Medium

Design tokens exist but pages use arbitrary values:

```tsx
// design-tokens.ts defines spacing scale
spacing: { 0: '0', 1: '0.25rem', 2: '0.5rem', 4: '1rem', 6: '1.5rem', 8: '2rem' }

// But pages use arbitrary values:
className="space-y-6"  // Some pages
className="space-y-8"  // Other pages
className="py-5"       // Inconsistent padding
```

**Fix:** Standardize to `space-y-6` for sections, `p-6` for cards.

---

### 2.5 Select/Input Styling Needs Standardization 🟡 Low

`CollectabilityPage.tsx:247-260` and `CasesPage.tsx` have custom select/input styling.  
No `<Select>` or `<Input>` primitives in the design system.

**Fix:** Create `<Select>` and `<Input>` components in `ui/`, then migrate.

---

## 3. Major Technical Issues

### 3.1 Duplicated Supabase Fetch Logic 🔴 Critical

**CollectabilityPage.tsx:** Raw `supabaseClient.from()` calls in `useEffect`  
**CasesPage.tsx:** Raw `supabaseClient.from()` calls in `useEffect`  
**Both bypass:**

- `demoSafeSelect()` wrapper
- Proper error normalization
- Unified `MetricsState` pattern

**Hooks exist but aren't used:**

- `useCollectabilitySnapshot.ts` — proper demo-safe wrapper
- `useCasesDashboard.ts` — exists but not imported

**Fix:** Migrate pages to use existing hooks (or create `useCasesPage` hook).

---

### 3.2 Duplicated Helper Functions 🟡 High

**Currency formatter:**

- `CollectabilityPage.tsx:437` — `formatCurrency()` local function
- `CasesPage.tsx:715` — `formatCurrency()` local function
- `ExecutiveDashboardPageNew.tsx` — imports from `utils/formatters`
- `src/lib/utils/formatters.ts` — canonical version ✅

**Tier pill class:**

- `CollectabilityPage.tsx:462` — `tierPillClass()` local function
- `CasesPage.tsx:755` — `tierPillClass()` local function
- `src/components/ui/Badge.tsx` — `TierBadge` component ✅

**Fix:** Delete local functions, import from centralized utils/components.

---

### 3.3 TypeScript Strictness Gaps 🟡 Medium

- `CasesPage.tsx:492` — `Record<string, unknown>` type assertions
- Several `as` casts that could be avoided with proper types
- `CollectabilityTier` type defined in multiple places

**Fix:** Use shared types from `src/types/index.ts`.

---

### 3.4 No Filter Persistence 🟡 Medium

`CollectabilityPage` and `CasesPage` have tier filters and search, but:

- Filters reset on navigation
- No `usePersistedState` hook

**Fix:** Add `usePersistedState` hook using `localStorage` for filter state.

---

### 3.5 Missing Error Boundaries 🟡 Low

No React error boundaries at route level. If a hook throws, entire app crashes.

**Fix:** Add `<ErrorBoundary>` wrapper in `App.tsx` routes.

---

## 4. Prioritized Task Checklist

### 🔴 Must Fix Before Real Users

| #   | Task                                                    | Files                                      | Effort |
| --- | ------------------------------------------------------- | ------------------------------------------ | ------ |
| 1   | Add "Today's Priorities" action list to Overview        | `ExecutiveDashboardPageNew.tsx`            | 2hr    |
| 2   | Fix refresh button to call refetch, not reload          | `AppShellNew.tsx`, create `RefreshContext` | 1hr    |
| 3   | Migrate CollectabilityPage to use DataTable + TierBadge | `CollectabilityPage.tsx`                   | 3hr    |
| 4   | Migrate CasesPage tables to use DataTable + TierBadge   | `CasesPage.tsx`                            | 3hr    |
| 5   | Replace raw Supabase calls with demo-safe hooks         | Both pages                                 | 2hr    |
| 6   | Refactor CaseDetailDrawer to use Drawer primitive       | `CasesPage.tsx`                            | 2hr    |
| 7   | Add MetricsGate + Skeleton to loading states everywhere | All pages                                  | 1hr    |

**Estimated total:** ~14 hours

---

### 🟡 High-Leverage Polish

| #   | Task                                          | Files                                       | Effort |
| --- | --------------------------------------------- | ------------------------------------------- | ------ |
| 8   | Add tier trend indicators (week-over-week)    | `ExecutiveDashboardPageNew.tsx`, new hook   | 2hr    |
| 9   | Replace SummaryCard with TierCard component   | `CollectabilityPage.tsx`                    | 1hr    |
| 10  | Standardize card styling with Card primitives | All pages                                   | 1hr    |
| 11  | Create usePersistedState hook for filters     | `src/hooks/usePersistedState.ts`            | 1hr    |
| 12  | Delete duplicated local formatters/helpers    | `CollectabilityPage`, `CasesPage`           | 30min  |
| 13  | Create Select/Input UI primitives             | `src/components/ui/Select.tsx`, `Input.tsx` | 1hr    |

**Estimated total:** ~7 hours

---

### ⚪ Nice to Have

| #   | Task                                            | Files              | Effort |
| --- | ----------------------------------------------- | ------------------ | ------ |
| 14  | Add route-level error boundaries                | `App.tsx`          | 1hr    |
| 15  | Add keyboard shortcuts (J/K navigation)         | `DataTable.tsx`    | 1hr    |
| 16  | Add skeleton to SettingsPage                    | `SettingsPage.tsx` | 30min  |
| 17  | Add "How to read the dashboard" section to Help | `HelpPage.tsx`     | 1hr    |
| 18  | Basic component render tests                    | `tests/`           | 2hr    |

**Estimated total:** ~6 hours

---

## 5. Component Usage Matrix

| Component       | Overview | Collectability | Cases     | Settings | Help   |
| --------------- | -------- | -------------- | --------- | -------- | ------ |
| `Card`          | ✅       | ⚠️ raw         | ⚠️ raw    | ⚠️ raw   | ⚠️ raw |
| `TierBadge`     | ❌       | ❌ custom      | ❌ custom | N/A      | N/A    |
| `DataTable`     | ❌       | ❌ custom      | ❌ custom | N/A      | N/A    |
| `MetricsGate`   | ✅       | ❌             | ❌        | N/A      | N/A    |
| `Skeleton`      | ✅       | ❌             | ❌        | ❌       | N/A    |
| `Button`        | ✅       | ❌ custom      | ❌ custom | N/A      | ⚠️ raw |
| `ZeroStateCard` | ✅       | ✅             | ✅        | N/A      | N/A    |
| `Drawer`        | ❌       | N/A            | ❌ custom | N/A      | N/A    |

**Legend:** ✅ Using primitive | ⚠️ Using raw classes | ❌ Not using (should be)

---

## 6. Recommended Implementation Order

```
Day 1 (AM): Tasks 1, 2, 7
Day 1 (PM): Tasks 3, 5
Day 2 (AM): Tasks 4, 6
Day 2 (PM): Tasks 8, 9, 10, 11, 12
```

This order ensures:

1. "Today's Priorities" ships first (biggest UX win)
2. Refresh works without page reload
3. Tables get unified before drill-down features
4. Polish comes after core functionality

---

## 7. Files to Modify Summary

| Priority | File                              | Primary Changes                         |
| -------- | --------------------------------- | --------------------------------------- |
| 🔴       | `ExecutiveDashboardPageNew.tsx`   | Add PriorityActionList, tier trends     |
| 🔴       | `AppShellNew.tsx`                 | Wire RefreshContext instead of reload   |
| 🔴       | `CollectabilityPage.tsx`          | Use DataTable, TierBadge, hooks         |
| 🔴       | `CasesPage.tsx`                   | Use DataTable, TierBadge, Drawer, hooks |
| 🟡       | `SettingsPage.tsx`                | Use Card primitives                     |
| 🟡       | `HelpPage.tsx`                    | Add dashboard reading guide             |
| 🟡       | `src/hooks/usePersistedState.ts`  | New file                                |
| 🟡       | `src/contexts/RefreshContext.tsx` | New file                                |

---

## Conclusion

The design system and primitives are **excellent** — the issue is adoption. Most pages were built before the enterprise components existed and haven't been migrated. The path forward is:

1. **Prioritize UX wins** (Today's Priorities, smart refresh)
2. **Migrate to primitives** (DataTable, TierBadge, Drawer)
3. **Delete duplication** (local formatters, custom tier styles)
4. **Add polish** (trends, persistence, keyboard nav)

After this work, the console will be genuinely mom-friendly and enterprise-grade.

---

_End of audit._
