# Compliance Documentation

> FDCPA, FCRA, GLBA policies, operator training materials, and audit documentation.

---

## Contents

| Document                                                                                   | Description                                                |
| ------------------------------------------------------------------------------------------ | ---------------------------------------------------------- |
| [compliance_manual_v1.md](./compliance_manual_v1.md)                                       | Comprehensive compliance manual covering FDCPA, FCRA, GLBA |
| [mom_desk_card.md](./mom_desk_card.md)                                                     | 1-page quick reference: 10 DOs, 10 DON'Ts, decision trees  |
| [scripts_and_templates.md](./scripts_and_templates.md)                                     | Phone scripts, demand letters, settlement templates        |
| [dragonfly_security_and_compliance_audit.md](./dragonfly_security_and_compliance_audit.md) | Security audit findings and RLS policies                   |

---

## Key Regulations

| Regulation | Scope                                                           |
| ---------- | --------------------------------------------------------------- |
| **FDCPA**  | Fair Debt Collection Practices Act – debtor communication rules |
| **FCRA**   | Fair Credit Reporting Act – permissible purpose, disputes       |
| **GLBA**   | Gramm-Leach-Bliley Act – data security, privacy                 |

---

## Ownership

- **Primary Owner:** Mom (Ops Director) for daily compliance
- **Legal Review:** Dad (CEO) for policy decisions
- **Technical Controls:** McCabe (COO/CTO) for system enforcement

---

## Training Requirements

All operators must:

1. Read `compliance_manual_v1.md` before handling debtor communications
2. Keep `mom_desk_card.md` printed at workstation
3. Complete annual compliance refresher (Q1 each year)

---

## Audit Trail

All compliance-related actions are logged in Supabase with:

- Timestamp
- User ID
- Action type
- Plaintiff/debtor reference
