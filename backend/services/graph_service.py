"""
Dragonfly Engine - Graph Service

Business logic for building and querying the Judgment Intelligence Graph.
Converts flat judgment rows into a graph of entities (people, companies, courts)
and relationships between them.

This module is designed to be called from ingest service after each judgment
is inserted. Failures here should NEVER break ingestion.
"""

import logging
import re
from typing import Optional
from uuid import UUID

import psycopg

logger = logging.getLogger(__name__)

# Patterns to detect company names
COMPANY_PATTERNS = re.compile(
    r"\b(LLC|L\.L\.C\.?|INC\.?|INCORPORATED|CORP\.?|CORPORATION|LTD\.?|LIMITED|LP|L\.P\.?|LLP|L\.L\.P\.?|CO\.?|COMPANY|ENTERPRISES|HOLDINGS|GROUP|PARTNERS|ASSOCIATES|SOLUTIONS|SERVICES|CONSULTING)\b",
    re.IGNORECASE,
)


def normalize_name(name: str | None) -> str:
    """
    Normalize a name for entity matching.

    - Trim whitespace
    - Collapse internal spaces
    - Uppercase
    - Return empty string if input is falsy

    Args:
        name: The raw name to normalize

    Returns:
        Normalized name (uppercase, trimmed, collapsed spaces) or empty string
    """
    if not name:
        return ""

    # Strip leading/trailing whitespace
    normalized = str(name).strip()

    # Collapse multiple spaces to single space
    normalized = re.sub(r"\s+", " ", normalized)

    # Uppercase for consistent matching
    return normalized.upper()


def infer_entity_type(name: str) -> str:
    """
    Infer entity type from name using simple heuristics.

    If the name contains company indicators (LLC, INC, CORP, etc.),
    classify as 'company'. Otherwise, classify as 'person'.

    Args:
        name: The entity name to classify

    Returns:
        'company' or 'person'
    """
    if not name:
        return "person"

    if COMPANY_PATTERNS.search(name):
        return "company"

    return "person"


async def get_or_create_entity(
    name: str,
    entity_type: str,
    conn: "psycopg.AsyncConnection",
    metadata: dict | None = None,
) -> Optional[UUID]:
    """
    Get or create an entity in the intelligence graph.

    Uses the UNIQUE constraint on (normalized_name, type) to handle
    concurrent inserts safely. If an entity already exists, returns its ID.

    Args:
        name: The raw entity name
        entity_type: The entity type ('person', 'company', 'court', 'address', 'attorney')
        conn: Database connection (inside a transaction)
        metadata: Optional metadata dict for the entity

    Returns:
        Entity UUID if successful, None if name is blank

    Raises:
        Nothing - errors are logged and None is returned
    """
    if not name or not name.strip():
        return None

    normalized = normalize_name(name)
    if not normalized:
        return None

    metadata_json = metadata or {}

    try:
        # First try to find existing entity
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT id FROM intelligence.entities
                WHERE normalized_name = %s AND type = %s::intelligence.entity_type
                """,
                (normalized, entity_type),
            )
            row = await cur.fetchone()
            if row:
                return row[0]

            # Not found - try to insert
            try:
                await cur.execute(
                    """
                    INSERT INTO intelligence.entities (type, raw_name, normalized_name, metadata)
                    VALUES (%s::intelligence.entity_type, %s, %s, %s::jsonb)
                    RETURNING id
                    """,
                    (
                        entity_type,
                        name.strip(),
                        normalized,
                        psycopg.types.json.Json(metadata_json),
                    ),
                )
                row = await cur.fetchone()
                if row:
                    logger.debug(
                        "Created entity: type=%s, normalized_name=%s, id=%s",
                        entity_type,
                        normalized,
                        row[0],
                    )
                    return row[0]

            except psycopg.errors.UniqueViolation:
                # Race condition - another process inserted first
                # Re-query to get the existing ID
                await cur.execute(
                    """
                    SELECT id FROM intelligence.entities
                    WHERE normalized_name = %s AND type = %s::intelligence.entity_type
                    """,
                    (normalized, entity_type),
                )
                row = await cur.fetchone()
                if row:
                    logger.debug(
                        "Entity already exists (concurrent insert): type=%s, normalized_name=%s, id=%s",
                        entity_type,
                        normalized,
                        row[0],
                    )
                    return row[0]

    except Exception as e:
        logger.error(
            "Failed to get_or_create_entity: type=%s, name=%s, error=%s",
            entity_type,
            name,
            e,
        )
        return None

    return None


async def create_relationship(
    source_entity_id: UUID,
    target_entity_id: UUID,
    relation: str,
    source_judgment_id: int,
    conn: "psycopg.AsyncConnection",
    confidence: float = 1.0,
) -> Optional[UUID]:
    """
    Create a relationship between two entities.

    Args:
        source_entity_id: The source entity UUID
        target_entity_id: The target entity UUID
        relation: The relationship type ('plaintiff_in', 'defendant_in', etc.)
        source_judgment_id: The judgment ID that established this relationship
        conn: Database connection (inside a transaction)
        confidence: Confidence score (0.0 to 1.0)

    Returns:
        Relationship UUID if successful, None on error
    """
    try:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO intelligence.relationships
                    (source_entity_id, target_entity_id, relation, source_judgment_id, confidence)
                VALUES (%s, %s, %s::intelligence.relation_type, %s, %s)
                RETURNING id
                """,
                (
                    source_entity_id,
                    target_entity_id,
                    relation,
                    source_judgment_id,
                    confidence,
                ),
            )
            row = await cur.fetchone()
            if row:
                logger.debug(
                    "Created relationship: %s -[%s]-> %s (judgment=%s)",
                    source_entity_id,
                    relation,
                    target_entity_id,
                    source_judgment_id,
                )
                return row[0]

    except Exception as e:
        logger.error(
            "Failed to create_relationship: %s -[%s]-> %s, error=%s",
            source_entity_id,
            relation,
            target_entity_id,
            e,
        )
        return None

    return None


async def build_judgment_graph(
    judgment_id: int, conn: "psycopg.AsyncConnection"
) -> bool:
    """
    Build graph entities and relationships for a single judgment.

    Given a judgment_id:
    1. Load the judgment row from public.judgments
    2. Create entities for plaintiff, defendant, and court
    3. Create relationships between them

    All operations are performed within the provided connection's transaction.

    Args:
        judgment_id: The judgment ID to process
        conn: Database connection (caller manages transaction)

    Returns:
        True if graph was built successfully, False on error
    """
    try:
        async with conn.cursor() as cur:
            # Load the judgment
            await cur.execute(
                """
                SELECT id, plaintiff_name, defendant_name, source_file, judgment_amount
                FROM public.judgments
                WHERE id = %s
                """,
                (judgment_id,),
            )
            row = await cur.fetchone()

            if not row:
                logger.warning("Judgment not found: %s", judgment_id)
                return False

            jid, plaintiff_name, defendant_name, source_file, judgment_amount = row

            # Extract court from source_file (format: "court|filename" or just "filename")
            court_name = None
            if source_file:
                parts = source_file.split("|")
                if len(parts) > 1:
                    court_name = parts[0]

            # Determine entity types using heuristics
            plaintiff_type = (
                infer_entity_type(plaintiff_name) if plaintiff_name else "person"
            )
            defendant_type = (
                infer_entity_type(defendant_name) if defendant_name else "person"
            )

            # Create entities
            plaintiff_entity_id = None
            defendant_entity_id = None
            court_entity_id = None

            if plaintiff_name:
                plaintiff_entity_id = await get_or_create_entity(
                    name=plaintiff_name,
                    entity_type=plaintiff_type,
                    conn=conn,
                    metadata={"role": "plaintiff", "source_judgment_id": judgment_id},
                )

            if defendant_name:
                defendant_entity_id = await get_or_create_entity(
                    name=defendant_name,
                    entity_type=defendant_type,
                    conn=conn,
                    metadata={"role": "defendant", "source_judgment_id": judgment_id},
                )

            if court_name:
                court_entity_id = await get_or_create_entity(
                    name=court_name,
                    entity_type="court",
                    conn=conn,
                    metadata={"source_judgment_id": judgment_id},
                )

            # Create relationships
            # plaintiff -> defendant (plaintiff_in relationship)
            if plaintiff_entity_id and defendant_entity_id:
                await create_relationship(
                    source_entity_id=plaintiff_entity_id,
                    target_entity_id=defendant_entity_id,
                    relation="plaintiff_in",
                    source_judgment_id=judgment_id,
                    conn=conn,
                )

            # defendant -> court (sued_at relationship)
            if defendant_entity_id and court_entity_id:
                await create_relationship(
                    source_entity_id=defendant_entity_id,
                    target_entity_id=court_entity_id,
                    relation="sued_at",
                    source_judgment_id=judgment_id,
                    conn=conn,
                )

            logger.info(
                "Built graph for judgment %s: plaintiff=%s, defendant=%s, court=%s",
                judgment_id,
                plaintiff_entity_id,
                defendant_entity_id,
                court_entity_id,
            )
            return True

    except Exception as e:
        logger.error("Failed to build graph for judgment %s: %s", judgment_id, e)
        return False


async def process_judgment_for_graph(judgment_id: int) -> bool:
    """
    Top-level async function to process a judgment for the intelligence graph.

    Acquires a DB connection, builds the graph within a transaction, and
    handles all errors gracefully. This function NEVER raises - failures
    are logged but do not propagate to avoid breaking ingestion.

    Args:
        judgment_id: The judgment ID to process

    Returns:
        True if processing succeeded, False otherwise
    """
    try:
        # Local import to avoid circular dependencies
        from ..db import get_pool

        conn = await get_pool()
        if conn is None:
            logger.error(
                "Graph build failed for judgment %s: database connection not available",
                judgment_id,
            )
            return False

        # Run within an explicit transaction
        async with conn.transaction():
            result = await build_judgment_graph(judgment_id, conn)

        return result

    except Exception as exc:
        logger.error("Graph build failed for judgment %s: %s", judgment_id, exc)
        # DO NOT re-raise - this must not break ingestion
        return False


async def get_judgment_graph(judgment_id: int) -> dict:
    """
    Retrieve the graph for a specific judgment.

    Finds all relationships where source_judgment_id = judgment_id,
    collects all referenced entity IDs, and returns entities + relationships.

    Args:
        judgment_id: The judgment ID to query

    Returns:
        Dict with 'judgment_id', 'entities', and 'relationships' keys
    """
    try:
        from ..db import get_pool

        conn = await get_pool()
        if conn is None:
            return {"judgment_id": judgment_id, "entities": [], "relationships": []}

        async with conn.cursor() as cur:
            # Get all relationships for this judgment
            await cur.execute(
                """
                SELECT id, source_entity_id, target_entity_id, relation, confidence, source_judgment_id, created_at
                FROM intelligence.relationships
                WHERE source_judgment_id = %s
                """,
                (judgment_id,),
            )
            relationship_rows = await cur.fetchall()

            relationships = []
            entity_ids = set()

            for row in relationship_rows:
                (
                    rel_id,
                    source_id,
                    target_id,
                    relation,
                    confidence,
                    src_jid,
                    created_at,
                ) = row
                relationships.append(
                    {
                        "id": str(rel_id),
                        "source_entity_id": str(source_id),
                        "target_entity_id": str(target_id),
                        "relation": relation,
                        "confidence": confidence,
                        "source_judgment_id": src_jid,
                    }
                )
                entity_ids.add(source_id)
                entity_ids.add(target_id)

            # Get all referenced entities
            entities = []
            if entity_ids:
                placeholders = ", ".join(["%s"] * len(entity_ids))
                await cur.execute(
                    f"""
                    SELECT id, type, raw_name, normalized_name, metadata, created_at
                    FROM intelligence.entities
                    WHERE id IN ({placeholders})
                    """,
                    tuple(entity_ids),
                )
                entity_rows = await cur.fetchall()

                for row in entity_rows:
                    eid, etype, raw_name, normalized_name, metadata, created_at = row
                    entities.append(
                        {
                            "id": str(eid),
                            "type": etype,
                            "raw_name": raw_name,
                            "normalized_name": normalized_name,
                            "metadata": metadata or {},
                        }
                    )

            return {
                "judgment_id": judgment_id,
                "entities": entities,
                "relationships": relationships,
            }

    except Exception as e:
        logger.error("Failed to get graph for judgment %s: %s", judgment_id, e)
        return {"judgment_id": judgment_id, "entities": [], "relationships": []}
