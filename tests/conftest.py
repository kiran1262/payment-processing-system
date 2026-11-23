import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.database import Base, get_db, enable_sqlite_foreign_keys
from app.main import app

@pytest.fixture()
def client():
    engine = enable_sqlite_foreign_keys(create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool))
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    def override_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as test_client:
        response = test_client.post("/api/auth/register", json={
            "tenant_name": "Test Store", "full_name": "Test Owner",
            "email": "owner@example.com", "password": "correct-horse-battery",
        })
        assert response.status_code == 201
        test_client.headers.update({"Authorization": f"Bearer {response.json()['access_token']}"})
        yield test_client
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()
