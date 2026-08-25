"""Add ConversationMessage

Revision ID: 230b8d52b7e7
Revises: 6c8fd5ab903d
Create Date: 2026-08-24 19:46:09.185054

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '230b8d52b7e7'
down_revision: Union[str, None] = '6c8fd5ab903d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'conversation_messages',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('telegram_user_id', sa.BigInteger(), nullable=False, comment='Telegram user ID who owns this message'),
        sa.Column('role', sa.String(length=10), nullable=False, comment='Role of the sender (user or model)'),
        sa.Column('content', sa.Text(), nullable=False, comment='The text content of the message'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_conversation_messages_telegram_user_id'), 'conversation_messages', ['telegram_user_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_conversation_messages_telegram_user_id'), table_name='conversation_messages')
    op.drop_table('conversation_messages')
