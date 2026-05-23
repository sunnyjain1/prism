"""merge subscription-related heads

Revision ID: e7b3c1d4a9f2
Revises: 9f0f8d4c2a11, c0f4c7b8a1d2, c2f9f4d8f1a1
Create Date: 2026-05-23 13:35:00.000000

"""
from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = 'e7b3c1d4a9f2'
down_revision: Union[str, Sequence[str], None] = ('9f0f8d4c2a11', 'c0f4c7b8a1d2', 'c2f9f4d8f1a1')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
