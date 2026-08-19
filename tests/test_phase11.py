import os
import pytest
from app.core.config import Settings

def test_production_config():
    """Test that production environment variables load correctly."""
    # Temporarily set environment variables
    os.environ["APP_ENV"] = "production"
    os.environ["LOG_LEVEL"] = "WARNING"
    os.environ["TELEGRAM_BOT_TOKEN"] = "test_token"
    os.environ["GEMINI_API_KEY"] = "test_key"
    
    settings = Settings()
    assert settings.app_env == "production"
    assert settings.log_level == "WARNING"
    assert settings.telegram_bot_token == "test_token"
    assert settings.gemini_api_key == "test_key"
    
    # Cleanup
    del os.environ["APP_ENV"]
    del os.environ["LOG_LEVEL"]
    del os.environ["TELEGRAM_BOT_TOKEN"]
    del os.environ["GEMINI_API_KEY"]

def test_dockerfile_exists():
    """Verify Dockerfile is present for containerization."""
    assert os.path.exists("Dockerfile")

def test_docker_compose_exists():
    """Verify docker-compose.yml is present."""
    assert os.path.exists("docker-compose.yml")

def test_dockerignore_exists():
    """Verify .dockerignore is present."""
    assert os.path.exists(".dockerignore")

def test_start_script_exists():
    """Verify start script is present."""
    assert os.path.exists("scripts/start.sh")
