"""
Dragonfly RAG Test - End-to-End Validation

Seeds a test document with embedding and validates the RAG search flow.

Usage:
    python -m tools.test_rag --env dev
    python -m tools.test_rag --env dev --seed-only   # Just seed data
    python -m tools.test_rag --env dev --cleanup     # Remove test data

Requirements:
    - OPENAI_API_KEY in environment
    - RAG migration applied (20260201000000)
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from uuid import uuid4

import click
import psycopg
from psycopg.rows import dict_row

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.supabase_client import get_supabase_db_url, get_supabase_env

# Test organization ID (use a consistent test org)
TEST_ORG_ID = "00000000-0000-0000-0000-000000000001"

# Test evidence file
TEST_EVIDENCE = {
    "id": "11111111-1111-1111-1111-111111111111",
    "bucket_path": "test/rag_test_document.pdf",
    "file_name": "rag_test_document.pdf",
    "sha256_hash": "a" * 64,
    "size_bytes": 1024,
    "mime_type": "application/pdf",
}

# Test document
TEST_DOCUMENT = {
    "id": "22222222-2222-2222-2222-222222222222",
    "status": "indexed",
    "token_count": 150,
    "chunk_count": 3,
}

# Test chunks with content that should match common queries
TEST_CHUNKS = [
    {
        "id": "33333333-3333-3333-3333-333333333331",
        "chunk_index": 0,
        "page_number": 1,
        "content": "JUDGMENT ENTERED. The court hereby enters judgment in favor of the Plaintiff, Acme Collections LLC, against the Defendant, John Smith, in the amount of $5,000.00 (Five Thousand Dollars) plus interest at 9% per annum.",
    },
    {
        "id": "33333333-3333-3333-3333-333333333332",
        "chunk_index": 1,
        "page_number": 2,
        "content": "The Defendant John Smith resides at 123 Main Street, Springfield, IL 62701. The Defendant is employed at Springfield Industries as a warehouse manager with an estimated annual salary of $45,000.",
    },
    {
        "id": "33333333-3333-3333-3333-333333333333",
        "chunk_index": 2,
        "page_number": 3,
        "content": "ENFORCEMENT RECOMMENDATION: Based on the Defendant's employment status and income level, wage garnishment is recommended as the primary collection strategy. Maximum garnishment rate under Illinois law is 15% of disposable earnings.",
    },
]


def connect_db(dsn: str) -> psycopg.Connection:
    """Connect to database."""
    return psycopg.connect(dsn, row_factory=dict_row)


async def generate_embedding(text: str) -> list[float] | None:
    """Generate embedding using OpenAI."""
    import httpx

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        click.secho("❌ OPENAI_API_KEY not set", fg="red")
        return None

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                "https://api.openai.com/v1/embeddings",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "text-embedding-3-small",
                    "input": text,
                    "dimensions": 1536,
                },
            )

            if response.status_code != 200:
                click.secho(f"❌ OpenAI error: {response.status_code}", fg="red")
                return None

            data = response.json()
            return data["data"][0]["embedding"]

    except Exception as e:
        click.secho(f"❌ Embedding failed: {e}", fg="red")
        return None


def ensure_test_org(conn: psycopg.Connection) -> bool:
    """Ensure test organization exists."""
    try:
        # Check if tenant schema exists
        result = conn.execute(
            """
            SELECT EXISTS (
                SELECT 1 FROM information_schema.schemata
                WHERE schema_name = 'tenant'
            )
            """
        ).fetchone()

        if not result or not result["exists"]:
            click.secho("⚠️  tenant schema not found, skipping org check", fg="yellow")
            return True

        # Check/create test org
        conn.execute(
            """
            INSERT INTO tenant.orgs (id, name, slug)
            VALUES (%s, 'Test Organization', 'test-org')
            ON CONFLICT (id) DO NOTHING
            """,
            [TEST_ORG_ID],
        )
        conn.commit()
        return True

    except Exception as e:
        click.secho(f"⚠️  Could not create test org: {e}", fg="yellow")
        return True  # Continue anyway


def seed_test_evidence(conn: psycopg.Connection) -> bool:
    """Seed test evidence file."""
    try:
        conn.execute(
            """
            INSERT INTO evidence.files (id, org_id, bucket_path, file_name, sha256_hash, size_bytes, mime_type)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO NOTHING
            """,
            [
                TEST_EVIDENCE["id"],
                TEST_ORG_ID,
                TEST_EVIDENCE["bucket_path"],
                TEST_EVIDENCE["file_name"],
                TEST_EVIDENCE["sha256_hash"],
                TEST_EVIDENCE["size_bytes"],
                TEST_EVIDENCE["mime_type"],
            ],
        )
        conn.commit()
        click.echo("  ✅ Test evidence file seeded")
        return True
    except Exception as e:
        click.secho(f"  ❌ Failed to seed evidence: {e}", fg="red")
        return False


def seed_test_document(conn: psycopg.Connection) -> bool:
    """Seed test RAG document."""
    try:
        conn.execute(
            """
            INSERT INTO rag.documents (id, evidence_id, org_id, status, token_count, chunk_count, processed_at)
            VALUES (%s, %s, %s, %s::rag.document_status, %s, %s, NOW())
            ON CONFLICT (id) DO UPDATE SET
                status = EXCLUDED.status,
                token_count = EXCLUDED.token_count,
                chunk_count = EXCLUDED.chunk_count
            """,
            [
                TEST_DOCUMENT["id"],
                TEST_EVIDENCE["id"],
                TEST_ORG_ID,
                TEST_DOCUMENT["status"],
                TEST_DOCUMENT["token_count"],
                TEST_DOCUMENT["chunk_count"],
            ],
        )
        conn.commit()
        click.echo("  ✅ Test document seeded")
        return True
    except Exception as e:
        click.secho(f"  ❌ Failed to seed document: {e}", fg="red")
        return False


async def seed_test_chunks(conn: psycopg.Connection) -> bool:
    """Seed test chunks with embeddings."""
    click.echo("  Generating embeddings for test chunks...")

    for chunk in TEST_CHUNKS:
        # Generate embedding
        embedding = await generate_embedding(chunk["content"])
        if not embedding:
            click.secho(
                f"  ❌ Failed to generate embedding for chunk {chunk['chunk_index']}", fg="red"
            )
            return False

        try:
            # Insert chunk with embedding
            conn.execute(
                """
                INSERT INTO rag.chunks (id, document_id, org_id, chunk_index, page_number, content, embedding)
                VALUES (%s, %s, %s, %s, %s, %s, %s::vector(1536))
                ON CONFLICT (id) DO UPDATE SET
                    content = EXCLUDED.content,
                    embedding = EXCLUDED.embedding
                """,
                [
                    chunk["id"],
                    TEST_DOCUMENT["id"],
                    TEST_ORG_ID,
                    chunk["chunk_index"],
                    chunk["page_number"],
                    chunk["content"],
                    str(embedding),  # Convert to string for vector type
                ],
            )
            conn.commit()
            click.echo(f"    ✅ Chunk {chunk['chunk_index']} (page {chunk['page_number']})")

        except Exception as e:
            click.secho(f"  ❌ Failed to seed chunk: {e}", fg="red")
            return False

    return True


async def test_vector_search(conn: psycopg.Connection) -> bool:
    """Test vector search via RPC."""
    click.echo("\n📊 Testing Vector Search...")

    test_queries = [
        "What is the judgment amount?",
        "Where does the defendant live?",
        "What collection strategy is recommended?",
    ]

    for query in test_queries:
        click.echo(f"\n  Query: '{query}'")

        # Generate query embedding
        embedding = await generate_embedding(query)
        if not embedding:
            click.secho("  ❌ Failed to generate query embedding", fg="red")
            continue

        try:
            # Call match_chunks
            result = conn.execute(
                """
                SELECT * FROM rag.match_chunks(
                    %s::vector(1536),
                    0.5,  -- threshold
                    3,    -- count
                    %s    -- org_id
                )
                """,
                [str(embedding), TEST_ORG_ID],
            ).fetchall()

            if not result:
                click.secho("  ⚠️  No matching chunks found", fg="yellow")
            else:
                click.secho(f"  ✅ Found {len(result)} matching chunk(s):", fg="green")
                for row in result:
                    sim = row["similarity"]
                    page = row["page_number"] or "?"
                    preview = row["content"][:60] + "..."
                    click.echo(f"      [{sim:.3f}] Page {page}: {preview}")

        except Exception as e:
            click.secho(f"  ❌ Search failed: {e}", fg="red")
            return False

    return True


async def test_rag_service() -> bool:
    """Test the full RAG service."""
    click.echo("\n🤖 Testing RAG Service...")

    try:
        from backend.services.rag import RagService

        service = RagService()

        result = await service.search(
            query="What is the judgment amount and who is the defendant?",
            org_id=TEST_ORG_ID,
            match_threshold=0.5,
            match_count=5,
        )

        click.echo(f"\n  Query: '{result.query}'")
        click.echo(f"  Chunks Retrieved: {result.chunks_retrieved}")
        click.echo(f"  Model: {result.model_used}")
        click.echo(f"  Insufficient Evidence: {result.insufficient_evidence}")
        click.echo(f"\n  Answer:\n  {'-' * 60}")
        click.echo(f"  {result.answer}")
        click.echo(f"  {'-' * 60}")

        if result.citations:
            click.echo(f"\n  Citations ({len(result.citations)}):")
            for c in result.citations:
                click.echo(f"    • Doc: {c.document_id[:8]}... Page: {c.page_number}")
                click.echo(f"      Quote: {c.quote_snippet[:50]}...")

        click.secho("\n  ✅ RAG Service test passed!", fg="green")
        return True

    except Exception as e:
        click.secho(f"\n  ❌ RAG Service test failed: {e}", fg="red")
        import traceback

        traceback.print_exc()
        return False


def cleanup_test_data(conn: psycopg.Connection) -> None:
    """Remove test data."""
    click.echo("\n🧹 Cleaning up test data...")

    try:
        conn.execute("DELETE FROM rag.chunks WHERE document_id = %s", [TEST_DOCUMENT["id"]])
        conn.execute("DELETE FROM rag.documents WHERE id = %s", [TEST_DOCUMENT["id"]])
        conn.execute("DELETE FROM evidence.files WHERE id = %s", [TEST_EVIDENCE["id"]])
        conn.commit()
        click.echo("  ✅ Test data removed")
    except Exception as e:
        click.secho(f"  ⚠️  Cleanup warning: {e}", fg="yellow")


def verify_schema(conn: psycopg.Connection) -> bool:
    """Verify RAG schema exists."""
    click.echo("\n🔍 Verifying RAG Schema...")

    checks = [
        ("vector extension", "SELECT * FROM pg_extension WHERE extname = 'vector'"),
        ("rag schema", "SELECT * FROM information_schema.schemata WHERE schema_name = 'rag'"),
        (
            "rag.documents table",
            "SELECT * FROM information_schema.tables WHERE table_schema = 'rag' AND table_name = 'documents'",
        ),
        (
            "rag.chunks table",
            "SELECT * FROM information_schema.tables WHERE table_schema = 'rag' AND table_name = 'chunks'",
        ),
        (
            "HNSW index",
            "SELECT * FROM pg_indexes WHERE schemaname = 'rag' AND indexname LIKE '%hnsw%'",
        ),
    ]

    all_pass = True
    for name, query in checks:
        result = conn.execute(query).fetchone()
        if result:
            click.echo(f"  ✅ {name}")
        else:
            click.secho(f"  ❌ {name} NOT FOUND", fg="red")
            all_pass = False

    return all_pass


@click.command()
@click.option("--env", type=click.Choice(["dev", "prod"]), default="dev", help="Target environment")
@click.option("--seed-only", is_flag=True, help="Only seed test data, don't run tests")
@click.option("--cleanup", is_flag=True, help="Remove test data and exit")
@click.option("--skip-service", is_flag=True, help="Skip RAG service test (requires OpenAI)")
def main(env: str, seed_only: bool, cleanup: bool, skip_service: bool) -> None:
    """Test the RAG system end-to-end."""
    os.environ["SUPABASE_MODE"] = env

    click.echo(f"\n{'=' * 60}")
    click.echo(f"  DRAGONFLY RAG TEST - Environment: {env.upper()}")
    click.echo(f"{'=' * 60}")

    # Get database URL
    try:
        db_url = get_supabase_db_url()
    except Exception as e:
        click.secho(f"\n❌ Failed to get database URL: {e}", fg="red")
        sys.exit(1)

    # Connect
    try:
        conn = connect_db(db_url)
    except Exception as e:
        click.secho(f"\n❌ Database connection failed: {e}", fg="red")
        sys.exit(1)

    try:
        # Cleanup only
        if cleanup:
            cleanup_test_data(conn)
            sys.exit(0)

        # Verify schema
        if not verify_schema(conn):
            click.secho("\n❌ RAG schema not found. Run migrations first.", fg="red")
            sys.exit(1)

        # Seed data
        click.echo("\n📦 Seeding Test Data...")
        ensure_test_org(conn)

        if not seed_test_evidence(conn):
            sys.exit(1)

        if not seed_test_document(conn):
            sys.exit(1)

        if not asyncio.run(seed_test_chunks(conn)):
            sys.exit(1)

        if seed_only:
            click.secho("\n✅ Test data seeded successfully!", fg="green")
            sys.exit(0)

        # Test vector search
        if not asyncio.run(test_vector_search(conn)):
            sys.exit(1)

        # Test RAG service
        if not skip_service:
            if not asyncio.run(test_rag_service()):
                sys.exit(1)
        else:
            click.echo("\n⏭️  Skipping RAG service test")

        click.secho(f"\n{'=' * 60}", fg="green")
        click.secho("  ✅ ALL RAG TESTS PASSED", fg="green")
        click.secho(f"{'=' * 60}\n", fg="green")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
