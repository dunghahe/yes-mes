"""Internal readiness check without bypassing Cloudflare Access on HTTP routes."""

import socket
import sys

from sqlalchemy import text

from app.core.db import engine


def main() -> int:
    try:
        with socket.create_connection(("127.0.0.1", 8000), timeout=3):
            pass
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return 0
    except Exception:
        # Health logs must not contain a connection URL or credentials.
        return 1


if __name__ == "__main__":
    sys.exit(main())
