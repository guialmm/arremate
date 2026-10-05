import enum
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Computed,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base, TimestampMixin


def pg_enum(cls: type[enum.Enum]) -> Enum:
    return Enum(cls, name=cls.__name__.lower(), values_callable=lambda e: [m.value for m in e])


class Etapa(str, enum.Enum):
    """Where a fetch from PNCP stands. Failures are retried by the next run."""

    pendente = "pendente"
    ok = "ok"
    falhou = "falhou"


class StatusDocumento(str, enum.Enum):
    pendente = "pendente"
    ok = "ok"
    falhou = "falhou"
    # .doc, .odt, scanned PDFs without a text layer: kept and counted, not read.
    nao_suportado = "nao_suportado"


class Licitacao(TimestampMixin, Base):
    __tablename__ = "licitacoes"
    __table_args__ = (
        UniqueConstraint("cnpj", "ano", "sequencial"),
        Index("ix_licitacoes_busca", "busca", postgresql_using="gin"),
    )

    # numeroControlePNCP, e.g. "83021808000182-1-000627/2026": stable across updates.
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    cnpj: Mapped[str] = mapped_column(String(14))
    ano: Mapped[int] = mapped_column(Integer)
    sequencial: Mapped[int] = mapped_column(Integer)

    orgao: Mapped[str] = mapped_column(String(300))
    unidade: Mapped[str | None] = mapped_column(String(300))
    uf: Mapped[str | None] = mapped_column(String(2), index=True)
    municipio: Mapped[str | None] = mapped_column(String(120))

    modalidade_id: Mapped[int] = mapped_column(Integer)
    modalidade: Mapped[str] = mapped_column(String(80))
    objeto: Mapped[str] = mapped_column(Text)
    informacao_complementar: Mapped[str | None] = mapped_column(Text)
    valor_estimado: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    srp: Mapped[bool] = mapped_column(default=False)  # sistema de registro de preços
    situacao: Mapped[str] = mapped_column(String(60))

    publicada_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    abertura_propostas: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    encerramento_propostas: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )
    atualizada_no_pncp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    link_origem: Mapped[str | None] = mapped_column(Text)
    raw: Mapped[dict] = mapped_column(JSONB)

    # Items and the document list come from slower endpoints, fetched separately.
    detalhes: Mapped[Etapa] = mapped_column(pg_enum(Etapa), default=Etapa.pendente, index=True)
    detalhes_tentativas: Mapped[int] = mapped_column(Integer, default=0)
    detalhes_erro: Mapped[str | None] = mapped_column(Text)

    busca: Mapped[str] = mapped_column(
        TSVECTOR,
        Computed(
            "to_tsvector('portuguese', objeto || ' ' || coalesce(informacao_complementar, ''))",
            persisted=True,
        ),
    )

    itens: Mapped[list["Item"]] = relationship(
        back_populates="licitacao", order_by="Item.numero", cascade="all, delete-orphan"
    )
    documentos: Mapped[list["Documento"]] = relationship(
        back_populates="licitacao", order_by="Documento.sequencial", cascade="all, delete-orphan"
    )


class Item(Base):
    __tablename__ = "itens"
    __table_args__ = (UniqueConstraint("licitacao_id", "numero"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    licitacao_id: Mapped[str] = mapped_column(ForeignKey("licitacoes.id", ondelete="CASCADE"))
    numero: Mapped[int] = mapped_column(Integer)
    descricao: Mapped[str] = mapped_column(Text)
    material_ou_servico: Mapped[str | None] = mapped_column(String(1))  # "M" | "S"
    quantidade: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    unidade: Mapped[str | None] = mapped_column(String(60))
    valor_unitario: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    valor_total: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    # "Exclusiva para ME/EPP", "Cota reservada"... decides who may bid at all.
    beneficio: Mapped[str | None] = mapped_column(String(80))
    criterio_julgamento: Mapped[str | None] = mapped_column(String(80))

    licitacao: Mapped[Licitacao] = relationship(back_populates="itens")


class Documento(Base):
    __tablename__ = "documentos"
    __table_args__ = (UniqueConstraint("licitacao_id", "sequencial"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    licitacao_id: Mapped[str] = mapped_column(ForeignKey("licitacoes.id", ondelete="CASCADE"))
    sequencial: Mapped[int] = mapped_column(Integer)
    titulo: Mapped[str] = mapped_column(String(500))
    tipo_id: Mapped[int | None] = mapped_column(Integer)
    tipo: Mapped[str | None] = mapped_column(String(120))
    url: Mapped[str] = mapped_column(Text)

    status: Mapped[StatusDocumento] = mapped_column(
        pg_enum(StatusDocumento), default=StatusDocumento.pendente
    )
    formato: Mapped[str | None] = mapped_column(String(10))
    nome_arquivo: Mapped[str | None] = mapped_column(String(300))
    tamanho_bytes: Mapped[int | None] = mapped_column(BigInteger)
    sha256: Mapped[str | None] = mapped_column(String(64))
    total_paginas: Mapped[int | None] = mapped_column(Integer)
    tentativas: Mapped[int] = mapped_column(Integer, default=0)
    erro: Mapped[str | None] = mapped_column(Text)
    baixado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    licitacao: Mapped[Licitacao] = relationship(back_populates="documentos")
    paginas: Mapped[list["Pagina"]] = relationship(
        back_populates="documento", order_by="Pagina.numero", cascade="all, delete-orphan"
    )


class Pagina(Base):
    """One page of extracted text: the unit the agent cites and the verifier checks."""

    __tablename__ = "paginas"
    __table_args__ = (
        UniqueConstraint("documento_id", "numero"),
        Index("ix_paginas_busca", "busca", postgresql_using="gin"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    documento_id: Mapped[int] = mapped_column(ForeignKey("documentos.id", ondelete="CASCADE"))
    # Sequential across the whole document (ZIPs hold several files).
    numero: Mapped[int] = mapped_column(Integer)
    # File inside a ZIP and the page within it, which is what a human looks up.
    arquivo: Mapped[str | None] = mapped_column(String(300))
    pagina_no_arquivo: Mapped[int] = mapped_column(Integer)
    texto: Mapped[str] = mapped_column(Text)
    busca: Mapped[str] = mapped_column(
        TSVECTOR, Computed("to_tsvector('portuguese', texto)", persisted=True)
    )

    documento: Mapped[Documento] = relationship(back_populates="paginas")


class Sincronizacao(Base):
    """Progress of the daily sweep, so a run that dies on page 17 resumes there."""

    __tablename__ = "sincronizacoes"

    dia: Mapped[date] = mapped_column(Date, primary_key=True)
    modalidade_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ultima_pagina: Mapped[int] = mapped_column(Integer, default=0)
    total_paginas: Mapped[int | None] = mapped_column(Integer)
    total_registros: Mapped[int | None] = mapped_column(Integer)
    concluida: Mapped[bool] = mapped_column(default=False)
    atualizada_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.now, onupdate=datetime.now
    )
