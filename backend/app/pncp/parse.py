"""PNCP JSON → column dicts. Kept pure so tests can feed recorded responses."""

from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

# PNCP timestamps carry no offset; they are Brasília time.
BRASILIA = ZoneInfo("America/Sao_Paulo")


def data_hora(valor: str | None) -> datetime | None:
    if not valor:
        return None
    dt = datetime.fromisoformat(valor)
    return dt if dt.tzinfo else dt.replace(tzinfo=BRASILIA)


def decimal(valor) -> Decimal | None:
    return None if valor is None else Decimal(str(valor))


def licitacao(r: dict) -> dict:
    orgao = r.get("orgaoEntidade") or {}
    unidade = r.get("unidadeOrgao") or {}
    return {
        "id": r["numeroControlePNCP"],
        "cnpj": orgao["cnpj"],
        "ano": r["anoCompra"],
        "sequencial": r["sequencialCompra"],
        "orgao": orgao.get("razaoSocial") or "",
        "unidade": unidade.get("nomeUnidade"),
        "uf": unidade.get("ufSigla"),
        "municipio": unidade.get("municipioNome"),
        "modalidade_id": r["modalidadeId"],
        "modalidade": r.get("modalidadeNome") or "",
        "objeto": (r.get("objetoCompra") or "").strip(),
        "informacao_complementar": r.get("informacaoComplementar"),
        "valor_estimado": decimal(r.get("valorTotalEstimado")),
        "srp": bool(r.get("srp")),
        "situacao": r.get("situacaoCompraNome") or "",
        "publicada_em": data_hora(r.get("dataPublicacaoPncp") or r.get("dataInclusao")),
        "abertura_propostas": data_hora(r.get("dataAberturaProposta")),
        "encerramento_propostas": data_hora(r.get("dataEncerramentoProposta")),
        "atualizada_no_pncp": data_hora(r.get("dataAtualizacaoGlobal") or r.get("dataAtualizacao")),
        "link_origem": r.get("linkSistemaOrigem"),
        "raw": r,
    }


def item(r: dict) -> dict:
    return {
        "numero": r["numeroItem"],
        "descricao": (r.get("descricao") or "").strip(),
        "material_ou_servico": r.get("materialOuServico"),
        "quantidade": decimal(r.get("quantidade")),
        "unidade": r.get("unidadeMedida"),
        "valor_unitario": decimal(r.get("valorUnitarioEstimado")),
        "valor_total": decimal(r.get("valorTotal")),
        "beneficio": r.get("tipoBeneficioNome"),
        "criterio_julgamento": r.get("criterioJulgamentoNome"),
    }


def documento(r: dict) -> dict:
    return {
        "sequencial": r["sequencialDocumento"],
        "titulo": (r.get("titulo") or "").strip()[:500],
        "tipo_id": r.get("tipoDocumentoId"),
        "tipo": r.get("tipoDocumentoNome"),
        "url": r.get("url") or r["uri"],
    }
