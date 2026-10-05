"""analises de edital

Revision ID: 9340bd506aec
Revises: 4b71299e2a99
Create Date: 2026-10-05 18:22:51.052950

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '9340bd506aec'
down_revision: Union[str, Sequence[str], None] = '4b71299e2a99'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('analises',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('perfil_id', sa.Integer(), nullable=False),
    sa.Column('licitacao_id', sa.String(length=40), nullable=False),
    sa.Column('resultado', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('recomendacao', sa.String(length=20), nullable=False),
    sa.Column('modelo', sa.String(length=60), nullable=False),
    sa.Column('paginas_lidas', sa.Integer(), nullable=False),
    sa.Column('tokens_entrada', sa.Integer(), nullable=False),
    sa.Column('tokens_saida', sa.Integer(), nullable=False),
    sa.Column('segundos', sa.Double(), nullable=False),
    sa.Column('citacoes_total', sa.Integer(), nullable=False),
    sa.Column('citacoes_verificadas', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['licitacao_id'], ['licitacoes.id'], name=op.f('fk_analises_licitacao_id_licitacoes'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['perfil_id'], ['perfis.id'], name=op.f('fk_analises_perfil_id_perfis'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_analises')),
    sa.UniqueConstraint('perfil_id', 'licitacao_id', name=op.f('uq_analises_perfil_id'))
    )
    op.create_index(op.f('ix_analises_perfil_id'), 'analises', ['perfil_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_analises_perfil_id'), table_name='analises')
    op.drop_table('analises')
