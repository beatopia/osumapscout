"""Deployment configuration and readiness tests."""

import os
import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from backend.app.config import AppConfig, validate_server_environment
from backend.app.main import app


class AppConfigTests(unittest.TestCase):
    def test_explicit_origins_are_trimmed_and_wildcard_is_rejected(self) -> None:
        with patch.dict(os.environ, {"CORS_ORIGINS": "https://one.test, https://two.test"}):
            self.assertEqual(
                AppConfig.from_environment().cors_origins,
                ("https://one.test", "https://two.test"),
            )
        with patch.dict(os.environ, {"CORS_ORIGINS": "*"}):
            with self.assertRaisesRegex(ValueError, "explicit origins"):
                AppConfig.from_environment()

    def test_startup_contract_validates_credentials_and_database_url(self) -> None:
        environment = {
            "OSU_CLIENT_ID": "id",
            "OSU_CLIENT_SECRET": "secret",
            "DATABASE_URL": "postgresql+psycopg://user:password@host/database",
        }
        with patch.dict(os.environ, environment, clear=True):
            config = validate_server_environment()
        self.assertTrue(config.cors_origins)


class HealthTests(unittest.TestCase):
    def test_health_does_not_touch_database(self) -> None:
        with patch("backend.app.main.get_engine") as engine:
            response = TestClient(app).get("/health")
        self.assertEqual(response.json(), {"status": "ok"})
        engine.assert_not_called()

    def test_readiness_checks_database_once(self) -> None:
        connection = MagicMock()
        engine = MagicMock()
        engine.connect.return_value.__enter__.return_value = connection
        with patch("backend.app.main.get_engine", return_value=engine):
            response = TestClient(app).get("/ready")
        self.assertEqual(response.json(), {"status": "ready"})
        connection.execute.assert_called_once()


if __name__ == "__main__":
    unittest.main()
