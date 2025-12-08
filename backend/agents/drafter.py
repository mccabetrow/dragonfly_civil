"""
Dragonfly Engine - Drafter Agent

Creates enforcement packet documents from strategy.
Fifth stage in the enforcement pipeline.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from decimal import Decimal

from .models import (
    DocumentType,
    DraftDocument,
    DrafterInput,
    DrafterOutput,
    DraftPacket,
    EnforcementAction,
    NormalizerOutput,
    StrategistOutput,
)

logger = logging.getLogger(__name__)

# Filing fees by document type
FILING_FEES: dict[DocumentType, Decimal] = {
    DocumentType.INCOME_EXECUTION: Decimal("45"),
    DocumentType.RESTRAINING_NOTICE: Decimal("0"),
    DocumentType.PROPERTY_EXECUTION: Decimal("45"),
    DocumentType.INFORMATION_SUBPOENA: Decimal("35"),
    DocumentType.SETTLEMENT_LETTER: Decimal("0"),
    DocumentType.DEMAND_LETTER: Decimal("0"),
}


class Drafter:
    """
    Drafter Agent - Stage 5

    Generates enforcement documents:
    - Income execution forms
    - Restraining notices
    - Property executions
    - Information subpoenas
    - Settlement/demand letters

    Input: DrafterInput (StrategistOutput + NormalizerOutput)
    Output: DrafterOutput (DraftPacket with documents)
    """

    def __init__(self):
        """Initialize Drafter agent."""
        self._initialized = True

    # =========================================================================
    # LOGGING HOOKS
    # =========================================================================

    def _log_start(self, input_data: DrafterInput) -> None:
        """Hook: Called when drafting starts."""
        logger.info(
            f"[Drafter] Starting document drafting for "
            f"plan_id={input_data.strategist_output.plan.plan_id}"
        )

    def _log_complete(self, output: DrafterOutput, duration_ms: float) -> None:
        """Hook: Called when drafting completes."""
        packet = output.packet
        logger.info(
            f"[Drafter] Completed drafting for packet_id={packet.packet_id} "
            f"documents={len(packet.documents)} "
            f"fees=${packet.total_filing_fees:.2f} "
            f"in {duration_ms:.2f}ms"
        )

    def _log_error(self, input_data: DrafterInput, error: Exception) -> None:
        """Hook: Called when drafting fails."""
        logger.error(
            f"[Drafter] Failed drafting for "
            f"plan_id={input_data.strategist_output.plan.plan_id}: "
            f"{type(error).__name__}: {error}"
        )

    # =========================================================================
    # DOCUMENT GENERATION
    # =========================================================================

    def _generate_income_execution(
        self, norm_output: NormalizerOutput, target: str
    ) -> DraftDocument:
        """Generate income execution document."""
        j = norm_output.judgment
        intel = norm_output.debtor_intel

        employer_name = target
        employer_address = intel.employer_address if intel else "[EMPLOYER ADDRESS]"

        content = f"""
NEW YORK STATE
INCOME EXECUTION

SUPREME COURT OF THE STATE OF NEW YORK
COUNTY OF {j.county_normalized or "[COUNTY]"}

{j.plaintiff_name or "[PLAINTIFF NAME]"},
                    Judgment Creditor,

        -against-                           Index No.: {j.case_number}

{j.debtor_name or "[DEBTOR NAME]"},
                    Judgment Debtor.

TO: {employer_name}
    {employer_address}

INCOME EXECUTION

PLEASE TAKE NOTICE that pursuant to CPLR 5231, you are hereby directed to
withhold from the earnings of the above-named judgment debtor and pay over
to the undersigned, as attorney for the judgment creditor, the sum of:

    JUDGMENT AMOUNT:     ${j.judgment_amount:,.2f}
    PLUS INTEREST AND COSTS

You are directed to withhold ten percent (10%) of the judgment debtor's
earnings, or the amount specified in CPLR 5231(b), whichever is less, and
remit such amount to the undersigned within seven (7) days after each pay
period.

This income execution shall remain in effect until the judgment is satisfied
in full or until further order of the court.

Dated: {datetime.now().strftime("%B %d, %Y")}

_______________________________
Attorney for Judgment Creditor
[ATTORNEY NAME]
[ATTORNEY ADDRESS]
[ATTORNEY PHONE]
"""

        placeholders = []
        if "[" in content:
            # Find all placeholders
            import re

            placeholders = re.findall(r"\[[A-Z\s]+\]", content)

        return DraftDocument(
            document_type=DocumentType.INCOME_EXECUTION,
            title=f"Income Execution - {j.case_number}",
            content=content.strip(),
            placeholders=list(set(placeholders)),
            is_complete=len(placeholders) == 0,
            requires_notarization=False,
            filing_instructions=("File with County Clerk. Serve on employer via certified mail."),
        )

    def _generate_restraining_notice(
        self, norm_output: NormalizerOutput, target: str
    ) -> DraftDocument:
        """Generate restraining notice document."""
        j = norm_output.judgment

        content = f"""
NEW YORK STATE
RESTRAINING NOTICE

SUPREME COURT OF THE STATE OF NEW YORK
COUNTY OF {j.county_normalized or "[COUNTY]"}

{j.plaintiff_name or "[PLAINTIFF NAME]"},
                    Judgment Creditor,

        -against-                           Index No.: {j.case_number}

{j.debtor_name or "[DEBTOR NAME]"},
                    Judgment Debtor.

TO: {target}
    [ADDRESS]

RESTRAINING NOTICE

PLEASE TAKE NOTICE that pursuant to CPLR 5222, you are hereby restrained
from making or suffering any sale, assignment or transfer of, or any
interference with, any property in which the above-named judgment debtor
has an interest, including but not limited to money, bank accounts, wages,
or other property.

This notice affects the following property:

    All funds, credits, or other property belonging to or owed to the
    judgment debtor, {j.debtor_name or "[DEBTOR NAME]"}, up to the amount of
    ${j.judgment_amount:,.2f} plus interest and costs.

The judgment creditor has a judgment against the judgment debtor in the
amount of ${j.judgment_amount:,.2f}, entered on {j.judgment_date or "[DATE]"}.

Violation of this restraint is punishable as a contempt of court.

Dated: {datetime.now().strftime("%B %d, %Y")}

_______________________________
Attorney for Judgment Creditor
"""

        import re

        placeholders = re.findall(r"\[[A-Z\s]+\]", content)

        return DraftDocument(
            document_type=DocumentType.RESTRAINING_NOTICE,
            title=f"Restraining Notice - {j.case_number}",
            content=content.strip(),
            placeholders=list(set(placeholders)),
            is_complete=len(placeholders) == 0,
            requires_notarization=False,
            filing_instructions="Serve on target via personal service or certified mail.",
        )

    def _generate_property_execution(
        self, norm_output: NormalizerOutput, target: str
    ) -> DraftDocument:
        """Generate property execution document."""
        j = norm_output.judgment

        content = f"""
NEW YORK STATE
PROPERTY EXECUTION

SUPREME COURT OF THE STATE OF NEW YORK
COUNTY OF {j.county_normalized or "[COUNTY]"}

{j.plaintiff_name or "[PLAINTIFF NAME]"},
                    Judgment Creditor,

        -against-                           Index No.: {j.case_number}

{j.debtor_name or "[DEBTOR NAME]"},
                    Judgment Debtor.

EXECUTION

TO THE SHERIFF OF {j.county_normalized or "[COUNTY]"} COUNTY:

You are hereby commanded to satisfy the judgment described below out of the
personal property of the judgment debtor within your county:

    Judgment Amount:     ${j.judgment_amount:,.2f}
    Date of Judgment:    {j.judgment_date or "[DATE]"}
    Interest From:       {j.judgment_date or "[DATE]"}
    Costs Taxed:         $[COSTS]

TARGET PROPERTY:
{target}

If sufficient personal property cannot be found, you are authorized to
proceed against real property pursuant to CPLR 5236.

Dated: {datetime.now().strftime("%B %d, %Y")}

_______________________________
Clerk of the Court

_______________________________
Attorney for Judgment Creditor
"""

        import re

        placeholders = re.findall(r"\[[A-Z\s]+\]", content)

        return DraftDocument(
            document_type=DocumentType.PROPERTY_EXECUTION,
            title=f"Property Execution - {j.case_number}",
            content=content.strip(),
            placeholders=list(set(placeholders)),
            is_complete=len(placeholders) == 0,
            requires_notarization=False,
            filing_instructions=("File with County Clerk. Deliver to Sheriff for execution."),
        )

    def _generate_information_subpoena(self, norm_output: NormalizerOutput) -> DraftDocument:
        """Generate information subpoena document."""
        j = norm_output.judgment

        content = f"""
NEW YORK STATE
INFORMATION SUBPOENA

SUPREME COURT OF THE STATE OF NEW YORK
COUNTY OF {j.county_normalized or "[COUNTY]"}

{j.plaintiff_name or "[PLAINTIFF NAME]"},
                    Judgment Creditor,

        -against-                           Index No.: {j.case_number}

{j.debtor_name or "[DEBTOR NAME]"},
                    Judgment Debtor.

INFORMATION SUBPOENA

TO: {j.debtor_name or "[DEBTOR NAME]"}
    [DEBTOR ADDRESS]

Pursuant to CPLR 5224, you are hereby required to answer in writing, under
oath, the questions attached hereto, and to return your answers to the
undersigned within seven (7) days after service of this subpoena.

QUESTIONS:

1. State your full legal name and any other names by which you have been
   known.

2. State your current address and all addresses at which you have resided
   during the past five (5) years.

3. State the name and address of your current employer, your position, and
   your gross weekly, bi-weekly, or monthly income.

4. List all bank accounts, brokerage accounts, or other financial accounts
   in which you have any interest, including the name and address of each
   financial institution and the account numbers.

5. List all real property in which you have any interest, including the
   address and the nature of your interest.

6. List all motor vehicles, boats, or other vehicles owned by you or
   registered in your name.

7. List all other assets having a value in excess of $500.

YOUR FAILURE TO COMPLY WITH THIS SUBPOENA MAY RESULT IN PUNISHMENT FOR
CONTEMPT OF COURT.

Dated: {datetime.now().strftime("%B %d, %Y")}

_______________________________
Attorney for Judgment Creditor
"""

        import re

        placeholders = re.findall(r"\[[A-Z\s]+\]", content)

        return DraftDocument(
            document_type=DocumentType.INFORMATION_SUBPOENA,
            title=f"Information Subpoena - {j.case_number}",
            content=content.strip(),
            placeholders=list(set(placeholders)),
            is_complete=len(placeholders) == 0,
            requires_notarization=False,
            filing_instructions=("Serve on judgment debtor. Answers due within 7 days."),
        )

    def _generate_settlement_letter(
        self, norm_output: NormalizerOutput, discount_pct: float = 0.20
    ) -> DraftDocument:
        """Generate settlement offer letter."""
        j = norm_output.judgment
        settlement_amount = j.judgment_amount * Decimal(str(1 - discount_pct))

        content = f"""
[FIRM LETTERHEAD]

{datetime.now().strftime("%B %d, %Y")}

{j.debtor_name or "[DEBTOR NAME]"}
[DEBTOR ADDRESS]

RE: Settlement Offer - {j.case_number}
    Judgment Amount: ${j.judgment_amount:,.2f}

Dear {j.debtor_name or "Judgment Debtor"}:

We represent {j.plaintiff_name or "[PLAINTIFF NAME]"}, the judgment creditor
in the above-referenced matter. A judgment was entered against you on
{j.judgment_date or "[DATE]"} in the amount of ${j.judgment_amount:,.2f}.

Our client is willing to consider a settlement of this matter for a reduced
amount. Specifically, our client will accept:

    SETTLEMENT AMOUNT: ${settlement_amount:,.2f}
    (Representing a {discount_pct:.0%} discount)

This offer is contingent upon receipt of payment within thirty (30) days of
the date of this letter. Upon receipt of payment, we will file a satisfaction
of judgment with the court.

If we do not receive payment or a response to this offer within the time
specified, we will proceed with enforcement actions including, but not limited
to, wage garnishment, bank levies, and property liens.

Please contact our office to discuss this matter or to arrange payment.

Very truly yours,

_______________________________
[ATTORNEY NAME]
Attorney for Judgment Creditor
[PHONE]
[EMAIL]
"""

        import re

        placeholders = re.findall(r"\[[A-Z\s]+\]", content)

        return DraftDocument(
            document_type=DocumentType.SETTLEMENT_LETTER,
            title=f"Settlement Offer - {j.case_number}",
            content=content.strip(),
            placeholders=list(set(placeholders)),
            is_complete=len(placeholders) == 0,
            requires_notarization=False,
            filing_instructions="Send via certified mail, return receipt requested.",
        )

    def _generate_cover_letter(
        self, norm_output: NormalizerOutput, strategy_name: str, doc_count: int
    ) -> str:
        """Generate packet cover letter."""
        j = norm_output.judgment

        return f"""
ENFORCEMENT PACKET COVER LETTER

Case: {j.case_number}
Debtor: {j.debtor_name or "[DEBTOR NAME]"}
Judgment Amount: ${j.judgment_amount:,.2f}
Strategy: {strategy_name}

This packet contains {doc_count} document(s) for enforcement of the
above-referenced judgment.

Please review all documents for accuracy and complete any fields marked
with brackets before filing or service.

Generated: {datetime.now().strftime("%B %d, %Y at %I:%M %p")}
""".strip()

    def _generate_filing_checklist(self, documents: list[DraftDocument]) -> list[str]:
        """Generate filing checklist based on documents."""
        checklist: list[str] = []

        for doc in documents:
            checklist.append(f"[ ] Review {doc.title}")
            if doc.placeholders:
                checklist.append(f"    [ ] Complete {len(doc.placeholders)} placeholder(s)")
            if doc.requires_notarization:
                checklist.append("    [ ] Obtain notarization")
            if doc.filing_instructions:
                checklist.append(f"    [ ] {doc.filing_instructions}")

        checklist.append("[ ] Retain copies for file")
        checklist.append("[ ] Update case status in system")

        return checklist

    # =========================================================================
    # MAIN RUN METHOD
    # =========================================================================

    async def run(self, input_data: DrafterInput) -> DrafterOutput:
        """
        Execute the document drafting pipeline.

        Args:
            input_data: DrafterInput with StrategistOutput and NormalizerOutput

        Returns:
            DrafterOutput with DraftPacket

        Raises:
            Exception: On processing errors
        """
        start_time = datetime.utcnow()
        self._log_start(input_data)

        try:
            strategist_output = input_data.strategist_output
            normalizer_output = input_data.normalizer_output
            plan = strategist_output.plan

            # Generate packet ID
            packet_id = f"pkt_{uuid.uuid4().hex[:12]}"

            # Collect unique document types needed
            documents: list[DraftDocument] = []
            seen_types: set[DocumentType] = set()

            for step in plan.steps:
                for doc_type in step.documents_required:
                    if doc_type in seen_types:
                        continue
                    seen_types.add(doc_type)

                    # Generate document based on type
                    if doc_type == DocumentType.INCOME_EXECUTION:
                        doc = self._generate_income_execution(normalizer_output, step.target)
                    elif doc_type == DocumentType.RESTRAINING_NOTICE:
                        doc = self._generate_restraining_notice(normalizer_output, step.target)
                    elif doc_type == DocumentType.PROPERTY_EXECUTION:
                        doc = self._generate_property_execution(normalizer_output, step.target)
                    elif doc_type == DocumentType.INFORMATION_SUBPOENA:
                        doc = self._generate_information_subpoena(normalizer_output)
                    elif doc_type == DocumentType.SETTLEMENT_LETTER:
                        doc = self._generate_settlement_letter(normalizer_output)
                    else:
                        # Fallback: create placeholder document
                        doc = DraftDocument(
                            document_type=doc_type,
                            title=f"{doc_type.value} - {plan.judgment_id}",
                            content=f"[Document type {doc_type.value} not yet implemented]",
                            placeholders=[],
                            is_complete=False,
                        )

                    documents.append(doc)

            # Calculate total filing fees
            total_fees = sum(FILING_FEES.get(doc.document_type, Decimal("0")) for doc in documents)

            # Generate cover letter
            cover_letter = self._generate_cover_letter(
                normalizer_output, plan.strategy_name, len(documents)
            )

            # Generate filing checklist
            filing_checklist = self._generate_filing_checklist(documents)

            # Build packet
            packet = DraftPacket(
                packet_id=packet_id,
                judgment_id=plan.judgment_id,
                plan_id=plan.plan_id,
                documents=documents,
                cover_letter=cover_letter,
                filing_checklist=filing_checklist,
                total_filing_fees=total_fees,
            )

            output = DrafterOutput(
                packet=packet,
                drafted_at=datetime.utcnow(),
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

    async def _llm_generate_document(self, doc_type: DocumentType, context: dict) -> str:
        """
        TODO: LLM integration for document generation.

        Use case: Generate customized document content based on
        case specifics and legal requirements.

        Args:
            doc_type: Type of document to generate
            context: Case context and data

        Returns:
            Generated document content

        Implementation notes:
            - Use Claude or GPT-4 for legal document drafting
            - Include NY legal form requirements
            - Maintain professional legal language
        """
        # TODO: Implement LLM call
        logger.debug("[Drafter] LLM document generation not implemented")
        return ""

    async def _llm_review_document(self, document: DraftDocument) -> list[str]:
        """
        TODO: LLM integration for document review.

        Use case: Review generated document for completeness,
        accuracy, and legal compliance.

        Args:
            document: Document to review

        Returns:
            List of issues or suggestions

        Implementation notes:
            - Check for missing required elements
            - Verify legal citations
            - Flag potential issues
        """
        # TODO: Implement LLM call
        logger.debug("[Drafter] LLM document review not implemented")
        return []
