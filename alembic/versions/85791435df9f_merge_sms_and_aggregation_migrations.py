"""merge sms and aggregation migrations

Revision ID: 85791435df9f
Revises: 4b5c6d7e8f90, a1b2c3d4e5f6
Create Date: 2026-05-26 01:24:46.194519

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '85791435df9f'
down_revision: Union[str, Sequence[str], None] = ('4b5c6d7e8f90', 'a1b2c3d4e5f6')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
