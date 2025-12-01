# Engineering Documentation

> Architecture, agent specifications, API docs, and worker references.

---

## Contents

### Architecture & Design

| Document                                                   | Description                                         |
| ---------------------------------------------------------- | --------------------------------------------------- |
| [n8n_bridge_architecture.md](./n8n_bridge_architecture.md) | n8n → Python bridge design, workflow classification |
| [enforcement_engine.md](./enforcement_engine.md)           | Enforcement engine architecture                     |
| [enforcement_flows.md](./enforcement_flows.md)             | Enforcement workflow state machine                  |
| [enforcement_tiers.md](./enforcement_tiers.md)             | Tier assignment logic and rules                     |
| [queues.md](./queues.md)                                   | Queue system design (call, signature, tasks)        |

### Agent Specifications

| Document                                                     | Description                          |
| ------------------------------------------------------------ | ------------------------------------ |
| [dragonfly_codex_prompt.md](./dragonfly_codex_prompt.md)     | AI agent system prompt               |
| [Dragonfly_Codex_Guide.md](./Dragonfly_Codex_Guide.md)       | Codex integration guide              |
| [DRAGONFLY_Codex_Playbook.md](./DRAGONFLY_Codex_Playbook.md) | Playbook for AI-assisted development |
| [ai_guidelines.md](./ai_guidelines.md)                       | AI usage guidelines and constraints  |
| [codex_prompts.md](./codex_prompts.md)                       | Prompt library for Codex             |

### API & Integration

| Document                                                       | Description                         |
| -------------------------------------------------------------- | ----------------------------------- |
| [worker_n8n_rpc_reference.md](./worker_n8n_rpc_reference.md)   | RPC endpoints for n8n workers       |
| [database_rpc_requirements.md](./database_rpc_requirements.md) | Database RPC function specs         |
| [n8n_orchestration.md](./n8n_orchestration.md)                 | n8n workflow orchestration patterns |
| [n8n_alerts.md](./n8n_alerts.md)                               | Alert configuration for n8n         |
| [n8n_bridge_mapping.md](./n8n_bridge_mapping.md)               | Workflow-to-Python mapping table    |

### Workflows

| Document                                                                       | Description                    |
| ------------------------------------------------------------------------------ | ------------------------------ |
| [workflow_income_execution_factory.md](./workflow_income_execution_factory.md) | Income execution workflow spec |
| [workflow_new_lead_enrichment.md](./workflow_new_lead_enrichment.md)           | New lead enrichment workflow   |

---

## Ownership

- **Primary Owner:** McCabe (COO/CTO)

---

## Standards

1. **API docs:** Include request/response schemas
2. **Agent specs:** Define inputs, outputs, and constraints
3. **Architecture:** Include diagrams where helpful
4. **Versioning:** Note breaking changes in headers
