from __future__ import annotations

from typing import Iterator, List

import pytest
from flask import Flask

from app import db
from app.utility import burn_rate_refresh


@pytest.fixture
def flask_app() -> Iterator[Flask]:
    app = Flask(__name__)
    app.config.update(
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        ENABLE_BURN_RATE_REFRESH=True,
    )
    db.init_app(app)
    yield app
    with app.app_context():
        db.session.remove()


def test_normalize_link_ids_filters_invalids() -> None:
    result = burn_rate_refresh._normalize_link_ids([None, "abc", -5, 5, 3, 5])
    assert result == (3, 5)


def test_schedule_without_context_does_not_submit(monkeypatch) -> None:
    submissions: List[tuple] = []

    def fake_submit(*args, **kwargs):
        submissions.append((args, kwargs))

    monkeypatch.setattr(burn_rate_refresh._THREAD_POOL, "submit", fake_submit)
    burn_rate_refresh.schedule_burn_rate_refresh([1, 2, 3])
    assert not submissions


def test_schedule_skips_when_disabled(flask_app: Flask, monkeypatch) -> None:
    submissions: List[tuple] = []

    def fake_submit(*args, **kwargs):
        submissions.append((args, kwargs))

    monkeypatch.setattr(burn_rate_refresh._THREAD_POOL, "submit", fake_submit)
    monkeypatch.setattr(burn_rate_refresh, "_is_enabled", lambda app: False)

    with flask_app.app_context():
        burn_rate_refresh.schedule_burn_rate_refresh([7, 8])

    assert not submissions


def test_schedule_enqueues_when_enabled(flask_app: Flask, monkeypatch) -> None:
    submissions: List[tuple] = []

    def fake_submit(callback, app, link_ids, job_ids):
        submissions.append((callback, app, link_ids, job_ids))

    monkeypatch.setattr(burn_rate_refresh._THREAD_POOL, "submit", fake_submit)
    monkeypatch.setattr(burn_rate_refresh, "_is_enabled", lambda app: True)

    with flask_app.app_context():
        burn_rate_refresh.schedule_burn_rate_refresh([1, "2", None, 1], job_ids=[None, "5", 7])

    assert submissions
    callback, app, link_ids, job_ids = submissions[0]
    assert app is flask_app
    assert link_ids == (1, 2)
    assert job_ids == (5, 7)
    assert callback is burn_rate_refresh._refresh_burn_rates