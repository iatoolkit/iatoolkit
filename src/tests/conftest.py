# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

import pytest
import os


@pytest.fixture(scope="session", autouse=True)
def setup_test_environment():
    """Configuración global de variables de ambiente para todos los tests"""
    # Guardar estado original
    original_environ = dict(os.environ)

    # Establecer variables para tests
    test_vars = {
        'DATABASE_URI': 'sqlite:///:memory:',
        'REDIS_URL': 'redis://localhost:6379',
        'FLASK_ENV': 'testing',
        # Rate limits off: they would count in the developer's Redis across tests (BL-030).
        'IAT_RATE_LIMITS': 'off',
        'SECRET_KEY': 'test_secret_key',
        'CARPETA_API_URL': 'http://test-carpeta-api.com',
        'MIDDLEWARE_API_URL': 'http://test-middleware-api.com',
        'BCU_API_URL': 'http://test-bcu-api.com',
        'CONTACT_BOOK_API_URL': 'http://test-contact-book-api.com',
        'PUBLIC_MARKET_API_URL': 'http://test-public-market-api.com',
        'USERS_APP_API_URL': 'http://test-users-app-api.com'
    }

    os.environ.update(test_vars)

    yield

    # Restaurar estado original
    os.environ.clear()
    os.environ.update(original_environ)
