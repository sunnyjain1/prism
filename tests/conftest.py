import os
import sys
from fnmatch import fnmatch

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, PROJECT_ROOT)
os.environ.setdefault("PRISM_SKIP_DOTENV", "true")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.dependencies import get_db
from core.rate_limit import limiter
import models  # noqa: F401
import user_models  # noqa: F401
from database import Base
from main import app
from api import search as search_api
from services import report_service
from services.cache_service import cache
from services.job_queue import job_queue

SQLALCHEMY_DATABASE_URL = "sqlite:///./test.db"


@pytest.fixture(scope="session")
def engine():
    engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)
    if os.path.exists("./test.db"):
        os.remove("./test.db")


@pytest.fixture(scope="function")
def db_session(engine):
    connection = engine.connect()
    transaction = connection.begin()
    Session = sessionmaker(bind=connection)
    session = Session()

    yield session

    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="function")
def cache_store(monkeypatch):
    store = {}

    def fake_get(key):
        return store.get(key)

    def fake_set(key, value, ttl=300):
        store[key] = value

    def fake_delete(key):
        store.pop(key, None)

    def fake_delete_pattern(pattern):
        for key in list(store):
            if fnmatch(key, pattern):
                store.pop(key, None)

    monkeypatch.setattr(cache, "get", fake_get)
    monkeypatch.setattr(cache, "set", fake_set)
    monkeypatch.setattr(cache, "delete", fake_delete)
    monkeypatch.setattr(cache, "delete_pattern", fake_delete_pattern)
    return store


@pytest.fixture(scope="function")
def api_client(db_session, monkeypatch):
    def override_get_db():
        yield db_session

    class ImmediateFuture:
        def result(self):
            return None

    def immediate_submit(func, *args, **kwargs):
        func(*args, **kwargs)
        return ImmediateFuture()

    background_session_factory = sessionmaker(bind=db_session.get_bind())
    monkeypatch.setattr(job_queue.executor, "submit", immediate_submit)
    monkeypatch.setattr(report_service, "SessionLocal", background_session_factory)
    monkeypatch.setattr(search_api, "SessionLocal", background_session_factory)
    job_queue.jobs.clear()

    app.dependency_overrides[get_db] = override_get_db
    limiter._storage.reset()

    with TestClient(app) as c:
        yield c

    app.dependency_overrides.clear()
    limiter._storage.reset()
    job_queue.jobs.clear()
