"""fix idempotency_keys to use composite primary key

Revision ID: ca94b3ed0380
Revises: 21f1c1209d8d
Create Date: 2026-06-21 13:48:31.258074

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ca94b3ed0380'
down_revision: Union[str, Sequence[str], None] = '21f1c1209d8d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Drop the old single-column primary key constraint
    op.drop_constraint('idempotency_keys_pkey', 'idempotency_keys', type_='primary')
    # Create the new composite primary key on (key, merchant_id)
    op.create_primary_key('idempotency_keys_pkey', 'idempotency_keys', ['key', 'merchant_id'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('idempotency_keys_pkey', 'idempotency_keys', type_='primary')
    op.create_primary_key('idempotency_keys_pkey', 'idempotency_keys', ['key'])
