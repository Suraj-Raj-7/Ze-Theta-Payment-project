# migrations/env.py
# ─────────────────────────────────────────────────────────────
# PURPOSE: Tells Alembic where our database is and where our
#          models are. Alembic reads this file every time you
#          run any alembic command.
#
# WHY THIS MATTERS:
#   Alembic needs to know about ALL our models to generate
#   correct migrations. If we forget to import a model here,
#   Alembic won't create that table.
# ─────────────────────────────────────────────────────────────

from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from alembic import context

# Import our settings to get DATABASE_URL
from app.config import settings

# Import Base — this is the parent class all our models inherit from
# Alembic reads Base.metadata to discover ALL tables
from app.database import Base

# Import ALL models so Alembic knows about them
# If you add a new model later, import it here too
from app.models.transaction import Transaction
from app.models.state_log import TransactionStateLog
from app.models.gateway import GatewayConfig, GatewayHealthMetric
from app.models.idempotency import IdempotencyKey
from app.models.webhook import WebhookEvent, ProcessedWebhookEvent
from app.models.refund import Refund

# Alembic Config object — reads alembic.ini
config = context.config

# Override the sqlalchemy.url from alembic.ini with our .env value
# This way we have ONE source of truth for the database URL
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

# Set up logging from alembic.ini config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# This is the metadata Alembic uses to detect schema changes
# Base.metadata knows about ALL tables because we imported all models above
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """
    Run migrations without a live database connection.
    Useful for generating SQL scripts to review before running.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """
    Run migrations with a live database connection.
    This is what actually creates/modifies tables in PostgreSQL.
    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata
        )
        with context.begin_transaction():
            context.run_migrations()


# Run online migrations if database is available, offline otherwise
if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()