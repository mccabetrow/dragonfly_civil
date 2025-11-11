import os


def _load_environment() -> None:
    """Load environment variables from .env if python-dotenv is available."""

    try:
        from dotenv import load_dotenv  # type: ignore

        load_dotenv()
    except Exception:  # pragma: no cover - python-dotenv optional
        pass


_load_environment()

REF = os.getenv("SUPABASE_PROJECT_REF", "").strip()
SERVICE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()


def _truthy(val: str | None) -> bool:
    if val is None:
        return False
    return val.strip().lower() in {"true", "on", "1", "yes", "y"}


USE_PUBLIC_WRAPPERS = _truthy(os.getenv("USE_PUBLIC_WRAPPERS", "true"))

# When wrappers are on, we talk to the public surface.
SCHEMA_PROFILE = (
    "public"
    if USE_PUBLIC_WRAPPERS
    else (os.getenv("SCHEMA_PROFILE", "public") or "public").strip() or "public"
)
BASE_URL = f"https://{REF}.supabase.co" if REF else ""

# Backwards compatibility: callers previously imported this name.
USE_PUBLIC = USE_PUBLIC_WRAPPERS
