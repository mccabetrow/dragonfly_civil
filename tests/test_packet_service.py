"""
Tests for Packet Service

Tests the Document Assembly Engine:
- calculate_interest: Interest calculation logic
- load_judgment_context: Judgment data loading
- generate_packet: End-to-end generation (with mocked storage)
"""

import tempfile
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.services.packet_service import (
    PacketError,
    calculate_interest,
    format_currency,
    format_date,
    generate_packet,
    load_judgment_context,
)

# =============================================================================
# format_currency tests
# =============================================================================


class TestFormatCurrency:
    """Tests for currency formatting helper."""

    def test_formats_positive_amount(self):
        """Should format positive amounts correctly."""
        assert format_currency(Decimal("1234.56")) == "$1,234.56"
        assert format_currency(Decimal("25000.00")) == "$25,000.00"
        assert format_currency(Decimal("0.99")) == "$0.99"

    def test_formats_large_amounts(self):
        """Should handle large amounts with commas."""
        assert format_currency(Decimal("1234567.89")) == "$1,234,567.89"

    def test_handles_none(self):
        """Should return $0.00 for None."""
        assert format_currency(None) == "$0.00"

    def test_handles_zero(self):
        """Should format zero correctly."""
        assert format_currency(Decimal("0")) == "$0.00"


# =============================================================================
# format_date tests
# =============================================================================


class TestFormatDate:
    """Tests for date formatting helper."""

    def test_formats_date(self):
        """Should format dates as MM/DD/YYYY."""
        assert format_date(date(2024, 10, 15)) == "10/15/2024"
        assert format_date(date(2023, 1, 5)) == "01/05/2023"

    def test_handles_none(self):
        """Should return empty string for None."""
        assert format_date(None) == ""


# =============================================================================
# calculate_interest tests
# =============================================================================


class TestCalculateInterest:
    """Tests for simple interest calculation."""

    def test_calculates_one_year_interest(self):
        """Should calculate interest for one full year."""
        judgment_date = date.today() - timedelta(days=365)
        result = calculate_interest(
            judgment_amount=Decimal("10000"),
            judgment_date=judgment_date,
            annual_rate=Decimal("9.0"),
        )

        # 10000 * 0.09 * 1 = 900
        assert result["interest_amount"] == Decimal("900.00")
        assert result["total_with_interest"] == Decimal("10900.00")
        assert result["interest_amount_formatted"] == "$900.00"
        assert result["total_with_interest_formatted"] == "$10,900.00"

    def test_calculates_partial_year_interest(self):
        """Should calculate interest for partial year."""
        # 6 months = 182.5 days ≈ 0.5 years
        judgment_date = date.today() - timedelta(days=183)
        result = calculate_interest(
            judgment_amount=Decimal("10000"),
            judgment_date=judgment_date,
            annual_rate=Decimal("9.0"),
        )

        # Interest should be roughly half of full year
        assert Decimal("400") < result["interest_amount"] < Decimal("500")

    def test_handles_none_date(self):
        """Should return zero interest for None date."""
        result = calculate_interest(
            judgment_amount=Decimal("10000"),
            judgment_date=None,
            annual_rate=Decimal("9.0"),
        )

        assert result["interest_amount"] == Decimal("0")
        assert result["total_with_interest"] == Decimal("10000")
        assert result["days_since_judgment"] == 0

    def test_handles_future_date(self):
        """Should clamp negative days to zero."""
        future_date = date.today() + timedelta(days=30)
        result = calculate_interest(
            judgment_amount=Decimal("10000"),
            judgment_date=future_date,
            annual_rate=Decimal("9.0"),
        )

        assert result["interest_amount"] == Decimal("0")
        assert result["days_since_judgment"] == 0

    def test_handles_zero_amount(self):
        """Should handle zero judgment amount."""
        result = calculate_interest(
            judgment_amount=Decimal("0"),
            judgment_date=date.today() - timedelta(days=365),
            annual_rate=Decimal("9.0"),
        )

        assert result["interest_amount"] == Decimal("0")
        assert result["total_with_interest"] == Decimal("0")

    def test_tracks_days_elapsed(self):
        """Should correctly track days since judgment."""
        judgment_date = date.today() - timedelta(days=100)
        result = calculate_interest(
            judgment_amount=Decimal("10000"),
            judgment_date=judgment_date,
            annual_rate=Decimal("9.0"),
        )

        assert result["days_since_judgment"] == 100
        assert 0.27 < result["years_since_judgment"] < 0.28


# =============================================================================
# load_judgment_context tests
# =============================================================================


class TestLoadJudgmentContext:
    """Tests for judgment context loading."""

    @pytest.mark.asyncio
    async def test_raises_error_for_missing_judgment(self):
        """Should raise PacketError if judgment not found."""
        mock_cursor = AsyncMock()
        mock_cursor.fetchone.return_value = None
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock()

        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        with patch("backend.services.packet_service.get_pool", return_value=mock_conn):
            with pytest.raises(PacketError, match="not found"):
                await load_judgment_context(99999)

    @pytest.mark.asyncio
    async def test_raises_error_for_no_db_connection(self):
        """Should raise PacketError if DB not available."""
        with patch("backend.services.packet_service.get_pool", return_value=None):
            with pytest.raises(PacketError, match="not available"):
                await load_judgment_context(1)

    @pytest.mark.asyncio
    async def test_loads_judgment_successfully(self):
        """Should load and format judgment data correctly."""
        mock_row = (
            123,  # id
            "CV-2024-001",  # case_number
            "John Plaintiff",  # plaintiff_name
            "Jane Defendant",  # defendant_name
            Decimal("25000.00"),  # judgment_amount
            date(2024, 6, 15),  # entry_date
            "123 Main St",  # defendant_address
            "555-1234",  # defendant_phone
            "jane@example.com",  # defendant_email
            "Active",  # status
            "Some notes",  # notes
        )

        mock_cursor = AsyncMock()
        mock_cursor.fetchone.return_value = mock_row
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock()

        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        with patch("backend.services.packet_service.get_pool", return_value=mock_conn):
            context = await load_judgment_context(123)

        assert context["judgment_id"] == 123
        assert context["case_number"] == "CV-2024-001"
        assert context["plaintiff_name"] == "John Plaintiff"
        assert context["defendant_name"] == "Jane Defendant"
        assert context["judgment_amount"] == Decimal("25000.00")
        assert context["judgment_amount_formatted"] == "$25,000.00"
        assert context["judgment_date"] == date(2024, 6, 15)
        assert context["judgment_date_formatted"] == "06/15/2024"


# =============================================================================
# generate_packet tests
# =============================================================================


class TestGeneratePacket:
    """Tests for end-to-end packet generation."""

    @pytest.mark.asyncio
    async def test_raises_error_for_invalid_packet_type(self):
        """Should raise PacketError for invalid packet type."""
        with pytest.raises(PacketError, match="Invalid packet type"):
            await generate_packet(1, "invalid_type")  # type: ignore

    @pytest.mark.asyncio
    async def test_raises_error_for_missing_template(self):
        """Should raise PacketError if template file doesn't exist."""
        # Mock the judgment loading to succeed
        mock_context = {
            "judgment_id": 1,
            "case_number": "TEST-001",
            "plaintiff_name": "Test",
            "defendant_name": "Test",
            "judgment_amount": Decimal("1000"),
            "judgment_date": date.today(),
            "interest_rate_percent": 9.0,
        }

        with patch(
            "backend.services.packet_service.load_judgment_context",
            return_value=mock_context,
        ):
            with patch(
                "backend.services.packet_service.TEMPLATES_DIR",
                Path("/nonexistent/path"),
            ):
                with pytest.raises(PacketError, match="Template not found"):
                    await generate_packet(1, "income_execution_ny")

    @pytest.mark.asyncio
    async def test_generates_packet_with_mock_template(self):
        """Should generate packet with a mock template."""
        # Create a temporary minimal DOCX for testing
        # Note: This requires a valid DOCX file structure
        # For CI, we'd typically skip this or use a fixture

        mock_context = {
            "judgment_id": 1,
            "case_number": "TEST-001",
            "plaintiff_name": "Test Plaintiff",
            "defendant_name": "Test Defendant",
            "judgment_amount": Decimal("10000"),
            "judgment_amount_formatted": "$10,000.00",
            "judgment_date": date(2024, 6, 15),
            "judgment_date_formatted": "06/15/2024",
            "judgment_date_iso": "2024-06-15",
            "defendant_address": "",
            "defendant_phone": "",
            "defendant_email": "",
            "status": "Active",
            "notes": "",
            "employer_name": "",
            "employer_address": "",
            "bank_name": "",
            "bank_address": "",
            "interest_rate_percent": 9.0,
        }

        mock_interest = {
            "interest_amount": Decimal("450"),
            "interest_amount_formatted": "$450.00",
            "total_with_interest": Decimal("10450"),
            "total_with_interest_formatted": "$10,450.00",
            "days_since_judgment": 180,
            "years_since_judgment": 0.49,
        }

        mock_signed_url = {"signedURL": "https://storage.example.com/signed/test.docx"}

        mock_storage = MagicMock()
        mock_storage.upload.return_value = {}
        mock_storage.create_signed_url.return_value = mock_signed_url

        mock_supabase = MagicMock()
        mock_supabase.storage.from_.return_value = mock_storage

        # Create a minimal valid DOCX template for testing
        with tempfile.TemporaryDirectory() as tmpdir:
            # We'll skip full DOCX creation since it requires python-docx
            # In real tests, you'd create a fixture template

            with patch(
                "backend.services.packet_service.load_judgment_context",
                AsyncMock(return_value=mock_context),
            ):
                with patch(
                    "backend.services.packet_service.calculate_interest",
                    return_value=mock_interest,
                ):
                    with patch(
                        "backend.services.packet_service.get_supabase_client",
                        return_value=mock_supabase,
                    ):
                        # For this test, also mock DocxTemplate to avoid needing a real file
                        mock_doc = MagicMock()
                        mock_doc.render = MagicMock()
                        mock_doc.save = MagicMock()

                        with patch(
                            "backend.services.packet_service.DocxTemplate",
                            return_value=mock_doc,
                        ):
                            with patch(
                                "backend.services.packet_service.TEMPLATES_DIR",
                                Path(tmpdir),
                            ):
                                # Create a dummy template file
                                dummy_template = (
                                    Path(tmpdir) / "income_execution_ny.docx"
                                )
                                dummy_template.touch()

                                url = await generate_packet(1, "income_execution_ny")

                                assert (
                                    url
                                    == "https://storage.example.com/signed/test.docx"
                                )
                                mock_doc.render.assert_called_once()
                                mock_storage.upload.assert_called_once()


# =============================================================================
# Integration test (requires real DB - skip in CI)
# =============================================================================


@pytest.mark.skip(reason="Integration test - requires real database connection")
class TestPacketServiceIntegration:
    """Integration tests that require a real database."""

    @pytest.mark.asyncio
    async def test_full_workflow(self):
        """Test full packet generation workflow with real DB."""
        # This would be run manually against a dev database
        pass
