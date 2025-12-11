"""
Dragonfly Engine - Column Mapper Utility

Fuzzy matching utility for mapping messy CSV column headers to canonical
schema fields. Uses multiple strategies:
1. Exact match (case-insensitive)
2. Pattern matching (regex)
3. Fuzzy string matching (Levenshtein distance)
4. Token-based matching (word overlap)

This module provides a generic column mapper that can be used with any
data source, not just FOIL.

Usage:
    from backend.services.column_mapper import ColumnMapper, ColumnMappingResult

    mapper = ColumnMapper()
    result = mapper.map_columns(df.columns.tolist())

    # Check confidence
    if result.confidence < 70:
        # Queue for human review

    # Use mapping
    canonical_col = result.raw_to_canonical.get("Def. Name")  # -> "defendant_name"
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


# =============================================================================
# Constants
# =============================================================================

# Default canonical fields and their possible variations
DEFAULT_CANONICAL_PATTERNS: Dict[str, Dict[str, Any]] = {
    "case_number": {
        "exact_matches": [
            "case number",
            "case no",
            "case #",
            "caseno",
            "case_number",
            "index no",
            "index number",
            "docket no",
            "docket number",
            "case id",
            "file number",
            "file no",
        ],
        "patterns": [
            r"(?i)^case[\s_.-]?(?:no|num|number|#|id)?\.?$",
            r"(?i)^docket[\s_.-]?(?:no|num|number)?$",
            r"(?i)^index[\s_.-]?(?:no|num|number)?$",
            r"(?i)^file[\s_.-]?(?:no|num|number)?$",
        ],
        "tokens": ["case", "docket", "index", "number", "no"],
        "required": True,
        "weight": 1.5,  # Higher weight for required fields
    },
    "defendant_name": {
        "exact_matches": [
            "defendant",
            "defendant name",
            "def name",
            "def. name",
            "defname",
            "def_name",
            "debtor",
            "debtor name",
            "judgment debtor",
        ],
        "patterns": [
            r"(?i)^def(?:endant)?[\s_.-]?(?:name)?$",
            r"(?i)^debtor[\s_.-]?(?:name)?$",
            r"(?i)^judgment[\s_.-]?debtor$",
        ],
        "tokens": ["defendant", "def", "debtor", "name"],
        "required": False,
        "weight": 1.0,
    },
    "plaintiff_name": {
        "exact_matches": [
            "plaintiff",
            "plaintiff name",
            "plf name",
            "plf. name",
            "plfname",
            "plf_name",
            "creditor",
            "creditor name",
            "judgment creditor",
        ],
        "patterns": [
            r"(?i)^pl(?:ain)?t(?:iff)?[\s_.-]?(?:name)?$",
            r"(?i)^plf\.?\s*(?:name)?$",
            r"(?i)^creditor[\s_.-]?(?:name)?$",
            r"(?i)^judgment[\s_.-]?creditor$",
        ],
        "tokens": ["plaintiff", "plf", "creditor", "name"],
        "required": False,
        "weight": 1.0,
    },
    "judgment_amount": {
        "exact_matches": [
            "judgment amount",
            "amount",
            "amt",
            "judgment amt",
            "judgmentamt",
            "judgment_amount",
            "total",
            "principal",
            "balance",
            "original amount",
        ],
        "patterns": [
            r"(?i)^(?:judgment[\s_.-]?)?(?:amt|amount)$",
            r"(?i)^total[\s_.-]?(?:judgment|amt|amount)?$",
            r"(?i)^principal$",
            r"(?i)^balance$",
        ],
        "tokens": ["judgment", "amount", "amt", "total", "principal"],
        "required": True,
        "weight": 1.5,
    },
    "filing_date": {
        "exact_matches": [
            "filing date",
            "date filed",
            "filed date",
            "file date",
            "filingdate",
            "filing_date",
            "date_filed",
        ],
        "patterns": [
            r"(?i)^(?:date[\s_.-]?)?filed$",
            r"(?i)^filing[\s_.-]?date$",
            r"(?i)^file[\s_.-]?date$",
        ],
        "tokens": ["filing", "filed", "date", "file"],
        "required": False,
        "weight": 0.8,
    },
    "judgment_date": {
        "exact_matches": [
            "judgment date",
            "jdgmt date",
            "jdgmtdate",
            "judgment_date",
            "entry date",
            "date of judgment",
            "date entered",
        ],
        "patterns": [
            r"(?i)^(?:jud?g(?:e?ment)?[\s_.-]?)?date$",
            r"(?i)^entry[\s_.-]?date$",
            r"(?i)^jdgmt[\s_.-]?date$",
            r"(?i)^date[\s_.-]?(?:of[\s_.-]?)?judgment$",
        ],
        "tokens": ["judgment", "jdgmt", "entry", "date"],
        "required": False,
        "weight": 0.8,
    },
    "county": {
        "exact_matches": [
            "county",
            "venue",
            "jurisdiction",
            "location",
        ],
        "patterns": [
            r"(?i)^county$",
            r"(?i)^venue$",
            r"(?i)^jurisdiction$",
        ],
        "tokens": ["county", "venue", "jurisdiction"],
        "required": False,
        "weight": 0.6,
    },
    "court": {
        "exact_matches": [
            "court",
            "court name",
            "courtname",
            "court_name",
            "tribunal",
        ],
        "patterns": [
            r"(?i)^court(?:[\s_.-]?name)?$",
            r"(?i)^tribunal$",
        ],
        "tokens": ["court", "tribunal"],
        "required": False,
        "weight": 0.6,
    },
    "defendant_address": {
        "exact_matches": [
            "defendant address",
            "def address",
            "def. address",
            "debtor address",
            "address",
            "def_address",
        ],
        "patterns": [
            r"(?i)^def(?:endant)?[\s_.-]?addr(?:ess)?$",
            r"(?i)^debtor[\s_.-]?addr(?:ess)?$",
            r"(?i)^address$",
        ],
        "tokens": ["defendant", "def", "debtor", "address", "addr"],
        "required": False,
        "weight": 0.5,
    },
}

# Minimum thresholds
DEFAULT_FUZZY_THRESHOLD = 80  # Minimum similarity for fuzzy match
DEFAULT_TOKEN_THRESHOLD = 0.5  # Minimum token overlap ratio


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class ColumnMatch:
    """Result of matching a single column."""

    raw_column: str
    canonical_field: Optional[str]
    match_type: str  # "exact", "pattern", "fuzzy", "token", "none"
    similarity_score: float  # 0-100
    matched_by: str  # What triggered the match (e.g., pattern string, token)


@dataclass
class ColumnMappingResult:
    """Complete result of column mapping."""

    raw_to_canonical: Dict[str, str]  # {"Def. Name": "defendant_name"}
    canonical_to_raw: Dict[str, str]  # {"defendant_name": "Def. Name"}
    unmapped_columns: List[str]  # Columns that couldn't be mapped
    match_details: List[ColumnMatch]  # Details of each match
    confidence: float  # 0-100 overall confidence
    required_missing: List[str]  # Required fields that are missing
    warnings: List[str]  # Warnings about low-confidence matches

    @property
    def is_valid(self) -> bool:
        """Check if mapping has minimum required fields."""
        required = {"case_number", "judgment_amount"}
        return required.issubset(set(self.canonical_to_raw.keys()))

    @property
    def needs_review(self) -> bool:
        """Check if mapping needs human review."""
        return self.confidence < 70 or len(self.required_missing) > 0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "raw_to_canonical": self.raw_to_canonical,
            "canonical_to_raw": self.canonical_to_raw,
            "unmapped_columns": self.unmapped_columns,
            "confidence": self.confidence,
            "required_missing": self.required_missing,
            "warnings": self.warnings,
            "is_valid": self.is_valid,
            "needs_review": self.needs_review,
            "match_details": [
                {
                    "raw_column": m.raw_column,
                    "canonical_field": m.canonical_field,
                    "match_type": m.match_type,
                    "similarity_score": m.similarity_score,
                    "matched_by": m.matched_by,
                }
                for m in self.match_details
            ],
        }


# =============================================================================
# Column Mapper Class
# =============================================================================


class ColumnMapper:
    """
    Maps CSV column headers to canonical schema fields using fuzzy matching.

    Supports:
    - Exact matching (case-insensitive)
    - Regex pattern matching
    - Fuzzy string matching (using difflib)
    - Token-based matching (word overlap)
    """

    def __init__(
        self,
        canonical_patterns: Optional[Dict[str, Dict[str, Any]]] = None,
        fuzzy_threshold: int = DEFAULT_FUZZY_THRESHOLD,
        token_threshold: float = DEFAULT_TOKEN_THRESHOLD,
        explicit_mapping: Optional[Dict[str, str]] = None,
    ):
        """
        Initialize ColumnMapper.

        Args:
            canonical_patterns: Custom pattern definitions for canonical fields
            fuzzy_threshold: Minimum similarity score (0-100) for fuzzy matching
            token_threshold: Minimum token overlap ratio (0-1) for token matching
            explicit_mapping: Explicit raw->canonical mapping to apply first
        """
        self.canonical_patterns = canonical_patterns or DEFAULT_CANONICAL_PATTERNS
        self.fuzzy_threshold = fuzzy_threshold
        self.token_threshold = token_threshold
        self.explicit_mapping = explicit_mapping or {}

    def map_columns(
        self,
        raw_columns: List[str],
        agency_template: Optional[str] = None,
    ) -> ColumnMappingResult:
        """
        Map raw column names to canonical field names.

        Args:
            raw_columns: List of column names from the raw CSV
            agency_template: Optional agency-specific template name

        Returns:
            ColumnMappingResult with all mappings and confidence scores
        """
        raw_to_canonical: Dict[str, str] = {}
        canonical_to_raw: Dict[str, str] = {}
        unmapped_columns: List[str] = []
        match_details: List[ColumnMatch] = []
        warnings: List[str] = []

        # Track which canonical fields have been assigned
        assigned_canonical: Set[str] = set()

        # First pass: Apply explicit mappings
        for raw_col, canonical_col in self.explicit_mapping.items():
            if raw_col in raw_columns and canonical_col in self.canonical_patterns:
                raw_to_canonical[raw_col] = canonical_col
                canonical_to_raw[canonical_col] = raw_col
                assigned_canonical.add(canonical_col)
                match_details.append(
                    ColumnMatch(
                        raw_column=raw_col,
                        canonical_field=canonical_col,
                        match_type="explicit",
                        similarity_score=100.0,
                        matched_by="explicit_mapping",
                    )
                )

        # Second pass: Match remaining columns
        for raw_col in raw_columns:
            if raw_col in raw_to_canonical:
                continue  # Already mapped

            match = self._find_best_match(raw_col, assigned_canonical)
            match_details.append(match)

            if match.canonical_field:
                raw_to_canonical[raw_col] = match.canonical_field
                canonical_to_raw[match.canonical_field] = raw_col
                assigned_canonical.add(match.canonical_field)

                # Add warning for low-confidence fuzzy matches
                if match.match_type == "fuzzy" and match.similarity_score < 85:
                    warnings.append(
                        f"Low confidence match: '{raw_col}' -> '{match.canonical_field}' "
                        f"({match.similarity_score:.1f}%)"
                    )
            else:
                unmapped_columns.append(raw_col)

        # Calculate confidence score
        required_missing = self._get_required_missing(canonical_to_raw)
        confidence = self._calculate_confidence(match_details, raw_columns, required_missing)

        return ColumnMappingResult(
            raw_to_canonical=raw_to_canonical,
            canonical_to_raw=canonical_to_raw,
            unmapped_columns=unmapped_columns,
            match_details=match_details,
            confidence=confidence,
            required_missing=required_missing,
            warnings=warnings,
        )

    def _find_best_match(
        self,
        raw_col: str,
        assigned_canonical: Set[str],
    ) -> ColumnMatch:
        """
        Find the best canonical field match for a raw column.

        Tries matching strategies in order:
        1. Exact match
        2. Pattern match
        3. Fuzzy match
        4. Token match
        """
        normalized = self._normalize_column_name(raw_col)

        best_match: Optional[ColumnMatch] = None
        best_score = 0.0

        for canonical_field, config in self.canonical_patterns.items():
            if canonical_field in assigned_canonical:
                continue  # Already assigned

            # Try exact match
            exact_matches = [
                self._normalize_column_name(e) for e in config.get("exact_matches", [])
            ]
            if normalized in exact_matches:
                return ColumnMatch(
                    raw_column=raw_col,
                    canonical_field=canonical_field,
                    match_type="exact",
                    similarity_score=100.0,
                    matched_by=f"exact:{normalized}",
                )

            # Try pattern match
            for pattern in config.get("patterns", []):
                if re.match(pattern, raw_col):
                    return ColumnMatch(
                        raw_column=raw_col,
                        canonical_field=canonical_field,
                        match_type="pattern",
                        similarity_score=95.0,
                        matched_by=f"pattern:{pattern}",
                    )

            # Try fuzzy match
            fuzzy_score = self._fuzzy_match_score(normalized, exact_matches)
            if fuzzy_score >= self.fuzzy_threshold and fuzzy_score > best_score:
                best_match = ColumnMatch(
                    raw_column=raw_col,
                    canonical_field=canonical_field,
                    match_type="fuzzy",
                    similarity_score=fuzzy_score,
                    matched_by=f"fuzzy:{fuzzy_score:.1f}%",
                )
                best_score = fuzzy_score

            # Try token match (lower priority than fuzzy)
            tokens = config.get("tokens", [])
            token_score = self._token_match_score(normalized, tokens)
            if token_score >= self.token_threshold:
                # Convert token score to 0-100 scale
                token_pct = token_score * 100
                if token_pct > best_score and best_score < self.fuzzy_threshold:
                    best_match = ColumnMatch(
                        raw_column=raw_col,
                        canonical_field=canonical_field,
                        match_type="token",
                        similarity_score=token_pct,
                        matched_by=f"token:{token_score:.2f}",
                    )
                    best_score = token_pct

        # Return best match or no-match result
        if best_match:
            return best_match

        return ColumnMatch(
            raw_column=raw_col,
            canonical_field=None,
            match_type="none",
            similarity_score=0.0,
            matched_by="no_match",
        )

    def _normalize_column_name(self, name: str) -> str:
        """Normalize column name for comparison."""
        # Lowercase, strip, replace various separators with space
        normalized = name.lower().strip()
        normalized = re.sub(r"[_.-]+", " ", normalized)
        normalized = re.sub(r"\s+", " ", normalized)
        return normalized

    def _fuzzy_match_score(
        self,
        normalized_col: str,
        candidates: List[str],
    ) -> float:
        """
        Calculate fuzzy match score using SequenceMatcher.

        Returns the best match score (0-100).
        """
        if not candidates:
            return 0.0

        best_score = 0.0
        for candidate in candidates:
            ratio = SequenceMatcher(None, normalized_col, candidate).ratio()
            score = ratio * 100
            if score > best_score:
                best_score = score

        return best_score

    def _token_match_score(
        self,
        normalized_col: str,
        tokens: List[str],
    ) -> float:
        """
        Calculate token overlap score.

        Returns overlap ratio (0-1).
        """
        if not tokens:
            return 0.0

        col_tokens = set(normalized_col.split())
        token_set = set(t.lower() for t in tokens)

        if not col_tokens:
            return 0.0

        overlap = col_tokens.intersection(token_set)
        return len(overlap) / len(col_tokens)

    def _get_required_missing(
        self,
        canonical_to_raw: Dict[str, str],
    ) -> List[str]:
        """Get list of required fields that are missing."""
        missing = []
        for canonical_field, config in self.canonical_patterns.items():
            if config.get("required", False):
                if canonical_field not in canonical_to_raw:
                    missing.append(canonical_field)
        return missing

    def _calculate_confidence(
        self,
        match_details: List[ColumnMatch],
        raw_columns: List[str],
        required_missing: List[str],
    ) -> float:
        """
        Calculate overall confidence score (0-100).

        Factors:
        - Percentage of columns mapped
        - Quality of matches (exact > pattern > fuzzy > token)
        - Whether required fields are present
        """
        if not raw_columns:
            return 0.0

        # Count by match type with quality weights
        type_weights = {
            "explicit": 1.0,
            "exact": 1.0,
            "pattern": 0.95,
            "fuzzy": 0.7,
            "token": 0.5,
            "none": 0.0,
        }

        total_weight = 0.0
        max_weight = 0.0

        for match in match_details:
            weight = type_weights.get(match.match_type, 0.0)
            # Apply field importance weight
            if match.canonical_field:
                field_config = self.canonical_patterns.get(match.canonical_field, {})
                field_weight = field_config.get("weight", 1.0)
                weight *= field_weight
                max_weight += field_weight
            else:
                max_weight += 1.0

            total_weight += weight

        # Base confidence from match quality
        base_confidence = (total_weight / max_weight * 100) if max_weight > 0 else 0.0

        # Penalty for missing required fields (each missing = -15%)
        required_penalty = len(required_missing) * 15

        final_confidence = max(0.0, base_confidence - required_penalty)
        return round(final_confidence, 1)


# =============================================================================
# Convenience Functions
# =============================================================================


def map_columns_fuzzy(
    columns: List[str],
    fuzzy_threshold: int = 80,
    explicit_mapping: Optional[Dict[str, str]] = None,
) -> ColumnMappingResult:
    """
    Convenience function to map columns with fuzzy matching.

    Args:
        columns: List of column names
        fuzzy_threshold: Minimum similarity score for fuzzy matches
        explicit_mapping: Optional explicit mappings to apply first

    Returns:
        ColumnMappingResult
    """
    mapper = ColumnMapper(
        fuzzy_threshold=fuzzy_threshold,
        explicit_mapping=explicit_mapping,
    )
    return mapper.map_columns(columns)


def suggest_column_mapping(
    raw_column: str,
    top_n: int = 3,
) -> List[Tuple[str, float]]:
    """
    Suggest possible canonical fields for a single column.

    Args:
        raw_column: Raw column name to match
        top_n: Number of suggestions to return

    Returns:
        List of (canonical_field, score) tuples sorted by score
    """
    mapper = ColumnMapper(fuzzy_threshold=0)  # Accept all matches

    suggestions: List[Tuple[str, float]] = []
    normalized = mapper._normalize_column_name(raw_column)

    for canonical_field, config in mapper.canonical_patterns.items():
        exact_matches = [mapper._normalize_column_name(e) for e in config.get("exact_matches", [])]

        # Check exact
        if normalized in exact_matches:
            suggestions.append((canonical_field, 100.0))
            continue

        # Check pattern
        for pattern in config.get("patterns", []):
            if re.match(pattern, raw_column):
                suggestions.append((canonical_field, 95.0))
                break
        else:
            # Check fuzzy
            fuzzy_score = mapper._fuzzy_match_score(normalized, exact_matches)
            if fuzzy_score > 30:  # Only include reasonable suggestions
                suggestions.append((canonical_field, fuzzy_score))

    # Sort by score descending and return top N
    suggestions.sort(key=lambda x: x[1], reverse=True)
    return suggestions[:top_n]
