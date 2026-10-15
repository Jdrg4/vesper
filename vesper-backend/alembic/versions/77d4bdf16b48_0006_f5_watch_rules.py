"""0006_f5_watch_rules

Revision ID: 77d4bdf16b48
Revises: d1a777ea4bd0
Create Date: 2026-08-03 23:47:36.375325

"""
from collections.abc import Sequence
from typing import Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '77d4bdf16b48'
down_revision: Union[str, None] = 'd1a777ea4bd0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('watch_rules',
    sa.Column('repository_id', sa.UUID(), nullable=False),
    # `create_type=False`: el tipo `task_type` ya lo creo la 0003 (F4). Dejar
    # que Alembic lo recree aqui aborta el upgrade con "type already exists".
    sa.Column(
        'task_type',
        postgresql.ENUM(
            'security', 'quality', 'deps', 'perf', 'docs',
            name='task_type',
            create_type=False,
        ),
        nullable=False,
    ),
    sa.Column('cron', sa.String(length=128), nullable=True),
    sa.Column('on_push', sa.Boolean(), nullable=False),
    sa.Column('ref', sa.String(length=256), nullable=True),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('next_run_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_run_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['repository_id'], ['repositories.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    # La unicidad es por (repo, tarea), NO por repo: dos tenants pueden tener
    # enrolado el mismo repo de GitHub, igual que en `repositories`.
    sa.UniqueConstraint('repository_id', 'task_type', name='uq_watch_rules_repo_task')
    )
    # El tick del scheduler barre exactamente esta pareja cada minuto.
    op.create_index('ix_watch_rules_enabled_next_run', 'watch_rules', ['enabled', 'next_run_at'], unique=False)
    op.create_index(op.f('ix_watch_rules_repository_id'), 'watch_rules', ['repository_id'], unique=False)
    op.create_index(op.f('ix_watch_rules_tenant_id'), 'watch_rules', ['tenant_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_watch_rules_tenant_id'), table_name='watch_rules')
    op.drop_index(op.f('ix_watch_rules_repository_id'), table_name='watch_rules')
    op.drop_index('ix_watch_rules_enabled_next_run', table_name='watch_rules')
    # Solo la tabla: soltar el tipo `task_type` se llevaria por delante
    # `review_jobs`, que lo comparte.
    op.drop_table('watch_rules')
