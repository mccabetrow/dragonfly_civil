# Dragonfly - Civil Judgment Enforcement Automation

## Project Setup Checklist

- [x] Verify that the copilot-instructions.md file in the .github directory is created
- [x] Clarify Project Requirements - Python backend, Postgres/Supabase, ETL automation
- [x] Scaffold the Project - Create folder structure and placeholder files
- [x] Customize the Project - Add schema, scripts, and configuration
- [x] Install Required Extensions - Python, Database tools
- [ ] Compile the Project - Install dependencies
- [ ] Create and Run Task - Setup development tasks
- [ ] Launch the Project - Test environment setup
- [ ] Ensure Documentation is Complete - Update README

## Project Overview

Dragonfly is a civil-judgment enforcement automation system with:
- Database: Postgres/Supabase (central truth)
- CRM/outreach: Simplicity integration (CSV + API)
- Automation: n8n or Python scheduling
- ETL: Python 3.11+ scripts
- Infrastructure: 12-factor .env config
- Tooling: VS Code tasks.json

## Development Guidelines

- Python 3.11+ required
- Follow 12-factor app principles
- Keep env config in .env files
- Use Supabase for local development
- Document all processes in README
