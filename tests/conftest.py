"""Shared fixtures: in-memory/temporary SQLite + ingested sample corpus."""

from __future__ import annotations

import socket
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app.db import init_db, make_engine, make_session_factory
from app.ingestion.loader import load_advisories

FIXTURE = Path(__file__).resolve().parent.parent / "data" / "sample" / "advisories.json"


@pytest.fixture(autouse=True)
def _block_real_network(monkeypatch: pytest.MonkeyPatch):
    """Fail loudly if any test tries to open a real socket.

    The whole suite must run offline and deterministically (research
    reproducibility). Tests that need HTTP inject `httpx.MockTransport`;
    anything else that reaches for the network is a bug, not a flake.
    """

    def _blocked(*args, **kwargs):
        raise RuntimeError(
            "Real network access is blocked in tests. Use httpx.MockTransport "
            "(see tests/test_fetchers.py) instead of a live endpoint."
        )

    monkeypatch.setattr(socket.socket, "connect", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)
    monkeypatch.setattr(socket, "getaddrinfo", _blocked)


@pytest.fixture()
def session(tmp_path: Path) -> Session:
    """A session on a fresh temporary SQLite database with tables created."""
    engine = make_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    sess = make_session_factory(engine)()
    yield sess
    sess.close()


@pytest.fixture()
def populated_session(session: Session) -> Session:
    """Session with the sample advisory fixture ingested."""
    report = load_advisories(session, FIXTURE)
    assert report.documents == 5, "sample fixture should contain 5 valid records"
    assert report.chunks > 0
    return session
