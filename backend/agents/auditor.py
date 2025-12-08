"""
Dragonfly Engine - Auditor Agent

Validates enforcement outputs and flags compliance issues.
Sixth stage in the enforcement pipeline.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime

from .models import (
    AuditorInput,
    AuditorOutput,
    AuditResult,
    ComplianceIssue,
    DrafterOutput,
    NormalizerOutput,
    RiskLevel,
    StrategistOutput,
)

logger = logging.getLogger(__name__)


class Auditor:
    """
    Auditor Agent - Stage 6

    Validates enforcement outputs:
    - Data completeness checks
    - Legal compliance validation
    - Document quality assessment
    - Cost/benefit analysis

    Input: AuditorInput (DrafterOutput + StrategistOutput + NormalizerOutput)
    Output: AuditorOutput (AuditResult with issues/recommendations)
    """

    def __init__(self):
        """Initialize Auditor agent."""
        self._initialized = True
        self._approval_threshold = 70.0  # Minimum score for auto-approval

    # =========================================================================
    # LOGGING HOOKS
    # =========================================================================

    def _log_start(self, input_data: AuditorInput) -> None:
        """Hook: Called when audit starts."""
        logger.info(
            f"[Auditor] Starting audit for "
            f"packet_id={input_data.drafter_output.packet.packet_id}"
        )

    def _log_complete(self, output: AuditorOutput, duration_ms: float) -> None:
        """Hook: Called when audit completes."""
        logger.info(
            f"[Auditor] Completed audit for packet_id={output.packet_id} "
            f"approved={output.audit.is_approved} "
            f"score={output.audit.score:.1f} "
            f"issues={len(output.audit.issues)} "
            f"in {duration_ms:.2f}ms"
        )

    def _log_error(self, input_data: AuditorInput, error: Exception) -> None:
        """Hook: Called when audit fails."""
        logger.error(
            f"[Auditor] Failed audit for "
            f"packet_id={input_data.drafter_output.packet.packet_id}: "
            f"{type(error).__name__}: {error}"
        )

    # =========================================================================
    # VALIDATION CHECKS
    # =========================================================================

    def _check_data_completeness(
        self, norm_output: NormalizerOutput
    ) -> tuple[list[ComplianceIssue], list[str], list[str]]:
        """Check for data completeness issues."""
        issues: list[ComplianceIssue] = []
        warnings: list[str] = []
        passed: list[str] = []

        j = norm_output.judgment

        # Check required fields
        if not j.case_number:
            issues.append(
                ComplianceIssue(
                    severity=RiskLevel.HIGH,
                    category="data",
                    description="Missing case number",
                    location="judgment.case_number",
                    recommendation="Add case number before filing",
                    auto_fixable=False,
                )
            )
        else:
            passed.append("Case number present")

        if not j.debtor_name:
            issues.append(
                ComplianceIssue(
                    severity=RiskLevel.HIGH,
                    category="data",
                    description="Missing debtor name",
                    location="judgment.debtor_name",
                    recommendation="Add debtor name before filing",
                    auto_fixable=False,
                )
            )
        else:
            passed.append("Debtor name present")

        if j.judgment_amount <= 0:
            issues.append(
                ComplianceIssue(
                    severity=RiskLevel.CRITICAL,
                    category="data",
                    description="Invalid or zero judgment amount",
                    location="judgment.judgment_amount",
                    recommendation="Verify and correct judgment amount",
                    auto_fixable=False,
                )
            )
        else:
            passed.append("Judgment amount valid")

        # Check validation errors from normalizer
        for error in j.validation_errors:
            issues.append(
                ComplianceIssue(
                    severity=RiskLevel.HIGH,
                    category="data",
                    description=error,
                    location="normalizer.validation",
                    recommendation="Resolve validation error",
                    auto_fixable=False,
                )
            )

        # Check validation warnings
        for warning in j.validation_warnings:
            warnings.append(warning)

        return issues, warnings, passed

    def _check_document_quality(
        self, drafter_output: DrafterOutput
    ) -> tuple[list[ComplianceIssue], list[str], list[str]]:
        """Check document quality and completeness."""
        issues: list[ComplianceIssue] = []
        warnings: list[str] = []
        passed: list[str] = []

        packet = drafter_output.packet

        if not packet.documents:
            issues.append(
                ComplianceIssue(
                    severity=RiskLevel.CRITICAL,
                    category="format",
                    description="No documents in packet",
                    location="packet.documents",
                    recommendation="Generate required documents",
                    auto_fixable=False,
                )
            )
            return issues, warnings, passed

        passed.append(f"Packet contains {len(packet.documents)} document(s)")

        # Check each document
        for doc in packet.documents:
            # Check for unfilled placeholders
            if doc.placeholders:
                issues.append(
                    ComplianceIssue(
                        severity=RiskLevel.MEDIUM,
                        category="format",
                        description=f"{doc.title}: {len(doc.placeholders)} unfilled placeholder(s)",
                        location=f"document.{doc.document_type.value}",
                        recommendation="Complete all placeholder fields",
                        auto_fixable=False,
                    )
                )
            else:
                passed.append(f"{doc.title}: All fields complete")

            # Check document length (too short = likely incomplete)
            if len(doc.content) < 500:
                warnings.append(f"{doc.title}: Document may be incomplete (short content)")

            # Check for required legal elements
            if "SUPREME COURT" not in doc.content.upper() and doc.document_type.value not in [
                "settlement_letter",
                "demand_letter",
            ]:
                issues.append(
                    ComplianceIssue(
                        severity=RiskLevel.LOW,
                        category="legal",
                        description=f"{doc.title}: Missing court header",
                        location=f"document.{doc.document_type.value}",
                        recommendation="Add proper court header",
                        auto_fixable=True,
                    )
                )

            # Check for signature line
            if "_______" not in doc.content:
                warnings.append(f"{doc.title}: Missing signature line")

        return issues, warnings, passed

    def _check_strategy_validity(
        self, strategist_output: StrategistOutput, norm_output: NormalizerOutput
    ) -> tuple[list[ComplianceIssue], list[str], list[str]]:
        """Check strategy validity and alignment."""
        issues: list[ComplianceIssue] = []
        warnings: list[str] = []
        passed: list[str] = []

        plan = strategist_output.plan
        j = norm_output.judgment

        # Check for steps
        if not plan.steps:
            issues.append(
                ComplianceIssue(
                    severity=RiskLevel.HIGH,
                    category="legal",
                    description="No enforcement steps in plan",
                    location="plan.steps",
                    recommendation="Generate enforcement strategy",
                    auto_fixable=False,
                )
            )
            return issues, warnings, passed

        passed.append(f"Plan has {len(plan.steps)} enforcement step(s)")

        # Check cost/benefit
        if plan.total_estimated_cost > j.judgment_amount * 0.5:
            issues.append(
                ComplianceIssue(
                    severity=RiskLevel.MEDIUM,
                    category="legal",
                    description="Enforcement cost exceeds 50% of judgment value",
                    location="plan.total_estimated_cost",
                    recommendation="Review strategy for cost efficiency",
                    auto_fixable=False,
                )
            )
        else:
            passed.append("Enforcement costs within acceptable range")

        # Check recovery rate
        if plan.expected_recovery_rate < 0.10:
            warnings.append("Very low expected recovery rate (<10%)")
        elif plan.expected_recovery_rate > 0.50:
            passed.append(f"Good expected recovery rate ({plan.expected_recovery_rate:.0%})")

        # Check for statute of limitations concerns
        if j.age_days > 1825:  # 5 years
            issues.append(
                ComplianceIssue(
                    severity=RiskLevel.HIGH,
                    category="legal",
                    description="Judgment approaching statute of limitations",
                    location="judgment.age_days",
                    recommendation="Verify judgment is still enforceable",
                    auto_fixable=False,
                )
            )
        elif j.age_days > 1460:  # 4 years
            warnings.append("Judgment age > 4 years - monitor statute of limitations")
        else:
            passed.append("Judgment within statute of limitations")

        return issues, warnings, passed

    def _check_legal_compliance(
        self, drafter_output: DrafterOutput, norm_output: NormalizerOutput
    ) -> tuple[list[ComplianceIssue], list[str], list[str]]:
        """Check for NY legal compliance issues."""
        issues: list[ComplianceIssue] = []
        warnings: list[str] = []
        passed: list[str] = []

        j = norm_output.judgment
        packet = drafter_output.packet

        # Check CPLR references in documents
        cplr_refs = []
        for doc in packet.documents:
            refs = re.findall(r"CPLR\s+\d+", doc.content.upper())
            cplr_refs.extend(refs)

        if cplr_refs:
            passed.append(f"Documents contain {len(set(cplr_refs))} CPLR reference(s)")
        else:
            warnings.append("No CPLR references found in documents")

        # Check county consistency
        counties_in_docs = set()
        for doc in packet.documents:
            county_match = re.search(r"COUNTY OF\s+(\w+)", doc.content.upper())
            if county_match:
                counties_in_docs.add(county_match.group(1))

        if len(counties_in_docs) > 1:
            issues.append(
                ComplianceIssue(
                    severity=RiskLevel.MEDIUM,
                    category="legal",
                    description="Inconsistent county references in documents",
                    location="documents",
                    recommendation="Verify correct county for all documents",
                    auto_fixable=True,
                )
            )
        elif counties_in_docs and j.county_normalized:
            doc_county = list(counties_in_docs)[0]
            if doc_county != j.county_normalized.upper():
                issues.append(
                    ComplianceIssue(
                        severity=RiskLevel.HIGH,
                        category="legal",
                        description=f"County mismatch: document says {doc_county}, judgment is {j.county_normalized}",
                        location="documents.county",
                        recommendation="Correct county in documents",
                        auto_fixable=True,
                    )
                )
            else:
                passed.append("County references consistent")

        return issues, warnings, passed

    def _calculate_score(self, issues: list[ComplianceIssue], passed: list[str]) -> float:
        """Calculate audit score based on issues and passed checks."""
        if not issues and not passed:
            return 50.0  # Neutral

        # Start with 100
        score = 100.0

        # Deduct for issues by severity
        severity_deductions = {
            RiskLevel.CRITICAL: 30,
            RiskLevel.HIGH: 15,
            RiskLevel.MEDIUM: 8,
            RiskLevel.LOW: 3,
        }

        for issue in issues:
            score -= severity_deductions.get(issue.severity, 5)

        # Bonus for passed checks (up to +10)
        bonus = min(10, len(passed) * 2)
        score += bonus

        return max(0, min(100, score))

    def _generate_recommendations(self, issues: list[ComplianceIssue], score: float) -> list[str]:
        """Generate actionable recommendations."""
        recommendations: list[str] = []

        # Critical issues first
        critical_issues = [i for i in issues if i.severity == RiskLevel.CRITICAL]
        if critical_issues:
            recommendations.append(
                f"URGENT: Resolve {len(critical_issues)} critical issue(s) before proceeding"
            )

        # High severity
        high_issues = [i for i in issues if i.severity == RiskLevel.HIGH]
        if high_issues:
            recommendations.append(f"Address {len(high_issues)} high-priority issue(s)")

        # Auto-fixable issues
        auto_fixable = [i for i in issues if i.auto_fixable]
        if auto_fixable:
            recommendations.append(f"{len(auto_fixable)} issue(s) can be auto-fixed")

        # Score-based recommendations
        if score >= 90:
            recommendations.append("Packet is ready for filing")
        elif score >= 70:
            recommendations.append("Packet needs minor revisions before filing")
        elif score >= 50:
            recommendations.append("Significant revisions required")
        else:
            recommendations.append("Major issues - recommend manual review")

        return recommendations

    # =========================================================================
    # MAIN RUN METHOD
    # =========================================================================

    async def run(self, input_data: AuditorInput) -> AuditorOutput:
        """
        Execute the audit pipeline.

        Args:
            input_data: AuditorInput with all prior stage outputs

        Returns:
            AuditorOutput with AuditResult

        Raises:
            Exception: On processing errors
        """
        start_time = datetime.utcnow()
        self._log_start(input_data)

        try:
            drafter_output = input_data.drafter_output
            strategist_output = input_data.strategist_output
            normalizer_output = input_data.normalizer_output

            all_issues: list[ComplianceIssue] = []
            all_warnings: list[str] = []
            all_passed: list[str] = []

            # Run all checks
            issues, warnings, passed = self._check_data_completeness(normalizer_output)
            all_issues.extend(issues)
            all_warnings.extend(warnings)
            all_passed.extend(passed)

            issues, warnings, passed = self._check_document_quality(drafter_output)
            all_issues.extend(issues)
            all_warnings.extend(warnings)
            all_passed.extend(passed)

            issues, warnings, passed = self._check_strategy_validity(
                strategist_output, normalizer_output
            )
            all_issues.extend(issues)
            all_warnings.extend(warnings)
            all_passed.extend(passed)

            issues, warnings, passed = self._check_legal_compliance(
                drafter_output, normalizer_output
            )
            all_issues.extend(issues)
            all_warnings.extend(warnings)
            all_passed.extend(passed)

            # Calculate score
            score = self._calculate_score(all_issues, all_passed)

            # Determine approval
            critical_count = sum(1 for i in all_issues if i.severity == RiskLevel.CRITICAL)
            is_approved = score >= self._approval_threshold and critical_count == 0

            # Generate recommendations
            recommendations = self._generate_recommendations(all_issues, score)

            # Build audit result
            audit = AuditResult(
                is_approved=is_approved,
                score=score,
                issues=all_issues,
                warnings=all_warnings,
                passed_checks=all_passed,
                recommendations=recommendations,
            )

            output = AuditorOutput(
                judgment_id=normalizer_output.judgment.judgment_id,
                packet_id=drafter_output.packet.packet_id,
                audit=audit,
                audited_at=datetime.utcnow(),
            )

            # Log completion
            duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
            self._log_complete(output, duration_ms)

            return output

        except Exception as e:
            self._log_error(input_data, e)
            raise

    # =========================================================================
    # LLM INTEGRATION HOOKS
    # =========================================================================

    async def _llm_deep_review(self, packet_content: str) -> list[ComplianceIssue]:
        """
        TODO: LLM integration for deep document review.

        Use case: Comprehensive review of document content
        for legal accuracy and completeness.

        Args:
            packet_content: Full packet text

        Returns:
            List of identified issues

        Implementation notes:
            - Use Claude or GPT-4 for legal review
            - Check for common legal errors
            - Verify NY enforcement law compliance
        """
        # TODO: Implement LLM call
        logger.debug("[Auditor] LLM deep review not implemented")
        return []

    async def _llm_suggest_fixes(self, issues: list[ComplianceIssue]) -> dict[str, str]:
        """
        TODO: LLM integration for fix suggestions.

        Use case: Generate specific fix suggestions for
        identified issues.

        Args:
            issues: List of compliance issues

        Returns:
            Dict mapping issue descriptions to fix suggestions

        Implementation notes:
            - Generate actionable fix text
            - Provide example corrections
            - Consider auto-fix opportunities
        """
        # TODO: Implement LLM call
        logger.debug("[Auditor] LLM fix suggestions not implemented")
        return {}
