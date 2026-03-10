"""merge sync_start_date and remove_subject_pattern

Revision ID: ac97ab409e8e
Revises: bb0c9ca025d8, 6377a8fb88ff
Create Date: 2026-03-10 21:41:47.513061

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ac97ab409e8e'
down_revision: Union[str, Sequence[str], None] = ('bb0c9ca025d8', '6377a8fb88ff')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
