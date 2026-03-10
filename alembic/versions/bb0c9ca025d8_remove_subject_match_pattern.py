"""remove subject_match_pattern

Revision ID: bb0c9ca025d8
Revises: e649ec2713bf
Create Date: 2026-03-07 02:02:35.748636

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'bb0c9ca025d8'
down_revision: Union[str, Sequence[str], None] = 'e649ec2713bf'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
