"""perfis e triagens

Revision ID: 4b71299e2a99
Revises: 072832541529
Create Date: 2026-10-05 18:14:27.648201

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '4b71299e2a99'
down_revision: Union[str, Sequence[str], None] = '072832541529'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('perfis',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('nome', sa.String(length=200), nullable=False),
    sa.Column('descricao', sa.Text(), nullable=False),
    sa.Column('palavras_chave', postgresql.ARRAY(sa.String(length=100)), nullable=False),
    sa.Column('ufs', postgresql.ARRAY(sa.String(length=2)), nullable=False),
    sa.Column('valor_minimo', sa.Numeric(precision=18, scale=2), nullable=True),
    sa.Column('valor_maximo', sa.Numeric(precision=18, scale=2), nullable=True),
    sa.Column('documentos', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_perfis'))
    )
    op.create_table('triagens',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('perfil_id', sa.Integer(), nullable=False),
    sa.Column('licitacao_id', sa.String(length=40), nullable=False),
    sa.Column('nota', sa.Integer(), nullable=False),
    sa.Column('relevante', sa.Boolean(), nullable=False),
    sa.Column('motivo', sa.Text(), nullable=False),
    sa.Column('modelo', sa.String(length=60), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['licitacao_id'], ['licitacoes.id'], name=op.f('fk_triagens_licitacao_id_licitacoes'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['perfil_id'], ['perfis.id'], name=op.f('fk_triagens_perfil_id_perfis'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_triagens')),
    sa.UniqueConstraint('perfil_id', 'licitacao_id', name=op.f('uq_triagens_perfil_id'))
    )
    op.create_index(op.f('ix_triagens_perfil_id'), 'triagens', ['perfil_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_triagens_perfil_id'), table_name='triagens')
    op.drop_table('triagens')
    op.drop_table('perfis')
