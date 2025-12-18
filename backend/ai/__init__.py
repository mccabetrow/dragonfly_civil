"""
Dragonfly Engine - AI/ML Module

This module contains:
- evaluator.py: Golden dataset regression testing framework
- AgentEvaluator: Generic agent evaluation with exact/semantic match
- ShadowMode: V2 runs side-by-side without affecting production
- OutcomeFeedbackStore: Structured store for collections feedback
"""

from backend.ai.evaluator import (
    AgentEvalResult,
    AgentEvalSummary,
    AgentEvaluator,
    AgentTestCase,
    EvalResult,
    Evaluator,
    GoldenDataset,
    OutcomeFeedback,
    OutcomeFeedbackStore,
    OutcomeType,
    ShadowMode,
    ShadowResult,
    StrictnessMode,
)

__all__ = [
    # Legacy evaluator
    "Evaluator",
    "EvalResult",
    "GoldenDataset",
    # Agent evaluator
    "AgentEvaluator",
    "AgentEvalResult",
    "AgentEvalSummary",
    "AgentTestCase",
    "StrictnessMode",
    # Shadow Mode
    "ShadowMode",
    "ShadowResult",
    # Outcome Feedback
    "OutcomeFeedbackStore",
    "OutcomeFeedback",
    "OutcomeType",
]
