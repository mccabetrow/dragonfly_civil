import pytest

from src.db_upload_safe import (
    chunked,
    upsert_public_judgments,
    upsert_public_judgments_chunked,
)


class FakeResponse:
    def __init__(self, status_code=None, data=None, count=None, error=None):
        self.status_code = status_code
        self.data = data
        self.count = count
        self.error = error


def make_fake_client(response, capture):
    class FakeExecutor:
        def __init__(self, resp):
            self._resp = resp

        def execute(self):
            return self._resp

    class FakeTable:
        def __init__(self, resp):
            self._resp = resp

        def upsert(self, rows, on_conflict, returning, count):
            capture["rows"] = rows
            capture["on_conflict"] = on_conflict
            capture["returning"] = returning
            capture["count"] = count
            return FakeExecutor(self._resp)

    class FakeClient:
        def __init__(self, resp):
            self._resp = resp

        def table(self, name):
            capture["table_name"] = name
            return FakeTable(self._resp)

    return FakeClient(response)


def test_upsert_public_judgments_success(monkeypatch):
    response = FakeResponse(status_code=200, data=[{"case_number": "A"}], count=None)
    capture = {}
    monkeypatch.setattr(
        "src.db_upload_safe.create_supabase_client",
        lambda: make_fake_client(response, capture),
    )

    rows = [{"case_number": "A", "source": "csv"}]
    result = upsert_public_judgments(rows)

    assert result == (1, response.data, 200)
    assert capture["table_name"] == "judgments"
    assert capture["rows"][0]["source_file"] == "csv"
    assert "source" not in capture["rows"][0]
    assert capture["on_conflict"] == "case_number"
    assert capture["returning"] == "representation"
    assert capture["count"] == "exact"


def test_upsert_public_judgments_infers_status(monkeypatch):
    response = FakeResponse(status_code=None, data=[{"case_number": "B"}], count=None)
    capture = {}
    monkeypatch.setattr(
        "src.db_upload_safe.create_supabase_client",
        lambda: make_fake_client(response, capture),
    )

    rows = [{"case_number": "B", "source": "watcher"}]
    result = upsert_public_judgments(rows)

    assert result == (1, response.data, 200)
    assert capture["table_name"] == "judgments"
    assert capture["rows"][0]["source_file"] == "watcher"


def test_upsert_public_judgments_raises_on_error(monkeypatch):
    response = FakeResponse(status_code=409, data={"message": "conflict"}, count=None)
    capture = {}
    monkeypatch.setattr(
        "src.db_upload_safe.create_supabase_client",
        lambda: make_fake_client(response, capture),
    )

    with pytest.raises(RuntimeError):
        upsert_public_judgments([{"case_number": "C"}])

    assert capture["table_name"] == "judgments"


def test_chunked_splits_iterable():
    result = list(chunked(range(5), 2))
    assert result == [[0, 1], [2, 3], [4]]


def test_chunked_rejects_non_positive_size():
    with pytest.raises(ValueError):
        list(chunked([1, 2], 0))


def test_upsert_public_judgments_chunked(monkeypatch):
    calls = []

    def fake_upsert(chunk):
        calls.append(list(chunk))
        return len(chunk), list(chunk), 200

    monkeypatch.setattr("src.db_upload_safe.upsert_public_judgments", fake_upsert)

    rows = [{"case_number": str(i)} for i in range(5)]
    total, data, status = upsert_public_judgments_chunked(rows, chunk_size=2, max_retries=2)

    assert total == 5
    assert len(data) == 5
    assert status == 200
    assert calls == [rows[0:2], rows[2:4], rows[4:5]]


def test_upsert_public_judgments_chunked_retries_transient(monkeypatch):
    attempts = {"count": 0}

    def flaky(chunk):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise RuntimeError("Upload failed (status=429). Full response: {}")
        return len(chunk), list(chunk), 200

    monkeypatch.setattr("src.db_upload_safe.upsert_public_judgments", flaky)

    rows = [{"case_number": "1"}]
    total, data, status = upsert_public_judgments_chunked(rows, chunk_size=1, max_retries=3)

    assert attempts["count"] == 2
    assert total == 1
    assert len(data) == 1
    assert status == 200


def test_upsert_public_judgments_chunked_non_transient(monkeypatch):
    attempts = {"count": 0}

    def failing(chunk):
        attempts["count"] += 1
        raise RuntimeError("Upload failed (status=400). Full response: {}")

    monkeypatch.setattr("src.db_upload_safe.upsert_public_judgments", failing)

    with pytest.raises(RuntimeError):
        upsert_public_judgments_chunked([{"case_number": "1"}], chunk_size=1, max_retries=3)

    assert attempts["count"] == 1
