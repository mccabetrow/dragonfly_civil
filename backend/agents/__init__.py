"""
Dragonfly Engine - AI Agent Framework

Multi-stage agent pipeline for judgment enforcement workflow automation.

Pipeline stages:
1. Extractor   - Pull raw judgment data from Supabase
2. Normalizer  - Standardize and validate extracted data
3. Reasoner    - Analyze case facts and identify enforcement opportunities
4. Strategist  - Generate prioritized enforcement strategy
5. Drafter     - Create enforcement packet documents
6. Auditor     - Validate outputs and flag compliance issues

Usage:
    from backend.agents import Orchestrator

    orchestrator = Orchestrator()
    result = await orchestrator.run(judgment_id="abc123")
"""

from .auditor import Auditor
from .drafter import Drafter
from .extractor import Extractor
from .normalizer import Normalizer
from .orchestrator import Orchestrator
from .reasoner import Reasoner
from .strategist import Strategist

__all__ = [
    "Orchestrator",
    "Extractor",
    "Normalizer",
    "Reasoner",
    "Strategist",
    "Drafter",
    "Auditor",
]
