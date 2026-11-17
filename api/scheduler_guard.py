"""Allow a declared production Cloud SQL Proxy without enabling local dev schedules.

The deployment guard verifies the VM project and starts the matching proxy.
This helper only validates that the app explicitly opts into that deployment.
"""
import os
import re

from sqlalchemy.engine import make_url


def database_schedule_allowed() -> bool:
    try:
        url = make_url(os.environ.get('DATABASE_URL') or '')
        host = url.host
        if not host:
            return False
        if host not in ('127.0.0.1', 'localhost', '::1'):
            return True  # Preserve the existing remote-DB scheduler default.
        connection = os.environ.get('CLOUD_SQL_INSTANCE_CONNECTION_NAME', '')
        expected_database = os.environ.get('POPCORN_EXPECTED_DATABASE', '')
        return (
            os.environ.get('POPCORN_CLOUD_SQL_PROXY_SCHEDULE_ENABLED') == '1'
            and os.environ.get('POPCORN_ENVIRONMENT') == 'production'
            and os.environ.get('POPCORN_DEPLOYMENT_PHASE') == 'production'
            and bool(re.fullmatch(r'[a-z][a-z0-9-]{4,62}[a-z0-9]:[a-z]+-[a-z]+[0-9]:[a-z][a-z0-9-]+', connection))
            and url.get_backend_name() == 'postgresql'
            and host == '127.0.0.1' and url.port == 5432
            and bool(expected_database) and url.database == expected_database
        )
    except Exception:
        # SQLAlchemy malformed URLs also raise ArgumentError. Never log the DSN.
        return False
