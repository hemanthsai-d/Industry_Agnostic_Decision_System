"""Root conftest — ensures tests always run in a test environment context.

This prevents the production validator in Settings from blocking test
collection when the .env file happens to have APP_ENV=production.
"""
from __future__ import annotations

import os


def pytest_configure(config):
    """Set environment to 'test' before any module imports Settings."""
    os.environ.setdefault('APP_ENV', 'test')
    # Disable features that require external services in CI/test
    os.environ.setdefault('AUTH_ENABLED', 'false')
    os.environ.setdefault('RATE_LIMIT_ENABLED', 'false')
    os.environ.setdefault('USE_POSTGRES', 'false')
    os.environ.setdefault('USE_REDIS', 'false')
    os.environ.setdefault('GENERATION_BACKEND', 'template')
