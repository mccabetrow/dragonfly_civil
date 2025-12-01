# Operations Documentation

> Runbooks, playbooks, SOPs, and import procedures for Dragonfly Civil.

---

## Contents

| Document                                                   | Description                                     |
| ---------------------------------------------------------- | ----------------------------------------------- |
| [RUNBOOK_900_IMPORT.md](./RUNBOOK_900_IMPORT.md)           | Step-by-step guide for the 900-plaintiff import |
| [playbook_900_intake_day.md](./playbook_900_intake_day.md) | Day-of execution checklist for 900 import       |
| [dry_run_900.md](./dry_run_900.md)                         | Dry run procedures and validation steps         |
| [ops_onboarding.md](./ops_onboarding.md)                   | Onboarding guide for new operators              |
| [ops_playbook_v1.md](./ops_playbook_v1.md)                 | General operations playbook                     |
| [runbook_ops.md](./runbook_ops.md)                         | Daily ops procedures                            |
| [runbook_phase1.md](./runbook_phase1.md)                   | Phase 1 launch runbook                          |
| [importer.md](./importer.md)                               | Importer tool documentation                     |
| [simplicity_importer.md](./simplicity_importer.md)         | Simplicity vendor import procedures             |

---

## Ownership

- **Primary Owner:** Mom (Ops Director) for execution
- **Technical Support:** McCabe (COO/CTO) for tooling

---

## Runbook Standards

1. **Pre-flight:** Always run preflight checks before imports
2. **Dry-run:** Test with `--dry-run` flag before committing
3. **Batching:** Import in batches (10 → 30 → 100 → full)
4. **Rollback:** Document rollback procedures for each operation
5. **Post-mortem:** Document lessons learned after major operations
