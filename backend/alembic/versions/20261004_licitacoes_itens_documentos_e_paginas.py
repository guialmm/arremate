"""licitacoes, itens, documentos e paginas

Revision ID: 072832541529
Revises: 
Create Date: 2026-10-04 15:39:44.648559

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '072832541529'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('licitacoes',
    sa.Column('id', sa.String(length=40), nullable=False),
    sa.Column('cnpj', sa.String(length=14), nullable=False),
    sa.Column('ano', sa.Integer(), nullable=False),
    sa.Column('sequencial', sa.Integer(), nullable=False),
    sa.Column('orgao', sa.String(length=300), nullable=False),
    sa.Column('unidade', sa.String(length=300), nullable=True),
    sa.Column('uf', sa.String(length=2), nullable=True),
    sa.Column('municipio', sa.String(length=120), nullable=True),
    sa.Column('modalidade_id', sa.Integer(), nullable=False),
    sa.Column('modalidade', sa.String(length=80), nullable=False),
    sa.Column('objeto', sa.Text(), nullable=False),
    sa.Column('informacao_complementar', sa.Text(), nullable=True),
    sa.Column('valor_estimado', sa.Numeric(precision=18, scale=2), nullable=True),
    sa.Column('srp', sa.Boolean(), nullable=False),
    sa.Column('situacao', sa.String(length=60), nullable=False),
    sa.Column('publicada_em', sa.DateTime(timezone=True), nullable=False),
    sa.Column('abertura_propostas', sa.DateTime(timezone=True), nullable=True),
    sa.Column('encerramento_propostas', sa.DateTime(timezone=True), nullable=True),
    sa.Column('atualizada_no_pncp', sa.DateTime(timezone=True), nullable=True),
    sa.Column('link_origem', sa.Text(), nullable=True),
    sa.Column('raw', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('detalhes', sa.Enum('pendente', 'ok', 'falhou', name='etapa'), nullable=False),
    sa.Column('detalhes_tentativas', sa.Integer(), nullable=False),
    sa.Column('detalhes_erro', sa.Text(), nullable=True),
    sa.Column('busca', postgresql.TSVECTOR(), sa.Computed("to_tsvector('portuguese', objeto || ' ' || coalesce(informacao_complementar, ''))", persisted=True), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_licitacoes')),
    sa.UniqueConstraint('cnpj', 'ano', 'sequencial', name=op.f('uq_licitacoes_cnpj'))
    )
    op.create_index('ix_licitacoes_busca', 'licitacoes', ['busca'], unique=False, postgresql_using='gin')
    op.create_index(op.f('ix_licitacoes_detalhes'), 'licitacoes', ['detalhes'], unique=False)
    op.create_index(op.f('ix_licitacoes_encerramento_propostas'), 'licitacoes', ['encerramento_propostas'], unique=False)
    op.create_index(op.f('ix_licitacoes_publicada_em'), 'licitacoes', ['publicada_em'], unique=False)
    op.create_index(op.f('ix_licitacoes_uf'), 'licitacoes', ['uf'], unique=False)
    op.create_table('sincronizacoes',
    sa.Column('dia', sa.Date(), nullable=False),
    sa.Column('modalidade_id', sa.Integer(), nullable=False),
    sa.Column('ultima_pagina', sa.Integer(), nullable=False),
    sa.Column('total_paginas', sa.Integer(), nullable=True),
    sa.Column('total_registros', sa.Integer(), nullable=True),
    sa.Column('concluida', sa.Boolean(), nullable=False),
    sa.Column('atualizada_em', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('dia', 'modalidade_id', name=op.f('pk_sincronizacoes'))
    )
    op.create_table('documentos',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('licitacao_id', sa.String(length=40), nullable=False),
    sa.Column('sequencial', sa.Integer(), nullable=False),
    sa.Column('titulo', sa.String(length=500), nullable=False),
    sa.Column('tipo_id', sa.Integer(), nullable=True),
    sa.Column('tipo', sa.String(length=120), nullable=True),
    sa.Column('url', sa.Text(), nullable=False),
    sa.Column('status', sa.Enum('pendente', 'ok', 'falhou', 'nao_suportado', name='statusdocumento'), nullable=False),
    sa.Column('formato', sa.String(length=10), nullable=True),
    sa.Column('nome_arquivo', sa.String(length=300), nullable=True),
    sa.Column('tamanho_bytes', sa.BigInteger(), nullable=True),
    sa.Column('sha256', sa.String(length=64), nullable=True),
    sa.Column('total_paginas', sa.Integer(), nullable=True),
    sa.Column('tentativas', sa.Integer(), nullable=False),
    sa.Column('erro', sa.Text(), nullable=True),
    sa.Column('baixado_em', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['licitacao_id'], ['licitacoes.id'], name=op.f('fk_documentos_licitacao_id_licitacoes'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_documentos')),
    sa.UniqueConstraint('licitacao_id', 'sequencial', name=op.f('uq_documentos_licitacao_id'))
    )
    op.create_table('itens',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('licitacao_id', sa.String(length=40), nullable=False),
    sa.Column('numero', sa.Integer(), nullable=False),
    sa.Column('descricao', sa.Text(), nullable=False),
    sa.Column('material_ou_servico', sa.String(length=1), nullable=True),
    sa.Column('quantidade', sa.Numeric(precision=18, scale=4), nullable=True),
    sa.Column('unidade', sa.String(length=60), nullable=True),
    sa.Column('valor_unitario', sa.Numeric(precision=18, scale=4), nullable=True),
    sa.Column('valor_total', sa.Numeric(precision=18, scale=2), nullable=True),
    sa.Column('beneficio', sa.String(length=80), nullable=True),
    sa.Column('criterio_julgamento', sa.String(length=80), nullable=True),
    sa.ForeignKeyConstraint(['licitacao_id'], ['licitacoes.id'], name=op.f('fk_itens_licitacao_id_licitacoes'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_itens')),
    sa.UniqueConstraint('licitacao_id', 'numero', name=op.f('uq_itens_licitacao_id'))
    )
    op.create_table('paginas',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('documento_id', sa.Integer(), nullable=False),
    sa.Column('numero', sa.Integer(), nullable=False),
    sa.Column('arquivo', sa.String(length=300), nullable=True),
    sa.Column('pagina_no_arquivo', sa.Integer(), nullable=False),
    sa.Column('texto', sa.Text(), nullable=False),
    sa.Column('busca', postgresql.TSVECTOR(), sa.Computed("to_tsvector('portuguese', texto)", persisted=True), nullable=False),
    sa.ForeignKeyConstraint(['documento_id'], ['documentos.id'], name=op.f('fk_paginas_documento_id_documentos'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_paginas')),
    sa.UniqueConstraint('documento_id', 'numero', name=op.f('uq_paginas_documento_id'))
    )
    op.create_index('ix_paginas_busca', 'paginas', ['busca'], unique=False, postgresql_using='gin')


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_paginas_busca', table_name='paginas', postgresql_using='gin')
    op.drop_table('paginas')
    op.drop_table('itens')
    op.drop_table('documentos')
    op.drop_table('sincronizacoes')
    op.drop_index(op.f('ix_licitacoes_uf'), table_name='licitacoes')
    op.drop_index(op.f('ix_licitacoes_publicada_em'), table_name='licitacoes')
    op.drop_index(op.f('ix_licitacoes_encerramento_propostas'), table_name='licitacoes')
    op.drop_index(op.f('ix_licitacoes_detalhes'), table_name='licitacoes')
    op.drop_index('ix_licitacoes_busca', table_name='licitacoes', postgresql_using='gin')
    op.drop_table('licitacoes')
    # drop_table leaves the enum types behind; a later upgrade would collide with them.
    sa.Enum(name='statusdocumento').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='etapa').drop(op.get_bind(), checkfirst=True)
