"""merge budget feature heads

Revision ID: 7b2c4d8e9f10
Revises: 21f0d6a4c9b1, 5e1f75a4d2b3, f2c3b7a9d4e1
Create Date: 2026-05-24 00:00:01.000000

"""
from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = '7b2c4d8e9f10'
down_revision: Union[str, Sequence[str], None] = ('21f0d6a4c9b1', '5e1f75a4d2b3', 'f2c3b7a9d4e1')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None



def upgrade() -> None:
    pass



def downgrade() -> None:
    pass
