"""Alembic environment — wired to the application's own config and models.

The database URL is never hardcoded: it comes from the same DATABASE_URL the app
uses, so `alembic upgrade head` always targets the environment you are in.
"""
from __future__ import annotations

import os
import sys

from alembic import context
from sqlalchemy import engine_from_config, pool

# make the application importable when alembic runs from the project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import Config          # noqa: E402
from app.models import db              # noqa: E402

config = context.config
config.set_main_option("sqlalchemy.url", Config.SQLALCHEMY_DATABASE_URI.replace("%", "%%"))

target_metadata = db.metadata


def run_migrations_offline() -> None:
    context.configure(url=config.get_main_option("sqlalchemy.url"),
                      target_metadata=target_metadata,
                      literal_binds=True,
                      render_as_batch=True,
                      compare_type=True,
                      dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(config.get_section(config.config_ini_section, {}),
                                     prefix="sqlalchemy.",
                                     poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection,
                          target_metadata=target_metadata,
                          # batch mode lets SQLite do ALTERs it cannot do natively
                          render_as_batch=True,
                          compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
