import logging
import azure.functions as func
import os
import base64
import time
import json
import urllib.request
import urllib.error
import unicodedata
import re

from azure.identity import DefaultAzureCredential
from azure.storage.filedatalake import DataLakeServiceClient

from io import BytesIO
import pandas as pd

from reportlab.lib.pagesizes import letter, landscape
from reportlab.lib import colors
from reportlab.pdfgen import canvas
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.platypus import Table, TableStyle
import tempfile

from azure.communication.email import EmailClient
from azure.core.exceptions import HttpResponseError

from PyPDF2 import PdfReader, PdfWriter

app = func.FunctionApp()
logging.getLogger("azure").setLevel(logging.WARNING)
logging.getLogger("azure.core.pipeline.policies.http_logging_policy").setLevel(logging.WARNING)
INTER_EMAIL_DELAY_SECONDS = float(os.getenv("INTER_EMAIL_DELAY_SECONDS", "2"))
ACS_EMAIL_MAX_ATTEMPTS = int(os.getenv("ACS_EMAIL_MAX_ATTEMPTS", "3"))
RECIPIENTS_CSV_PATH = os.getenv("RECIPIENTS_CSV_PATH", "csv/destinatarios.csv")
INSIGHTS_SOURCE_FOLDER = os.getenv("INSIGHTS_SOURCE_FOLDER", "csv/fonte")
INSIGHTS_SOURCE_FILENAME = os.getenv("INSIGHTS_SOURCE_FILENAME", "").strip()
REFERENCE_FILE_SYSTEM = os.getenv("REFERENCE_FILE_SYSTEM", "reference")
FILIAIS_REFERENCE_PATH = os.getenv("FILIAIS_REFERENCE_PATH", "Filiais.TXT")
CLIENTES_TABLE_LANDSCAPE = str(os.getenv("CLIENTES_TABLE_LANDSCAPE", "1")).strip().casefold() in {
    "1", "true", "yes", "sim", "on"
}
AFASTADOS_TABLE_LANDSCAPE = str(os.getenv("AFASTADOS_TABLE_LANDSCAPE", "1")).strip().casefold() in {
    "1", "true", "yes", "sim", "on"
}

_INSIGHTS_REQUIRED_COLUMNS = [
    "Unidade Emissora", "unidade emissora", "unidade emissora ", "unidade",
    "Unidade Receptora", "unidade receptora",
    "UF Destinatario", "UF do Destinatario", "UF destino", "UF de destino",
    "UF Remetente", "UF do Remetente", "UF Origem", "UF de origem",
    "UF Receptora", "UF da Unidade Receptora", "UF Recebedora",
    "CNPJ Pagador", "cnpj pagador", "CNPJ do Pagador", "cnpj do pagador",
    "Endereco do Pagador", "endereco do pagador", "Endereco Pagador", "endereco pagador",
    "CEP do Pagador", "cep do pagador", "Cidade do Pagador", "cidade do pagador",
    "UF do Pagador", "uf do pagador", "IE do Pagador", "ie do pagador",
    "CNPJ/CPF", "cnpj cpf", "CNPJ", "cnpj", "CPF", "cpf",
    "Cliente", "cliente", "Nome do Cliente", "nome do cliente",
    "Cliente Pagador", "cliente pagador", "Nome do Cliente Pagador", "nome do cliente pagador",
    "Endereco", "endereco", "Logradouro", "logradouro", "Endereco do Cliente", "endereco do cliente",
    "CEP", "cep", "CEP do Remetente", "cep do remetente",
    "Fone", "fone", "Telefone", "telefone", "Celular", "celular",
    "Fone do Pagador", "fone do pagador", "Telefone do Pagador", "telefone do pagador",
    "Cidade", "cidade", "Cidade do Destinatario", "cidade do destinatario", "Municipio", "municipio",
    "UF", "uf", "Estado", "estado",
    "IE", "ie", "Inscricao Estadual", "inscricao estadual", "Inscricao", "inscricao",
    "IE cliente remetente", "ie cliente remetente",
    "Peso Calc", "peso calc", "Peso Calculado", "peso calculado",
    "ValMerc", "valmerc", "Valor Mercadoria", "valor mercadoria",
    "Quantidade", "quantidade", "Qtd", "qtd", "Quant", "quant",
    "Cidade do Remetente", "cidade do remetente",
    "Login", "login",
    "Login do Usuario", "login do usuario",
    "Login do Vendedor", "login do vendedor",
    "Vendedor", "vendedor",
    "Nome do Vendedor", "nome do vendedor",
    "Tipo do Frete", "tipo do frete",
    "Tipo de Baixa", "tipo de baixa",
    "Data de Emissao", "data de emissao",
    "Data da Ultima Ocorrencia", "data da ultima ocorrencia",
    "Codigo da Ultima Ocorrencia", "codigo da ultima ocorrencia",
    "Usuario da Ultima Ocorrencia", "usuario da ultima ocorrencia",
    "Unidade da Ultima Ocorrencia", "unidade da ultima ocorrencia",
    "Descricao da Ultima Ocorrencia", "descricao da ultima ocorrencia",
    "Latitude da Ultima Ocorrencia", "latitude da ultima ocorrencia",
    "Longitude da Ultima Ocorrencia", "longitude da ultima ocorrencia",
    "Dias (Data da Ultima Ocorrencia)", "dias data da ultima ocorrencia",
    "Data do Ultimo Movimento", "data do ultimo movimento",
    "Data da Ultima Movimentacao", "data da ultima movimentacao",
    "Data da Ultima Interacao", "data da ultima interacao",
    "Data da Ultima Compra", "data da ultima compra",
    "Data da Ultima Venda", "data da ultima venda",
    "Data de Inclusao da Ultima Ocorrencia", "data de inclusao da ultima ocorrencia",
    "Valor do Frete", "valor do frete",
    "Valor Liquidado", "valor liquidado",
    "Tipo de Movimentacao", "tipo de movimentacao", "tipo movimentacao",
    "Direcao", "direcao", "Entrada/Saida", "entrada saida",
    "Recebido/Expedido", "recebido expedido",
    "Status Operacao", "status operacao",
]


def _parse_filiais_mapping_from_text(content: str) -> dict[str, str]:
    mapping: dict[str, str] = {}

    fixed_width_mapping = _parse_filiais_fixed_width_report(content)
    if fixed_width_mapping:
        return fixed_width_mapping

    for raw_line in content.splitlines():
        line = str(raw_line).strip()
        if not line:
            continue
        if line.startswith(("#", "//", ";")):
            continue

        normalized_line = _normalize_header_name(line)
        if "sigla" in normalized_line and "cidade" in normalized_line:
            continue

        sigla = None
        cidade = None

        for sep in ["=", ";", "\t", "|", ","]:
            if sep in line:
                parts = [p.strip() for p in line.split(sep) if p.strip()]
                if len(parts) >= 2:
                    sigla, cidade = parts[0], parts[1]
                    break

        if not sigla or not cidade:
            match = re.match(r"^\s*([A-Za-z0-9]{2,10})\s+(.+?)\s*$", line)
            if match:
                sigla = match.group(1)
                cidade = match.group(2)

        if not sigla or not cidade:
            continue

        key = str(sigla).strip().casefold()
        value = str(cidade).strip()
        if key and value:
            mapping[key] = value

    return mapping


def _parse_filiais_fixed_width_report(content: str) -> dict[str, str]:
    lines = content.splitlines()
    separator_line = None
    header_line = None

    for idx, line in enumerate(lines):
        if "+" in line and "---" in line:
            next_idx = idx + 1
            if next_idx < len(lines) and "SIG" in lines[next_idx].upper() and "CIDADE" in lines[next_idx].upper():
                separator_line = line.rstrip("\n")
                header_line = lines[next_idx].rstrip("\n")
                break

    if not separator_line or not header_line:
        return {}

    widths = [len(part) for part in separator_line.split("+")]
    starts = []
    current = 0
    for width in widths:
        starts.append((current, current + width))
        current += width + 1

    headers = [header_line[start:end].strip() for start, end in starts]
    normalized_headers = [_normalize_header_name(h) for h in headers]

    sig_idx = None
    cidade_idx = None
    for idx, name in enumerate(normalized_headers):
        if name.startswith("sig"):
            sig_idx = idx
        if "cidade" == name or name.startswith("cidade"):
            cidade_idx = idx

    if sig_idx is None or cidade_idx is None:
        return {}

    mapping: dict[str, str] = {}
    data_started = False
    for line in lines:
        raw = line.rstrip("\n")
        if not raw.strip():
            continue
        if raw == header_line or raw == separator_line:
            data_started = True
            continue
        if not data_started:
            continue
        if "RELACAO DE UNIDADES" in raw.upper() or raw.strip().startswith("PAG:"):
            continue
        if "+" in raw and "---" in raw:
            continue

        row = [raw[start:end].strip() for start, end in starts]
        if len(row) <= max(sig_idx, cidade_idx):
            continue

        sigla = row[sig_idx].strip().split()[0] if row[sig_idx].strip() else ""
        cidade = row[cidade_idx].strip()
        if not sigla or not cidade:
            continue

        cidade = re.sub(r"-[A-Z]{2}$", "", cidade).strip()
        if sigla.casefold() == "sig":
            continue

        mapping[sigla.casefold()] = cidade

    return mapping


def _load_filiais_mapping(service_client: DataLakeServiceClient) -> dict[str, str]:
    try:
        reference_fs = service_client.get_file_system_client(REFERENCE_FILE_SYSTEM)
        file_client = reference_fs.get_file_client(FILIAIS_REFERENCE_PATH)
        content_bytes = file_client.download_file().readall()

        decoded = None
        for encoding in ["utf-8", "latin-1", "iso-8859-1", "cp1252", "windows-1252"]:
            try:
                decoded = content_bytes.decode(encoding)
                break
            except UnicodeDecodeError:
                continue

        if decoded is None:
            decoded = content_bytes.decode("utf-8", errors="ignore")

        mapping = _parse_filiais_mapping_from_text(decoded)
        if mapping:
            logging.info(
                "Mapa de filiais carregado de %s/%s com %s entradas.",
                REFERENCE_FILE_SYSTEM,
                FILIAIS_REFERENCE_PATH,
                len(mapping),
            )
        else:
            logging.warning(
                "Arquivo %s/%s lido, mas sem mapeamentos validos de sigla->cidade.",
                REFERENCE_FILE_SYSTEM,
                FILIAIS_REFERENCE_PATH,
            )
        return mapping
    except Exception as exc:
        logging.warning(
            "Nao foi possivel carregar mapa de filiais em %s/%s: %s",
            REFERENCE_FILE_SYSTEM,
            FILIAIS_REFERENCE_PATH,
            exc,
        )
        return {}


def _read_csv_from_datalake(
    file_system,
    path: str,
    sep: str = ",",
    skiprows: int = 0,
    usecols=None,
    nrows: int | None = None,
    dtype=None,
) -> pd.DataFrame:
    file_client = file_system.get_file_client(path)
    download = file_client.download_file()
    content = download.readall()
    
    # Tenta múltiplos encodings (comum em arquivos de origem variada)
    encodings = ["utf-8", "latin-1", "iso-8859-1", "cp1252", "windows-1252"]
    for encoding in encodings:
        try:
            return pd.read_csv(
                BytesIO(content),
                sep=sep,
                encoding=encoding,
                skiprows=skiprows,
                usecols=usecols,
                nrows=nrows,
                dtype=dtype,
                low_memory=False,
            )
        except (UnicodeDecodeError, UnicodeError):
            continue
    
    # Se nenhum encoding funcionou, tenta sem especificar (fallback)
    logging.warning("Nenhum encoding padrão funcionou para %s. Tentando fallback com erros ignorados.", path)
    return pd.read_csv(
        BytesIO(content),
        sep=sep,
        encoding="utf-8",
        errors="ignore",
        skiprows=skiprows,
        usecols=usecols,
        nrows=nrows,
        dtype=dtype,
        low_memory=False,
    )


def _pick_insights_columns(columns: list[str]) -> list[str]:
    normalized_candidates = {_normalize_header_name(c) for c in _INSIGHTS_REQUIRED_COLUMNS}
    normalized_preferred = {_normalize_header_name(c) for c in _PREFERRED_METRIC_COLUMNS}

    selected = []
    for col in columns:
        col_norm = _normalize_header_name(col)
        if col_norm in normalized_candidates or col_norm in normalized_preferred:
            selected.append(col)

    # Garante que exista ao menos a estrutura base para regras de frete.
    if not selected:
        return columns

    return selected


def _list_insights_source_paths(file_system, folder_path: str, preferred_filename: str) -> list[str]:
    paths = list(file_system.get_paths(path=folder_path, recursive=False))
    csv_files = []
    for path_item in paths:
        if getattr(path_item, "is_directory", False):
            continue
        name = getattr(path_item, "name", "")
        if str(name).lower().endswith(".csv"):
            csv_files.append(str(name))

    if not csv_files:
        raise FileNotFoundError(f"Nenhum CSV encontrado em {folder_path}")

    if preferred_filename:
        expected_full_path = f"{folder_path.rstrip('/')}/{preferred_filename}"
        for file_path in csv_files:
            if file_path == expected_full_path or file_path.endswith(f"/{preferred_filename}"):
                return [file_path]
        raise FileNotFoundError(f"Arquivo {preferred_filename} nao encontrado em {folder_path}")

    csv_files.sort()
    return csv_files


def _load_insights_from_datalake(
    file_system,
    folder_path: str,
    preferred_filename: str,
    allowed_units: set[str] | None = None,
) -> tuple[pd.DataFrame, list[str]]:
    source_paths = _list_insights_source_paths(file_system, folder_path, preferred_filename)
    frames: list[pd.DataFrame] = []

    for source_path in source_paths:
        try:
            header_df = _read_csv_from_datalake(
                file_system,
                source_path,
                sep=";",
                skiprows=1,
                nrows=0,
            )
            selected_columns = _pick_insights_columns(list(header_df.columns))

            source_df = _read_csv_from_datalake(
                file_system,
                source_path,
                sep=";",
                skiprows=1,
                usecols=selected_columns,
                dtype=str,
            )
            if source_df.empty:
                continue

            if allowed_units:
                unidade_emissora_col = _find_column(
                    source_df,
                    ["Unidade Emissora", "unidade emissora", "unidade emissora ", "unidade"],
                )
                unidade_receptora_col = _find_column(
                    source_df,
                    ["Unidade Receptora", "unidade receptora"],
                )

                if unidade_emissora_col or unidade_receptora_col:
                    before_count = len(source_df)
                    emissora_mask = (
                        source_df[unidade_emissora_col].astype(str).str.strip().str.casefold().isin(allowed_units)
                        if unidade_emissora_col
                        else pd.Series(False, index=source_df.index)
                    )
                    receptora_mask = (
                        source_df[unidade_receptora_col].astype(str).str.strip().str.casefold().isin(allowed_units)
                        if unidade_receptora_col
                        else pd.Series(False, index=source_df.index)
                    )

                    source_df = source_df[emissora_mask | receptora_mask].copy()
                    logging.info(
                        "Filtro por unidades (emissora/receptora) em %s: %s -> %s linhas.",
                        source_path,
                        before_count,
                        len(source_df),
                    )
                    if source_df.empty:
                        continue

            source_df["__source_file"] = source_path
            frames.append(source_df)
            logging.info(
                "CSV %s carregado com %s linhas e %s colunas selecionadas.",
                source_path,
                len(source_df),
                len(source_df.columns),
            )
        except Exception as exc:
            logging.warning("Falha ao ler CSV de insights %s: %s", source_path, exc)

    if not frames:
        return pd.DataFrame(), source_paths

    merged = pd.concat(frames, ignore_index=True, sort=False)
    return merged, source_paths


def _normalize_header_name(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower().strip()

    for sep in ["/", "-", "_", "|"]:
        text = text.replace(sep, " ")

    text = "".join(ch if ch.isalnum() or ch.isspace() else " " for ch in text)
    return " ".join(text.split())


def _find_column(df: pd.DataFrame, candidates: list[str]) -> str | None:
    normalized = {_normalize_header_name(col): col for col in df.columns}
    for candidate in candidates:
        col = normalized.get(_normalize_header_name(candidate))
        if col is not None:
            return col
    return None


# Campos que parecem identificadores/codigos e nao devem virar metricas de negocio.
_COLUMN_ID_KEYWORDS = frozenset({
    "numero", "serie", "chave", "cnpj", "cpf", "inscricao", "cfop", "lote",
    "cep", "codigo", "setor", "abc", "aliquota", "placa", "login", "fone",
    "celular", "ie cliente", "rel de", "unnamed",
})

# Metricas mais relevantes para operacao/logistica (tentar usar estas primeiro).
_PREFERRED_METRIC_COLUMNS = [
    "Valor do Frete",
    "Valor da Mercadoria",
    "Valor Liquidado",
    "Frete NTC",
    "Peso Real em Kg",
    "Quantidade de Volumes",
    "Quantidade de Dias de Atraso",
]


def _is_metric_column(col: str) -> bool:
    name = str(col).strip().lower()
    if len(name) <= 2:
        return False
    return not any(keyword in name for keyword in _COLUMN_ID_KEYWORDS)


def _parse_br_numeric(series: pd.Series) -> pd.Series:
    # Converte formato brasileiro (1.234,56) para float.
    cleaned = (
        series.astype(str)
        .str.strip()
        .str.replace(r"\.", "", regex=True)
        .str.replace(",", ".", regex=False)
    )
    return pd.to_numeric(cleaned, errors="coerce")


def _format_brl(value: float) -> str:
    formatted = f"{value:,.2f}"
    formatted = formatted.replace(",", "_").replace(".", ",").replace("_", ".")
    return f"R$ {formatted}"


def _format_number_ptbr(value: float) -> str:
    formatted = f"{value:,.2f}"
    return formatted.replace(",", "_").replace(".", ",").replace("_", ".")


def _parse_brl_to_float(value: str) -> float:
    text = str(value).replace("R$", "").strip()
    text = text.replace(".", "").replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return 0.0


def _parse_percent_to_float(value: str) -> float:
    text = str(value).replace("%", "").strip()
    try:
        return float(text)
    except ValueError:
        return 0.0


def _is_negative_display_value(value: str) -> bool:
    text = str(value).strip()
    if not text or text == "-":
        return False

    # Percentual (ex.: -9%)
    if text.endswith("%"):
        try:
            return float(text.replace("%", "").replace(",", ".")) < 0
        except ValueError:
            return False

    # Monetario BR (ex.: R$ -1.234,56)
    if "R$" in text:
        try:
            numeric = text.replace("R$", "").strip().replace(".", "").replace(",", ".")
            return float(numeric) < 0
        except ValueError:
            return False

    # Numerico generico (ex.: -123,45)
    try:
        return float(text.replace(".", "").replace(",", ".")) < 0
    except ValueError:
        return False


def _is_growth_header(value: str) -> bool:
    header = _normalize_header_name(str(value))
    return "cres" in header or "desempenho" in header


def _safe_growth_percent(old_value: float, new_value: float) -> str:
    if old_value == 0:
        return "-"
    pct = round(((new_value / old_value) - 1) * 100)
    if pct == 0:
        return "0%"
    return f"{pct:.0f}%"


def _build_soft_operational_comment(
    table_data: list[list[str]],
    filial: str,
    bloco_nome: str,
) -> str:
    if len(table_data) < 2:
        return ""

    total_row = table_data[1]
    if len(total_row) >= 6:
        valor_ano1 = str(total_row[2])
        valor_ano2 = str(total_row[4])
        desempenho = str(total_row[5])
    elif len(total_row) >= 4:
        valor_ano1 = str(total_row[1])
        valor_ano2 = str(total_row[2])
        desempenho = str(total_row[3])
    else:
        return ""

    growth = _parse_percent_to_float(desempenho)
    bloco_txt = bloco_nome.lower().strip()

    if bloco_txt == "total":
        if growth > 0:
            return (
                f"No consolidado total, a filial {filial.upper()} apresentou crescimento de {desempenho}, "
                f"com evolucao de {valor_ano1} para {valor_ano2}, mantendo resultado positivo no periodo."
            )
        if growth < 0:
            return (
                f"No consolidado total, a filial {filial.upper()} registrou leve reducao de {abs(growth):.0f}%, "
                f"com variacao de {valor_ano1} para {valor_ano2}, mantendo acompanhamento proximo da operacao."
            )
        return (
            f"No consolidado total, a filial {filial.upper()} manteve estabilidade no periodo, "
            f"com resultado de {valor_ano1} para {valor_ano2}."
        )

    if bloco_txt == "expedidos":
        if growth > 0:
            return (
                f"Nos fretes expedidos, a filial {filial.upper()} apresentou crescimento de {desempenho}, "
                f"evoluindo de {valor_ano1} para {valor_ano2} no periodo analisado."
            )
        if growth < 0:
            return (
                f"Nos fretes expedidos, a filial {filial.upper()} teve uma acomodacao de {abs(growth):.0f}%, "
                f"com ajuste de {valor_ano1} para {valor_ano2}, em um comportamento pontual do periodo."
            )
        return (
            f"Nos fretes expedidos, a filial {filial.upper()} manteve estabilidade no periodo, "
            f"com resultado de {valor_ano1} para {valor_ano2}."
        )

    if bloco_txt == "recebidos":
        if growth > 0:
            return (
                f"Nos fretes recebidos, a filial {filial.upper()} apresentou crescimento de {desempenho}, "
                f"com variacao de {valor_ano1} para {valor_ano2} no periodo analisado."
            )
        if growth < 0:
            return (
                f"Nos fretes recebidos, a filial {filial.upper()} registrou leve reducao de {abs(growth):.0f}%, "
                f"com variacao de {valor_ano1} para {valor_ano2}, mantendo o resultado geral sob controle."
            )
        return (
            f"Nos fretes recebidos, a filial {filial.upper()} manteve estabilidade no periodo, "
            f"com resultado de {valor_ano1} para {valor_ano2}."
        )

    if "fora do estado" in bloco_txt:
        if growth > 0:
            return (
                f"Nos fretes que chegam ou vao para fora do estado, a filial {filial.upper()} teve desempenho positivo de {desempenho}, "
                f"com evolucao de {valor_ano1} para {valor_ano2} no periodo analisado."
            )
        if growth < 0:
            return (
                f"Nos fretes que chegam ou vao para fora do estado, houve leve reducao de {abs(growth):.0f}% para a filial {filial.upper()}, "
                f"com variacao de {valor_ano1} para {valor_ano2}, mantendo resultado geral positivo no periodo."
            )
        return (
            f"Nos fretes que chegam ou vao para fora do estado, a filial {filial.upper()} manteve estabilidade no periodo, "
            f"com resultado de {valor_ano1} para {valor_ano2}."
        )

    if growth > 0:
        return (
            f"No consolidado de {bloco_txt}, a filial {filial.upper()} apresentou crescimento de {desempenho}, "
            f"com evolucao de {valor_ano1} para {valor_ano2} no periodo analisado."
        )
    if growth < 0:
        return (
            f"No consolidado de {bloco_txt}, a filial {filial.upper()} registrou leve reducao de {abs(growth):.0f}%, "
            f"com variacao de {valor_ano1} para {valor_ano2}, mantendo acompanhamento operacional."
        )
    return (
        f"No consolidado de {bloco_txt}, a filial {filial.upper()} manteve estabilidade no periodo, "
        f"com resultado de {valor_ano1} para {valor_ano2}."
    )


def _build_ai_operational_comment_if_configured(
    table_data: list[list[str]],
    filial: str,
    bloco_nome: str,
) -> str | None:
    endpoint = os.getenv("AOAI_ENDPOINT")
    deployment = os.getenv("AOAI_DEPLOYMENT")
    api_key = os.getenv("AOAI_API_KEY")
    api_version = os.getenv("AOAI_API_VERSION", "2024-10-21")

    if not endpoint or not deployment or not api_key:
        return None

    if len(table_data) < 2:
        return None

    facts = {
        "filial": filial.upper(),
        "bloco": bloco_nome,
        "cabecalho": table_data[0],
        "linha_total": table_data[1],
        "linhas_destaque": table_data[2:5],
    }

    base_endpoint = endpoint.rstrip("/")
    url = (
        f"{base_endpoint}/openai/deployments/{deployment}/chat/completions"
        f"?api-version={api_version}"
    )

    payload = {
        "messages": [
            {
                "role": "system",
                "content": (
                    "Voce escreve comunicados operacionais em portugues para colaboradores. "
                    "Regras obrigatorias: produzir uma unica frase, linguagem simples e suave, "
                    "sem tom alarmista, sem inventar dados, usar apenas os fatos fornecidos."
                ),
            },
            {
                "role": "user",
                "content": (
                    "Com base nos fatos abaixo, escreva uma frase unica no estilo de relatorio operacional. "
                    "A frase deve destacar crescimento, estabilidade ou reducao de forma suave. "
                    "Nao use listas, nao use markdown, nao acrescente numeros que nao estejam nos fatos.\n\n"
                    f"Fatos (JSON):\n{json.dumps(facts, ensure_ascii=False)}"
                ),
            },
        ],
        "max_tokens": 120,
        "temperature": 0.2,
    }

    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "api-key": api_key,
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            data = json.loads(response.read().decode("utf-8"))
            usage = data.get("usage") or {}
            logging.info(
                "Uso Azure OpenAI | tipo=comentario_operacional | filial=%s | bloco=%s | prompt_tokens=%s | completion_tokens=%s | total_tokens=%s",
                filial,
                bloco_nome,
                usage.get("prompt_tokens"),
                usage.get("completion_tokens"),
                usage.get("total_tokens"),
            )
            choices = data.get("choices") or []
            if not choices:
                return None

            content = choices[0].get("message", {}).get("content", "").strip()
            if not content:
                return None

            # Garante uma frase unica no PDF.
            one_line = " ".join(content.replace("\n", " ").split())
            if not one_line.endswith((".", "!", "?")):
                one_line += "."
            return one_line
    except Exception as exc:
        logging.warning(
            "Falha ao gerar comentario dinamico via IA para %s/%s: %s",
            filial,
            bloco_nome,
            exc,
        )
        return None


def _build_operational_comment(
    table_data: list[list[str]],
    filial: str,
    bloco_nome: str,
) -> str:
    ai_comment = _build_ai_operational_comment_if_configured(table_data, filial, bloco_nome)
    if ai_comment:
        logging.info(
            "Comentario operacional gerado por IA | filial=%s | bloco=%s",
            filial,
            bloco_nome,
        )
        return ai_comment

    logging.info(
        "Comentario operacional gerado por fallback deterministico | filial=%s | bloco=%s",
        filial,
        bloco_nome,
    )
    return _build_soft_operational_comment(table_data, filial, bloco_nome)


def _draw_wrapped_text(
    pdf: canvas.Canvas,
    text: str,
    y_start: float,
    x: float = 50,
    max_width: float = 520,
    font_name: str = "Helvetica",
    font_size: float = 8.5,
    line_height: float = 10.5,
) -> float:
    if not text:
        return y_start

    pdf.setFont(font_name, font_size)
    words = text.split()
    if not words:
        return y_start

    lines = []
    current = words[0]
    for word in words[1:]:
        probe = f"{current} {word}"
        if pdf.stringWidth(probe, font_name, font_size) <= max_width:
            current = probe
        else:
            lines.append(current)
            current = word
    lines.append(current)

    y = y_start
    for line in lines:
        pdf.drawString(x, y, line)
        y -= line_height

    return y


def _classify_metric_type(metric_name: str) -> str:
    """Classifica a métrica em tipo (Financeiro, Operacional, Desempenho)."""
    name_lower = metric_name.lower()
    
    if any(word in name_lower for word in ["valor", "frete", "mercadoria", "liquidado", "preco"]):
        return "Financeiro"
    if any(word in name_lower for word in ["peso", "kg", "volume", "quantidade", "unidade"]):
        return "Operacional"
    if any(word in name_lower for word in ["atraso", "dia", "performance", "desempenho"]):
        return "Desempenho"
    return "Análise"


def _format_metric_line_for_pdf(line: str) -> tuple[str, str, str]:
    """Parseia linha de métrica e retorna (classificação, métrica, valores formatados)."""
    # Esperado: "- Peso Real em Kg: total=201032.46 | media=42.58"
    if not line.strip().startswith("-"):
        return ("", "", "")
    
    line = line.strip()[2:].strip()  # Remove "- "
    parts = line.split(":")
    if len(parts) < 2:
        return ("", "", "")
    
    metric_name = parts[0].strip()
    metric_type = _classify_metric_type(metric_name)
    values_str = ":".join(parts[1:]).strip()
    
    # Parseia total e media
    try:
        total_part = [p.strip() for p in values_str.split("|") if "total" in p.lower()]
        media_part = [p.strip() for p in values_str.split("|") if "media" in p.lower()]
        
        total_val = float(total_part[0].split("=")[1]) if total_part else 0.0
        media_val = float(media_part[0].split("=")[1]) if media_part else 0.0

        if metric_type == "Financeiro":
            formatted_values = f"Total: {_format_brl(total_val)} | Média: {_format_brl(media_val)}"
        else:
            formatted_values = f"Total: {_format_number_ptbr(total_val)} | Média: {_format_number_ptbr(media_val)}"

        return metric_type, metric_name, formatted_values
    except Exception:
        return metric_type, metric_name, values_str


def _send_email_with_retry(email_client: EmailClient, message: dict, email: str) -> None:
    for attempt in range(1, ACS_EMAIL_MAX_ATTEMPTS + 1):
        try:
            poller = email_client.begin_send(message)
            poller.result()
            return
        except HttpResponseError as e:
            status = getattr(e, "status_code", None)
            retry_after = None
            if getattr(e, "response", None) is not None:
                retry_after = e.response.headers.get("Retry-After")

            if status == 429 and attempt < ACS_EMAIL_MAX_ATTEMPTS:
                try:
                    delay_seconds = float(retry_after) if retry_after else float(attempt * 5)
                except (TypeError, ValueError):
                    delay_seconds = float(attempt * 5)

                delay_seconds = max(1.0, min(delay_seconds, 30.0))
                logging.warning(
                    "Throttle ACS (429) ao enviar para %s. Tentativa %s/%s. Aguardando %.1fs antes de retry.",
                    email,
                    attempt,
                    ACS_EMAIL_MAX_ATTEMPTS,
                    delay_seconds,
                )
                time.sleep(delay_seconds)
                continue

            if status == 429:
                logging.error(
                    "Throttle ACS (429) persistente ao enviar para %s apos %s tentativas.",
                    email,
                    ACS_EMAIL_MAX_ATTEMPTS,
                )
            raise


def _normalize_tipo_frete(value: str) -> str | None:
    token = str(value).strip().upper()
    if token in {"CV", "CP", "FV", "FP", "CIF", "FOB"}:
        return token
    if "CIF" in token:
        return "CIF"
    if "FOB" in token:
        return "FOB"
    return None


def _group_tipo_frete(tipo: str) -> str | None:
    if tipo in {"CV", "CP", "CIF"}:
        return "CIF"
    if tipo in {"FV", "FP", "FOB"}:
        return "FOB"
    return None


def _compute_valor_frete_final(df: pd.DataFrame) -> pd.Series:
    tipo_baixa_col = _find_column(df, ["Tipo de Baixa", "tipo de baixa"])
    frete_col = _find_column(df, ["Valor do Frete", "valor do frete"])
    liquidado_col = _find_column(df, ["Valor Liquidado", "valor liquidado"])

    base_nan = pd.Series(float("nan"), index=df.index, dtype="float64")
    valor_frete = _parse_br_numeric(df[frete_col]) if frete_col else base_nan.copy()
    valor_liquidado = _parse_br_numeric(df[liquidado_col]) if liquidado_col else base_nan.copy()

    if tipo_baixa_col and liquidado_col:
        tipo_baixa = df[tipo_baixa_col].astype(str).str.strip().str.upper()
        is_liquidado = tipo_baixa.str.contains("LIQUIDADO", na=False)
        valor_final = valor_frete.where(~is_liquidado, valor_liquidado)
    else:
        valor_final = valor_frete if frete_col else valor_liquidado

    return valor_final.fillna(valor_frete).fillna(valor_liquidado)


def _extract_ano_series(df: pd.DataFrame, date_col: str) -> pd.Series:
    parsed_dates = pd.to_datetime(df[date_col], format="%d/%m/%y", errors="coerce")
    if parsed_dates.isna().all():
        parsed_dates = pd.to_datetime(df[date_col], format="%d/%m/%Y", errors="coerce")
    return parsed_dates.dt.year


def _extract_datetime_series(df: pd.DataFrame, date_col: str) -> pd.Series:
    parsed_dates = pd.to_datetime(df[date_col], format="%d/%m/%y", errors="coerce")
    if parsed_dates.isna().all():
        parsed_dates = pd.to_datetime(df[date_col], format="%d/%m/%Y", errors="coerce")
    return parsed_dates


def _month_name_pt(month: int) -> str:
    names = {
        1: "JANEIRO",
        2: "FEVEREIRO",
        3: "MARCO",
        4: "ABRIL",
        5: "MAIO",
        6: "JUNHO",
        7: "JULHO",
        8: "AGOSTO",
        9: "SETEMBRO",
        10: "OUTUBRO",
        11: "NOVEMBRO",
        12: "DEZEMBRO",
    }
    return names.get(int(month), str(month))


def _build_frete_tables(branch_df: pd.DataFrame) -> str:
    tipo_col = _find_column(branch_df, ["Tipo do Frete", "tipo do frete"])
    date_col = _find_column(branch_df, ["Data de Emissao", "data de emissao"])

    if not tipo_col or not date_col:
        return ""

    tmp = branch_df[[tipo_col, date_col]].copy()
    tmp["tipo"] = tmp[tipo_col].apply(_normalize_tipo_frete)
    tmp["grupo"] = tmp["tipo"].apply(lambda v: _group_tipo_frete(v) if v else None)
    tmp["valor"] = _compute_valor_frete_final(branch_df)
    tmp["ano"] = _extract_ano_series(tmp, date_col)

    tmp = tmp.dropna(subset=["grupo", "valor", "ano"])
    if tmp.empty:
        return ""

    years = sorted(tmp["ano"].astype(int).unique().tolist())
    if len(years) == 1:
        y1, y2 = years[0], years[0]
    else:
        y1, y2 = years[-2], years[-1]

    period_df = tmp[tmp["ano"].isin({y1, y2})].copy()

    def _agg_line(label: str, frame: pd.DataFrame) -> tuple[str, int, float, int, float, str]:
        q1 = int((frame["ano"] == y1).sum())
        q2 = int((frame["ano"] == y2).sum())
        v1 = float(frame.loc[frame["ano"] == y1, "valor"].sum())
        v2 = float(frame.loc[frame["ano"] == y2, "valor"].sum())
        return label, q1, v1, q2, v2, _safe_growth_percent(v1, v2)

    lines = []
    lines.append(f"Resumo por Tipo do Frete ({y1} x {y2})")
    lines.append("Linha | " + str(y1) + " Qtd | " + str(y1) + " Valor | " + str(y2) + " Qtd | " + str(y2) + " Valor | Desempenho")
    for label, q1, v1, q2, v2, perf in [_agg_line("TOTAL", period_df), _agg_line("CIF", period_df[period_df["grupo"] == "CIF"]), _agg_line("FOB", period_df[period_df["grupo"] == "FOB"])]:
        lines.append(
            f"{label} | {q1} | {_format_brl(v1)} | {q2} | {_format_brl(v2)} | {perf}"
        )

    lines.append("")
    lines.append("Detalhe de codigos (CV/CP/FV/FP)")
    lines.append("Codigo | " + str(y1) + " Qtd | " + str(y1) + " Valor | " + str(y2) + " Qtd | " + str(y2) + " Valor | Desempenho")
    for code in ["CV", "CP", "FV", "FP"]:
        detail_lines = _agg_line(code, period_df[period_df["tipo"] == code])
        lines.append(
            f"{detail_lines[0]} | {detail_lines[1]} | {_format_brl(detail_lines[2])} | {detail_lines[3]} | {_format_brl(detail_lines[4])} | {detail_lines[5]}"
        )

    return "\n".join(lines)


def _build_expedidos_recebidos_tables(
    totals_df: pd.DataFrame,
    filial: str,
) -> str:
    if totals_df.empty:
        return ""

    unidade_emissora_col = _find_column(totals_df, ["Unidade Emissora", "unidade emissora", "unidade emissora ", "unidade"])
    unidade_receptora_col = _find_column(totals_df, ["Unidade Receptora", "unidade receptora"])
    date_col = _find_column(totals_df, ["Data de Emissao", "data de emissao"])
    if not unidade_emissora_col or not unidade_receptora_col or not date_col:
        return ""

    tipo_frete_col = _find_column(totals_df, ["Tipo do Frete", "tipo do frete"])

    tmp = totals_df[[unidade_emissora_col, unidade_receptora_col, date_col]].copy()
    if tipo_frete_col:
        tmp["tipo_frete"] = totals_df[tipo_frete_col]
    else:
        tmp["tipo_frete"] = ""
    tmp["valor_final"] = _compute_valor_frete_final(totals_df)
    tmp["ano"] = _extract_ano_series(tmp, date_col)
    tmp = tmp.dropna(subset=["valor_final", "ano"])
    if tmp.empty:
        return ""

    filial_norm = str(filial).strip().casefold()
    lines: list[str] = []

    def _append_compact_table(section_title: str, frame: pd.DataFrame) -> None:
        if frame.empty:
            return

        frame = frame.copy()
        years = sorted(frame["ano"].astype(int).unique().tolist())
        if not years:
            return
        if len(years) == 1:
            y1, y2 = years[0], years[0]
        else:
            y1, y2 = years[-2], years[-1]

        frame = frame[frame["ano"].isin({y1, y2})].copy()
        if frame.empty:
            return

        frame["tipo_normalizado"] = frame["tipo_frete"].apply(_normalize_tipo_frete)
        frame["grupo"] = frame["tipo_normalizado"].apply(lambda v: _group_tipo_frete(v) if v else None)

        def _line(label: str, data: pd.DataFrame) -> str:
            q1 = int((data["ano"] == y1).sum())
            q2 = int((data["ano"] == y2).sum())
            v1 = float(data.loc[data["ano"] == y1, "valor_final"].sum())
            v2 = float(data.loc[data["ano"] == y2, "valor_final"].sum())
            return f"{label} | {q1} | {_format_brl(v1)} | {q2} | {_format_brl(v2)} | {_safe_growth_percent(v1, v2)}"

        if lines:
            lines.append("")
        lines.append(section_title)
        lines.append("Linha | " + str(y1) + " Qtd | " + str(y1) + " Valor | " + str(y2) + " Qtd | " + str(y2) + " Valor | Desempenho")
        lines.append(_line("TOTAL", frame))
        lines.append(_line("CIF", frame[frame["grupo"] == "CIF"]))
        lines.append(_line("FOB", frame[frame["grupo"] == "FOB"]))

    expedidos_df = tmp[
        tmp[unidade_emissora_col].astype(str).str.strip().str.casefold() == filial_norm
    ].copy()
    _append_compact_table("Tabela de Valores Expedidos (Frete Final)", expedidos_df)

    recebidos_df = tmp[
        tmp[unidade_receptora_col].astype(str).str.strip().str.casefold() == filial_norm
    ].copy()
    _append_compact_table("Tabela de Valores Recebidos (Frete Final)", recebidos_df)

    return "\n".join(lines)


def _build_filial_scope_df(totals_df: pd.DataFrame, filial: str) -> pd.DataFrame:
    if totals_df.empty:
        return pd.DataFrame()

    unidade_emissora_col = _find_column(totals_df, ["Unidade Emissora", "unidade emissora", "unidade emissora ", "unidade"])
    unidade_receptora_col = _find_column(totals_df, ["Unidade Receptora", "unidade receptora"])
    if not unidade_emissora_col or not unidade_receptora_col:
        return pd.DataFrame()

    filial_norm = str(filial).strip().casefold()
    mask_exp = totals_df[unidade_emissora_col].astype(str).str.strip().str.casefold() == filial_norm
    mask_rec = totals_df[unidade_receptora_col].astype(str).str.strip().str.casefold() == filial_norm

    scoped = totals_df[mask_exp | mask_rec].copy()
    if scoped.empty:
        return scoped

    movement_col = _find_column(
        scoped,
        [
            "Tipo de Movimentacao", "tipo de movimentacao", "tipo movimentacao",
            "Direcao", "direcao", "Entrada/Saida", "entrada saida",
            "Recebido/Expedido", "recebido expedido",
            "Status Operacao", "status operacao",
        ],
    )
    if not movement_col:
        movement_col = "Recebido/Expedido"
        scoped[movement_col] = ""

    scoped.loc[mask_exp.loc[scoped.index] & ~mask_rec.loc[scoped.index], movement_col] = "EXPEDIDO"
    scoped.loc[mask_rec.loc[scoped.index] & ~mask_exp.loc[scoped.index], movement_col] = "RECEBIDO"
    scoped.loc[mask_rec.loc[scoped.index] & mask_exp.loc[scoped.index], movement_col] = "INTERNO"
    return scoped


def _build_uf_emphasis_table(
    totals_df: pd.DataFrame,
    filial: str,
) -> str:
    if totals_df.empty:
        return ""

    unidade_emissora_col = _find_column(totals_df, ["Unidade Emissora", "unidade emissora", "unidade emissora ", "unidade"])
    unidade_receptora_col = _find_column(totals_df, ["Unidade Receptora", "unidade receptora"])
    date_col = _find_column(totals_df, ["Data de Emissao", "data de emissao"])
    uf_dest_col = _find_column(
        totals_df,
        [
            "UF Destinatario", "UF do Destinatario", "UF destino", "UF de destino",
            "UF Receptora", "UF da Unidade Receptora", "UF Recebedora",
        ],
    )
    uf_orig_col = _find_column(
        totals_df,
        [
            "UF do remetente", "UF Remetente", "UF origem", "UF de origem",
            "UF Origem", "UF",
        ],
    )

    if not unidade_emissora_col or not unidade_receptora_col or not date_col:
        return ""

    filial_norm = str(filial).strip().casefold()
    expedidos_df = totals_df[
        totals_df[unidade_emissora_col].astype(str).str.strip().str.casefold() == filial_norm
    ].copy()
    recebidos_df = totals_df[
        totals_df[unidade_receptora_col].astype(str).str.strip().str.casefold() == filial_norm
    ].copy()

    parts = []
    if uf_dest_col and not expedidos_df.empty:
        exp = expedidos_df.copy()
        exp["uf"] = exp[uf_dest_col].astype(str).str.strip().str.upper()
        parts.append(exp)

    if uf_orig_col and not recebidos_df.empty:
        rec = recebidos_df.copy()
        rec["uf"] = rec[uf_orig_col].astype(str).str.strip().str.upper()
        parts.append(rec)

    if not parts:
        return ""

    tmp = pd.concat(parts, ignore_index=False, sort=False)

    tmp["valor_final"] = _compute_valor_frete_final(tmp)
    tmp["ano"] = _extract_ano_series(tmp, date_col)
    tmp = tmp.dropna(subset=["valor_final", "ano"])
    tmp = tmp[tmp["uf"] != ""]
    if tmp.empty:
        return ""

    years = sorted(tmp["ano"].astype(int).unique().tolist())
    if len(years) == 1:
        y1, y2 = years[0], years[0]
    else:
        y1, y2 = years[-2], years[-1]

    tmp = tmp[tmp["ano"].isin({y1, y2})].copy()
    if tmp.empty:
        return ""

    pivot = tmp.groupby(["uf", "ano"]) ["valor_final"].sum().unstack(fill_value=0.0)
    if y1 not in pivot.columns:
        pivot[y1] = 0.0
    if y2 not in pivot.columns:
        pivot[y2] = 0.0
    pivot = pivot[[y1, y2]].sort_values(by=y2, ascending=False)

    max_ufs = 6
    display_rows = pivot.head(max_ufs)
    if len(pivot) > max_ufs:
        others = pivot.iloc[max_ufs:].sum(axis=0)
        display_rows.loc["OUTROS"] = others

    lines = []
    lines.append("Tabela de Valores por UF (Frete Final)")
    lines.append("Linha | " + str(y1) + " Valor | " + str(y2) + " Valor | Desempenho")

    total_y1 = float(tmp.loc[tmp["ano"] == y1, "valor_final"].sum())
    total_y2 = float(tmp.loc[tmp["ano"] == y2, "valor_final"].sum())
    lines.append(f"TOTAL | {_format_brl(total_y1)} | {_format_brl(total_y2)} | {_safe_growth_percent(total_y1, total_y2)}")

    for uf, row in display_rows.iterrows():
        v1 = float(row[y1])
        v2 = float(row[y2])
        lines.append(f"{uf} | {_format_brl(v1)} | {_format_brl(v2)} | {_safe_growth_percent(v1, v2)}")

    return "\n".join(lines)


def _build_cliente_pagador_table(
    totals_df: pd.DataFrame,
    filial: str,
    target_year: int | None = None,
) -> str:
    if totals_df.empty:
        return ""

    scoped_df = _build_filial_scope_df(totals_df, filial)
    if scoped_df.empty:
        return ""

    date_col = _find_column(scoped_df, ["Data de Emissao", "data de emissao"])
    cnpj_pagador_col = _find_column(
        scoped_df,
        ["CNPJ Pagador", "cnpj pagador", "CNPJ do Pagador", "cnpj do pagador"],
    )
    cliente_pagador_col = _find_column(
        scoped_df,
        ["Cliente Pagador", "cliente pagador", "Nome do Cliente Pagador", "nome do cliente pagador"],
    )
    vendedor_col = _find_column(
        scoped_df,
        [
            "Login", "login",
            "Login do Usuario", "login do usuario",
            "Login do Vendedor", "login do vendedor",
            "Vendedor", "vendedor",
            "Nome do Vendedor", "nome do vendedor",
            "Cod. Vendedor", "cod. vendedor",
            "Codigo do Vendedor", "codigo do vendedor",
        ],
    )

    quant_col = _find_column(
        scoped_df,
        [
            "Quantidade de Volumes", "quantidade de volumes",
            "Quantidade", "quantidade", "Qtd", "qtd", "Quant", "quant",
        ],
    )
    peso_col = _find_column(
        scoped_df,
        [
            "Peso Calc", "peso calc", "Peso Calculado", "peso calculado",
            "Peso Real em Kg", "peso real em kg", "Peso", "peso",
        ],
    )
    valmerc_col = _find_column(
        scoped_df,
        [
            "ValMerc", "valmerc", "Valor da Mercadoria", "valor da mercadoria",
            "Valor Mercadoria", "valor mercadoria",
        ],
    )

    if not date_col or not cnpj_pagador_col:
        return ""

    tmp = scoped_df.copy()
    tmp["valor_final"] = _compute_valor_frete_final(tmp)
    tmp["dt"] = _extract_datetime_series(tmp, date_col)
    tmp["ano"] = tmp["dt"].dt.year
    tmp["periodo"] = tmp["dt"].dt.to_period("M")
    tmp["cnpj_key"] = (
        tmp[cnpj_pagador_col]
        .astype(str)
        .str.replace(r"\D", "", regex=True)
        .str.strip()
    )
    tmp["cliente_nome"] = (
        tmp[cliente_pagador_col].astype(str).str.strip()
        if cliente_pagador_col
        else ""
    )
    tmp["vendedor_nome"] = (
        tmp[vendedor_col].astype(str).str.strip()
        if vendedor_col
        else ""
    )
    tmp["quant"] = _parse_br_numeric(tmp[quant_col]) if quant_col else 0.0
    tmp["peso"] = _parse_br_numeric(tmp[peso_col]) if peso_col else 0.0
    tmp["valmerc"] = _parse_br_numeric(tmp[valmerc_col]) if valmerc_col else 0.0

    tmp = tmp.dropna(subset=["valor_final", "ano"])
    tmp = tmp[(tmp["cnpj_key"] != "") & (tmp["cnpj_key"] != "0")]
    if tmp.empty:
        return ""

    months_sorted = sorted(tmp["periodo"].dropna().unique().tolist())
    if not months_sorted:
        return ""
    if target_year is not None:
        months_yr = [m for m in months_sorted if m.year == target_year]
        if not months_yr:
            return ""
        months_selected = months_yr[-3:]
    else:
        months_selected = months_sorted[-3:]
    months_desc = list(reversed(months_selected))

    logging.info(
        "Tabela Cliente Pagador | filial=%s | meses selecionados=%s",
        filial,
        [f"{p.year}-{p.month:02d}" for p in months_desc],
    )

    tmp = tmp[tmp["periodo"].isin(months_selected)].copy()
    if tmp.empty:
        return ""

    agg = (
        tmp.groupby(["cnpj_key", "periodo"], as_index=False)[["quant", "peso", "valmerc", "valor_final"]]
        .sum()
    )

    nome_por_cnpj = {}
    vendedor_por_cnpj = {}
    if cliente_pagador_col:
        nome_df = tmp[tmp["cliente_nome"] != ""].copy()
        if not nome_df.empty:
            for cnpj, group in nome_df.groupby("cnpj_key"):
                mode_series = group["cliente_nome"].mode()
                nome_por_cnpj[cnpj] = mode_series.iloc[0] if not mode_series.empty else group["cliente_nome"].iloc[0]

    if vendedor_col:
        vendedor_df = tmp[tmp["vendedor_nome"] != ""].copy()
        if not vendedor_df.empty:
            for cnpj, group in vendedor_df.groupby("cnpj_key"):
                mode_series = group["vendedor_nome"].mode()
                vendedor_por_cnpj[cnpj] = mode_series.iloc[0] if not mode_series.empty else group["vendedor_nome"].iloc[0]

    latest_month = months_desc[0]
    latest_scores = (
        agg[agg["periodo"] == latest_month][["cnpj_key", "valor_final"]]
        .set_index("cnpj_key")["valor_final"]
    )
    client_order = latest_scores.sort_values(ascending=False).index.tolist()
    if not client_order:
        client_order = sorted(tmp["cnpj_key"].unique().tolist())

    max_clientes = 10
    display_clients = client_order[:max_clientes]
    has_outros = len(client_order) > max_clientes

    def _month_metrics(frame: pd.DataFrame, month_period) -> tuple[float, float, float, float]:
        month_data = frame[frame["periodo"] == month_period]
        if month_data.empty:
            return 0.0, 0.0, 0.0, 0.0
        return (
            float(month_data["quant"].sum()),
            float(month_data["peso"].sum()),
            float(month_data["valmerc"].sum()),
            float(month_data["valor_final"].sum()),
        )

    def _fmt_num(value: float) -> str:
        return _format_number_ptbr(value)

    lines = []
    lines.append("Tabela de Valores por Cliente Pagador (Frete Final)")
    month_header_cells = ["FILIAL", "CLIENTE", "VENDEDOR"]
    metric_header_cells = ["", "", ""]
    for idx, period in enumerate(months_desc):
        month_title = _month_name_pt(period.month).upper()
        month_header_cells.extend([month_title, "", "", ""])
        metric_header_cells.extend(["QUANT", "PESO CALC", "VALMERC", "FRETE TOTAL"])
        if idx < len(months_desc) - 1:
            month_header_cells.append("")
            metric_header_cells.append("CRES")
    lines.append(" | ".join(month_header_cells))
    lines.append(" | ".join(metric_header_cells))

    # Linha TOTAL
    rebuilt_total_cells = [str(filial).upper(), "TOTAL", ""]
    for idx, period in enumerate(months_desc):
        q, p, vm, ft = _month_metrics(tmp, period)
        rebuilt_total_cells.extend([_fmt_num(q), _fmt_num(p), _format_brl(vm), _format_brl(ft)])
        if idx < len(months_desc) - 1:
            _, _, _, base_ft = _month_metrics(tmp, months_desc[idx + 1])
            rebuilt_total_cells.append(_safe_growth_percent(base_ft, ft))
    lines.append(" | ".join(rebuilt_total_cells))

    # Linhas por cliente pagador
    for cnpj in display_clients:
        client_frame = agg[agg["cnpj_key"] == cnpj]
        label = nome_por_cnpj.get(cnpj, cnpj)
        vendedor_label = vendedor_por_cnpj.get(cnpj, "")
        row_cells = [str(filial).upper(), label, vendedor_label]

        for idx, period in enumerate(months_desc):
            q, p, vm, ft = _month_metrics(client_frame, period)
            row_cells.extend([_fmt_num(q), _fmt_num(p), _format_brl(vm), _format_brl(ft)])
            if idx < len(months_desc) - 1:
                _, _, _, base_ft = _month_metrics(client_frame, months_desc[idx + 1])
                row_cells.append(_safe_growth_percent(base_ft, ft))

        lines.append(" | ".join(row_cells))

    if has_outros:
        outros_frame = agg[~agg["cnpj_key"].isin(display_clients)]
        row_cells = [str(filial).upper(), "OUTROS", ""]
        for idx, period in enumerate(months_desc):
            q, p, vm, ft = _month_metrics(outros_frame, period)
            row_cells.extend([_fmt_num(q), _fmt_num(p), _format_brl(vm), _format_brl(ft)])
            if idx < len(months_desc) - 1:
                _, _, _, base_ft = _month_metrics(outros_frame, months_desc[idx + 1])
                row_cells.append(_safe_growth_percent(base_ft, ft))
        lines.append(" | ".join(row_cells))

    return "\n".join(lines)


def _find_last_movement_date_column(df: pd.DataFrame) -> str | None:
    preferred_candidates = [
        "Data da Ultima Ocorrencia",
        "Data da Ultima Movimentacao",
        "Data do Ultimo Movimento",
        "Data da Ultima Interacao",
        "Data da Ultima Compra",
        "Data da Ultima Venda",
        "Data da Ultima Atualizacao",
        "Data de Inclusao da Ultima Ocorrencia",
    ]
    preferred = _find_column(df, preferred_candidates)
    if preferred:
        return preferred

    best_col = None
    best_score = -1
    for col in df.columns:
        norm = _normalize_header_name(col)
        if "data" not in norm:
            continue
        if "ultima" not in norm and "ultimo" not in norm:
            continue

        score = 1
        if "ocorrencia" in norm:
            score += 4
        if "movimento" in norm or "movimentacao" in norm:
            score += 3
        if "inclusao" in norm:
            score += 1
        if "usuario" in norm:
            score += 1

        if score > best_score:
            best_score = score
            best_col = col

    return best_col


def _build_usuarios_afastados_table(totals_df: pd.DataFrame, filial: str) -> str:
    if totals_df.empty:
        return ""

    unidade_emissora_col = _find_column(totals_df, ["Unidade Emissora", "unidade emissora", "unidade emissora ", "unidade"])
    if not unidade_emissora_col:
        return ""

    filial_norm = str(filial).strip().casefold()
    scoped_df = totals_df[
        totals_df[unidade_emissora_col].astype(str).str.strip().str.casefold() == filial_norm
    ].copy()
    if scoped_df.empty:
        return ""

    last_movement_col = _find_last_movement_date_column(scoped_df)
    if not last_movement_col:
        logging.info("Tabela de afastados: nenhuma coluna de data de ultimo movimento identificada para filial %s.", filial)
        return ""

    cliente_col = _find_column(
        scoped_df,
        [
            "Cliente Pagador", "cliente pagador",
            "Nome do Cliente Pagador", "nome do cliente pagador",
            "Cliente", "cliente",
            "Nome do Cliente", "nome do cliente",
            "Razao Social", "razao social",
            "Nome Fantasia", "nome fantasia",
        ],
    )
    cnpj_cpf_col = _find_column(
        scoped_df,
        [
            "CNPJ Pagador", "cnpj pagador",
            "CNPJ do Pagador", "cnpj do pagador",
            "CNPJ/CPF", "cnpj cpf",
            "CNPJ", "cnpj",
            "CPF", "cpf",
        ],
    )
    vendedor_col = _find_column(
        scoped_df,
        [
            "Login", "login",
            "Login do Usuario", "login do usuario",
            "Login do Vendedor", "login do vendedor",
            "Vendedor", "vendedor",
            "Nome do Vendedor", "nome do vendedor",
        ],
    )
    endereco_col = _find_column(
        scoped_df,
        [
            "Endereco do Pagador", "endereco do pagador",
            "Endereco Pagador", "endereco pagador",
            "Endereco do Cliente Pagador", "endereco do cliente pagador",
            "Endereco", "endereco",
            "Logradouro", "logradouro",
            "Endereco do Cliente", "endereco do cliente",
        ],
    )
    cep_col = _find_column(
        scoped_df,
        [
            "CEP do Remetente", "cep do remetente",
            "CEP do Pagador", "cep do pagador",
            "CEP cliente remetente", "cep cliente remetente",
            "CEP cliente", "cep cliente",
            "CEP do Cliente Pagador", "cep do cliente pagador",
            "CEP", "cep",
        ],
    )
    fone_col = _find_column(
        scoped_df,
        [
            "Fone do Pagador", "fone do pagador",
            "Telefone do Pagador", "telefone do pagador",
            "Telefone do Cliente Pagador", "telefone do cliente pagador",
            "Fone cliente remetente", "fone cliente remetente",
            "Telefone cliente remetente", "telefone cliente remetente",
            "Telefone cliente", "telefone cliente",
            "Fone", "fone",
            "Telefone", "telefone",
            "Celular", "celular",
        ],
    )
    cidade_col = _find_column(
        scoped_df,
        [
            "Cidade do Pagador", "cidade do pagador",
            "Cidade", "cidade",
            "Cidade do Remetente", "cidade do remetente",
            "Cidade do Destinatario", "cidade do destinatario",
            "Municipio", "municipio",
        ],
    )
    uf_col = _find_column(scoped_df, ["UF do Pagador", "uf do pagador", "UF", "uf", "UF Destinatario", "UF Remetente", "Estado", "estado"])
    ie_col = _find_column(
        scoped_df,
        [
            "IE cliente remetente", "ie cliente remetente",
            "IE do Pagador", "ie do pagador",
            "IE", "ie",
            "Inscricao Estadual", "inscricao estadual",
            "Inscricao", "inscricao",
        ],
    )

    tmp = scoped_df.copy()
    tmp["ultimo_movimento_dt"] = pd.to_datetime(tmp[last_movement_col], dayfirst=True, errors="coerce")
    if tmp["ultimo_movimento_dt"].isna().all():
        # Fallback para casos com formato alternativo ou com timezone/hora inconsistente.
        tmp["ultimo_movimento_dt"] = pd.to_datetime(tmp[last_movement_col], errors="coerce")
    tmp = tmp.dropna(subset=["ultimo_movimento_dt"])
    if tmp.empty:
        return ""

    if cnpj_cpf_col:
        tmp["entidade_key"] = (
            tmp[cnpj_cpf_col]
            .astype(str)
            .str.replace(r"\D", "", regex=True)
            .str.strip()
        )
    else:
        tmp["entidade_key"] = ""

    if cliente_col:
        cliente_nome_series = tmp[cliente_col].astype(str).str.strip()
    else:
        cliente_nome_series = pd.Series("", index=tmp.index, dtype="object")
    fallback_key = cliente_nome_series.str.casefold().replace("", pd.NA)
    tmp["entidade_key"] = tmp["entidade_key"].where(tmp["entidade_key"] != "", fallback_key)
    tmp = tmp.dropna(subset=["entidade_key"])
    if tmp.empty:
        return ""

    idx_latest = tmp.groupby("entidade_key")["ultimo_movimento_dt"].idxmax()
    latest_rows = tmp.loc[idx_latest].copy()

    today = pd.Timestamp.now().normalize()
    latest_rows["dias_sem_mov"] = (today - latest_rows["ultimo_movimento_dt"]).dt.days
    afastados = latest_rows[latest_rows["dias_sem_mov"] > 30].copy()
    if afastados.empty:
        return ""

    afastados = afastados.sort_values(by=["dias_sem_mov", "ultimo_movimento_dt"], ascending=[False, True])

    def _safe_text(series_col: str | None, frame: pd.DataFrame, default: str = "") -> pd.Series:
        if not series_col:
            return pd.Series(default, index=frame.index, dtype="object")
        raw = frame[series_col]
        cleaned = raw.where(raw.notna(), default).astype(str).str.strip()
        return cleaned.replace({"nan": default, "None": default})

    def _truncate_text(value: str, max_len: int) -> str:
        text = str(value).strip()
        if len(text) <= max_len:
            return text
        return text[: max(1, max_len - 3)].rstrip() + "..."

    cliente_s = _safe_text(cliente_col, afastados)
    cnpj_s = _safe_text(cnpj_cpf_col, afastados)
    vendedor_s = _safe_text(vendedor_col, afastados)
    endereco_s = _safe_text(endereco_col, afastados)
    cep_s = _safe_text(cep_col, afastados)
    fone_s = _safe_text(fone_col, afastados)
    cidade_s = _safe_text(cidade_col, afastados)
    uf_s = _safe_text(uf_col, afastados).str.upper()
    ie_s = _safe_text(ie_col, afastados)

    max_rows = 30
    if len(afastados) > max_rows:
        afastados = afastados.head(max_rows)
        cliente_s = cliente_s.loc[afastados.index]
        cnpj_s = cnpj_s.loc[afastados.index]
        vendedor_s = vendedor_s.loc[afastados.index]
        endereco_s = endereco_s.loc[afastados.index]
        cep_s = cep_s.loc[afastados.index]
        fone_s = fone_s.loc[afastados.index]
        cidade_s = cidade_s.loc[afastados.index]
        uf_s = uf_s.loc[afastados.index]
        ie_s = ie_s.loc[afastados.index]

    lines = []
    lines.append("Tabela de Clientes sem contato (+30 dias)")
    lines.append("CLIENTE | CNPJ/CPF | VENDEDOR | ENDERECO | CEP | FONE | CIDADE | UF | FIL | ULTIMO MOVIMENTO | IE")

    for idx in afastados.index:
        ultimo_mov = afastados.at[idx, "ultimo_movimento_dt"]
        ultimo_mov_fmt = ultimo_mov.strftime("%d/%m/%Y") if pd.notna(ultimo_mov) else ""
        row_cells = [
            _truncate_text(cliente_s.at[idx], 32),
            _truncate_text(cnpj_s.at[idx], 18),
            _truncate_text(vendedor_s.at[idx], 10),
            _truncate_text(endereco_s.at[idx], 34),
            _truncate_text(cep_s.at[idx], 9),
            _truncate_text(fone_s.at[idx], 14),
            _truncate_text(cidade_s.at[idx], 18),
            uf_s.at[idx],
            str(filial).upper(),
            ultimo_mov_fmt,
            _truncate_text(ie_s.at[idx], 16),
        ]
        lines.append(" | ".join(row_cells))

    logging.info(
        "Tabela de afastados gerada para filial=%s usando coluna de data='%s' com %s linhas.",
        filial,
        last_movement_col,
        len(afastados),
    )
    return "\n".join(lines)


def _extract_frete_tables_for_pdf(
    insight_text: str,
) -> tuple[list[list[str]], list[list[str]], list[list[str]], list[list[str]], list[list[str]], list[list[str]], list[list[str]], list[str]]:
    summary_table: list[list[str]] = []
    detail_table: list[list[str]] = []
    expedidos_table: list[list[str]] = []
    recebidos_table: list[list[str]] = []
    uf_table: list[list[str]] = []
    clientes_table: list[list[str]] = []
    afastados_table: list[list[str]] = []
    metric_lines: list[str] = []

    section = None
    for raw_line in insight_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        if line.startswith("Tabela de Valores Expedidos"):
            section = "expedidos"
            continue

        if line.startswith("Tabela de Valores Recebidos"):
            section = "recebidos"
            continue

        if line.startswith("Tabela de Valores por UF"):
            section = "uf"
            continue

        if line.startswith("Tabela de Valores por Cliente Pagador"):
            section = "clientes"
            continue

        if line.startswith("Tabela de Usuarios Afastados") or line.startswith("Tabela de Clientes sem contato"):
            section = "afastados"
            continue

        if line.startswith("Linha |") and section in {"expedidos", "recebidos", "uf", "clientes", "afastados"}:
            row = [cell.strip() for cell in line.split("|")]
            if section == "expedidos":
                expedidos_table.append(row)
            elif section == "recebidos":
                recebidos_table.append(row)
            elif section == "clientes":
                clientes_table.append(row)
            elif section == "afastados":
                afastados_table.append(row)
            else:
                uf_table.append(row)
            continue

        if line.startswith("CLIENTE |") and section == "afastados":
            afastados_table.append([cell.strip() for cell in line.split("|")])
            continue

        if line.startswith("Linha |"):
            section = "summary"
            summary_table.append([cell.strip() for cell in line.split("|")])
            continue

        if line.startswith("Codigo |"):
            section = "detail"
            detail_table.append([cell.strip() for cell in line.split("|")])
            continue

        if line.startswith("Principais metricas"):
            section = "metrics"
            continue

        if section in {"summary", "detail", "expedidos", "recebidos", "uf", "clientes", "afastados"} and "|" in line:
            row = [cell.strip() for cell in line.split("|")]
            if section == "summary":
                summary_table.append(row)
            elif section == "detail":
                detail_table.append(row)
            elif section == "expedidos":
                expedidos_table.append(row)
            elif section == "recebidos":
                recebidos_table.append(row)
            elif section == "clientes":
                clientes_table.append(row)
            elif section == "afastados":
                afastados_table.append(row)
            else:
                uf_table.append(row)
            continue

        if section == "metrics" and line.startswith("-"):
            metric_lines.append(line)

    return summary_table, detail_table, expedidos_table, recebidos_table, uf_table, clientes_table, afastados_table, metric_lines


def _draw_table_on_canvas(pdf: canvas.Canvas, title: str, table_data: list[list[str]], y_start: float) -> float:
    if not table_data:
        return y_start

    pdf.setFont("Helvetica-Bold", 10)
    pdf.drawString(50, y_start - 4, title)

    page_width, _ = pdf._pagesize
    usable_width = max(float(page_width) - 90.0, 360.0)

    col_count = len(table_data[0])
    if col_count == 6:
        col_widths = [90, 60, 105, 60, 105, 80]
        font_size = 8
    elif col_count == 4:
        col_widths = [120, 130, 130, 120]
        font_size = 8
    elif col_count == 3:
        col_widths = [180, 120, 200]
        font_size = 8
    elif col_count == 12:
        # Tabela mensal 2 meses: Filial, Cliente, Vendedor + 2 blocos
        # bloco atual tem CRES (5 cols), bloco base sem CRES (4 cols) → total 12 cols
        base_widths_12 = [18, 110, 36, 26, 36, 52, 46, 20, 26, 36, 52, 46]
        # soma = 504; escala pelo usable_width
        scale_12 = min(1.0, usable_width / float(sum(base_widths_12)))
        col_widths = [w * scale_12 for w in base_widths_12]
        font_size = 6.5 if scale_12 >= 0.95 else 6.0
    elif col_count == 11:
        # Layout da tabela de usuarios afastados (referencia cliente): melhor leitura em landscape.
        base_widths_11 = [120, 70, 50, 150, 48, 58, 78, 24, 24, 70, 56]
        scale_11 = min(1.0, usable_width / float(sum(base_widths_11)))
        col_widths = [w * scale_11 for w in base_widths_11]
        font_size = 6.3 if scale_11 >= 0.9 else 6.0
    elif col_count >= 13:
        # Tabelas mensais mais largas (ex.: Cliente Pagador 3 meses)
        if col_count == 17:
            # Calibrado para landscape letter (usable ~702pt).
            # Filial=18, Cliente=112, Vendedor=38; por bloco: Q=26, Peso=36, VM=54, Frete=48, Cres=18
            # bloco c/ CRES = 182; bloco s/ CRES = 164
            # total base = 18+112+38 + 182+182+164 = 696pt
            base_widths_17 = [18, 112, 38, 26, 36, 54, 48, 18, 26, 36, 54, 48, 18, 26, 36, 54, 48]
            scale_17 = min(1.0, usable_width / float(sum(base_widths_17)))
            col_widths = [w * scale_17 for w in base_widths_17]
            font_size = 6.5 if scale_17 >= 0.90 else 6.0
        elif col_count == 16:
            # Layout fixo mais compacto para 3 meses sem vendedor.
            base_widths_16 = [18, 120, 24, 34, 52, 46, 16, 24, 34, 52, 46, 16, 24, 34, 52, 46]
            scale_16 = min(1.0, usable_width / float(sum(base_widths_16)))
            col_widths = [w * scale_16 for w in base_widths_16]
            font_size = 6.5 if scale_16 >= 0.90 else 6.0
        else:
            base_col_widths = [30, 82]
            month_triplet = [22, 24, 30, 34, 20]
            month_last = [22, 24, 30, 34]

            remaining = col_count - 2
            dynamic_widths = []
            while remaining > 0:
                if remaining >= 5:
                    dynamic_widths.extend(month_triplet)
                    remaining -= 5
                else:
                    dynamic_widths.extend(month_last[:remaining])
                    remaining = 0

            col_widths = base_col_widths + dynamic_widths

        font_size = 5.0
    else:
        col_widths = [500 / max(col_count, 1)] * col_count
        font_size = 8

    def _truncate_to_width(text: str, max_width_pt: float, font_name: str, size: float) -> str:
        normalized = str(text).strip()
        if not normalized:
            return ""
        if stringWidth(normalized, font_name, size) <= max_width_pt:
            return normalized

        ellipsis = "..."
        ellipsis_w = stringWidth(ellipsis, font_name, size)
        if ellipsis_w >= max_width_pt:
            return ellipsis

        kept = normalized
        target_width = max_width_pt - ellipsis_w
        while kept and stringWidth(kept, font_name, size) > target_width:
            kept = kept[:-1]
        return (kept.rstrip() + ellipsis) if kept else ellipsis

    if col_count == 11:
        # Evita atropelo na tabela de clientes sem contato usando truncamento por largura real da celula.
        normalized_rows: list[list[str]] = []
        for row_idx, row in enumerate(table_data):
            current = []
            for col_idx, cell in enumerate(row):
                cell_text = str(cell).strip()
                if row_idx == 0:
                    current.append(cell_text)
                    continue

                # Reserva pequena margem para padding e grade da tabela.
                available_width = max(float(col_widths[col_idx]) - 4.0, 6.0)
                if col_idx in {7, 8, 9}:  # UF, FIL e data costumam caber naturalmente.
                    current.append(cell_text)
                else:
                    current.append(_truncate_to_width(cell_text, available_width, "Helvetica", float(font_size)))
            normalized_rows.append(current)
        table_data = normalized_rows

    table = Table(table_data, colWidths=col_widths)
    style_commands = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0B2C6B")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), font_size),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
        ("BACKGROUND", (0, 1), (-1, -1), colors.whitesmoke),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ("TOPPADDING", (0, 0), (-1, -1), 1),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
    ]

    is_cliente_mensal = (
        col_count >= 12
        and len(table_data) >= 2
        and any(str(cell).strip().upper() == "QUANT" for cell in table_data[1][:6])
    )

    if is_cliente_mensal:
        style_commands.append(("BACKGROUND", (0, 0), (-1, 1), colors.HexColor("#0B2C6B")))
        style_commands.append(("TEXTCOLOR", (0, 0), (-1, 1), colors.white))
        style_commands.append(("FONTNAME", (0, 0), (-1, 1), "Helvetica-Bold"))
        style_commands.append(("BACKGROUND", (0, 2), (-1, -1), colors.whitesmoke))

        style_commands.append(("SPAN", (0, 0), (0, 1)))
        style_commands.append(("SPAN", (1, 0), (1, 1)))
        style_commands.append(("SPAN", (2, 0), (2, 1)))

        if col_count == 17:
            block_starts = [3, 8, 13]
        elif col_count == 12:
            block_starts = [3, 8]
        elif col_count == 16:
            block_starts = [2, 7, 12]
        else:
            block_starts = [2]
            if col_count >= 7:
                block_starts.append(7)
            if col_count >= 12:
                block_starts.append(12)

        for start in block_starts:
            end = min(start + 4, col_count - 1)
            style_commands.append(("SPAN", (start, 0), (end, 0)))
            style_commands.append(("FONTNAME", (start, 1), (end, 1), "Helvetica-Bold"))
        style_commands.append(("LINEBELOW", (0, 1), (-1, 1), 0.75, colors.black))

    if col_count >= 12:
        data_start_row = 2 if is_cliente_mensal else 1
        left_end_col = 2 if col_count in {12, 17} else 1
        style_commands.append(("ALIGN", (0, data_start_row), (left_end_col, -1), "LEFT"))
        style_commands.append(("LEFTPADDING", (1, 0), (left_end_col, -1), 1))
        style_commands.append(("RIGHTPADDING", (0, 0), (-1, -1), 1))

        if is_cliente_mensal:
            if col_count == 12:
                numeric_cols = [3, 4, 5, 6, 8, 9, 10, 11]
                growth_cols = [7]
            elif col_count == 17:
                numeric_cols = [3, 4, 5, 6, 8, 9, 10, 11, 13, 14, 15, 16]
                growth_cols = [7, 12]
            else:
                numeric_cols = []
                growth_cols = []

            for col_idx in numeric_cols:
                style_commands.append(("ALIGN", (col_idx, data_start_row), (col_idx, -1), "RIGHT"))
            for col_idx in growth_cols:
                style_commands.append(("ALIGN", (col_idx, data_start_row), (col_idx, -1), "CENTER"))

    if col_count == 11:
        style_commands.append(("ALIGN", (0, 1), (6, -1), "LEFT"))
        style_commands.append(("ALIGN", (7, 1), (8, -1), "CENTER"))
        style_commands.append(("ALIGN", (9, 1), (9, -1), "CENTER"))
        style_commands.append(("ALIGN", (10, 1), (10, -1), "LEFT"))

    header_row_idx = 1 if is_cliente_mensal else 0
    growth_columns = {
        idx for idx, header in enumerate(table_data[header_row_idx]) if _is_growth_header(header)
    }
    first_data_row = 2 if is_cliente_mensal else 1
    for row_idx in range(first_data_row, len(table_data)):
        row = table_data[row_idx]
        for col_idx, cell in enumerate(row):
            if col_idx in growth_columns:
                style_commands.append(("FONTNAME", (col_idx, row_idx), (col_idx, row_idx), "Helvetica-Bold"))
            if col_idx in growth_columns and _is_negative_display_value(str(cell)):
                style_commands.append(("TEXTCOLOR", (col_idx, row_idx), (col_idx, row_idx), colors.red))

    table.setStyle(TableStyle(style_commands))

    width, height = table.wrapOn(pdf, usable_width, 700)

    # Para tabelas muito largas, reduz proporcionalmente para caber na pagina sem truncar.
    if width > usable_width:
        scale = usable_width / float(width)
        draw_y = y_start - 30 - (height * scale)

        pdf.saveState()
        pdf.translate(45, draw_y)
        pdf.scale(scale, scale)
        table.drawOn(pdf, 0, 0)
        pdf.restoreState()

        return y_start - 40 - (height * scale)

    table.drawOn(pdf, 45, y_start - 30 - height)
    return y_start - 40 - height


def _draw_summary_table_example_layout(
    pdf: canvas.Canvas,
    filial: str,
    summary_table: list[list[str]],
    y_start: float,
    bloco_titulo: str = "TOTAL",
    secao_titulo: str = "Resumo por Tipo do Frete",
) -> float:
    if len(summary_table) < 2:
        return y_start

    header = summary_table[0]
    y1 = header[1].split()[0] if len(header) > 1 else "Ano1"
    y2 = header[3].split()[0] if len(header) > 3 else "Ano2"

    table_data = [
        ["FILIAL", bloco_titulo, "", "", "", "DESEMPENHO"],
        ["", y1, "", y2, "", ""],
        ["", "Quantidade", "Valor", "Quantidade", "Valor", ""],
    ]

    ordered_labels = ["TOTAL", "CIF", "FOB"]
    rows_by_label: dict[str, list[str]] = {}
    for row in summary_table[1:]:
        if len(row) >= 6:
            label = str(row[0]).strip().upper()
            if label in ordered_labels and label not in rows_by_label:
                rows_by_label[label] = row

    for label in ordered_labels:
        row = rows_by_label.get(label)
        if not row:
            continue
        display_label = filial.upper() if label == "TOTAL" else label
        table_data.append([display_label, row[1], row[2], row[3], row[4], row[5]])

    pdf.setFont("Helvetica-Bold", 10)
    pdf.drawString(50, y_start - 4, secao_titulo)

    col_widths = [120, 70, 95, 70, 95, 90]
    table = Table(table_data, colWidths=col_widths)
    style_commands = [
        ("SPAN", (0, 0), (0, 2)),
        ("SPAN", (1, 0), (4, 0)),
        ("SPAN", (1, 1), (2, 1)),
        ("SPAN", (3, 1), (4, 1)),
        ("SPAN", (5, 0), (5, 2)),
        ("BACKGROUND", (0, 0), (-1, 2), colors.HexColor("#0B2C6B")),
        ("TEXTCOLOR", (0, 0), (-1, 2), colors.white),
        ("FONTNAME", (0, 0), (-1, 2), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
        ("BACKGROUND", (0, 3), (-1, -1), colors.whitesmoke),
        ("FONTNAME", (0, 3), (-1, -1), "Helvetica"),
    ]

    # No layout resumido, a coluna 5 representa Desempenho.
    for row_idx in range(3, len(table_data)):
        row = table_data[row_idx]
        if len(row) > 5 and _is_negative_display_value(str(row[5])):
            style_commands.append(("TEXTCOLOR", (5, row_idx), (5, row_idx), colors.red))

    table.setStyle(TableStyle(style_commands))

    width, height = table.wrapOn(pdf, 520, 700)
    table.drawOn(pdf, 45, y_start - 30 - height)
    return y_start - 40 - height


def _build_rule_based_insights(
    branch_df: pd.DataFrame,
    filial: str,
    totals_source_df: pd.DataFrame | None = None,
) -> str:
    if branch_df.empty and (totals_source_df is None or totals_source_df.empty):
        return f"Nao encontramos dados operacionais para a filial {filial} no CSV de insights."

    lines = [f"Filial {filial}: {len(branch_df)} registros analisados."]

    totals_df = totals_source_df if totals_source_df is not None and not totals_source_df.empty else branch_df
    scoped_df = _build_filial_scope_df(totals_df, filial)

    unidade_emissora_col = _find_column(totals_df, ["Unidade Emissora", "unidade emissora", "unidade emissora ", "unidade"])
    unidade_receptora_col = _find_column(totals_df, ["Unidade Receptora", "unidade receptora"])
    valor_frete_final = _compute_valor_frete_final(totals_df)

    expedidos_total = 0.0
    expedidos_media = 0.0
    recebidos_total = 0.0
    recebidos_media = 0.0

    if unidade_emissora_col:
        expedidos_mask = (
            totals_df[unidade_emissora_col].astype(str).str.strip().str.casefold()
            == str(filial).strip().casefold()
        )
        expedidos_vals = valor_frete_final[expedidos_mask].dropna()
        expedidos_total = float(expedidos_vals.sum())
        expedidos_media = float(expedidos_vals.mean()) if not expedidos_vals.empty else 0.0

    if unidade_receptora_col:
        recebidos_mask = (
            totals_df[unidade_receptora_col].astype(str).str.strip().str.casefold()
            == str(filial).strip().casefold()
        )
        recebidos_vals = valor_frete_final[recebidos_mask].dropna()
        recebidos_total = float(recebidos_vals.sum())
        recebidos_media = float(recebidos_vals.mean()) if not recebidos_vals.empty else 0.0

    frete_tables = _build_frete_tables(scoped_df)
    if frete_tables:
        lines.append("")
        lines.append(frete_tables)

    unidade_tables = _build_expedidos_recebidos_tables(totals_df, filial)
    if unidade_tables:
        lines.append("")
        lines.append(unidade_tables)

    uf_table = _build_uf_emphasis_table(totals_df, filial)
    if uf_table:
        lines.append("")
        lines.append(uf_table)

    clientes_table = _build_cliente_pagador_table(totals_df, filial)
    if clientes_table:
        lines.append("")
        lines.append(clientes_table)

    afastados_table = _build_usuarios_afastados_table(totals_df, filial)
    if afastados_table:
        lines.append("")
        lines.append(afastados_table)

    metric_source_df = scoped_df if not scoped_df.empty else branch_df
    numeric_cols = []
    for col in metric_source_df.columns:
        if not _is_metric_column(col):
            continue
        series = _parse_br_numeric(metric_source_df[col])
        if series.notna().sum() > 0:
            numeric_cols.append((col, series))

    if numeric_cols:
        preferred_lower = {name.lower() for name in _PREFERRED_METRIC_COLUMNS}
        preferred = [
            (col, series)
            for col, series in numeric_cols
            if str(col).strip().lower() in preferred_lower
        ]

        ranked = sorted(
            numeric_cols,
            key=lambda item: abs(item[1].sum(skipna=True)),
            reverse=True,
        )

        selected = preferred[:3] if len(preferred) >= 3 else ranked[:3]

        lines.append("Principais metricas do periodo:")
        lines.append(f"- Valor expedido final (Unidade Emissora): total={expedidos_total:.2f} | media={expedidos_media:.2f}")
        lines.append(f"- Valor recebido final (Unidade Receptora): total={recebidos_total:.2f} | media={recebidos_media:.2f}")
        for col, series in selected:
            total = float(series.sum(skipna=True))
            media = float(series.mean(skipna=True))
            lines.append(f"- {col}: total={total:.2f} | media={media:.2f}")
    else:
        lines.append("Principais metricas do periodo:")
        lines.append(f"- Valor expedido final (Unidade Emissora): total={expedidos_total:.2f} | media={expedidos_media:.2f}")
        lines.append(f"- Valor recebido final (Unidade Receptora): total={recebidos_total:.2f} | media={recebidos_media:.2f}")

    return "\n".join(lines)


def _refine_with_ai_if_configured(raw_insights: str, filial: str) -> str:
    endpoint = os.getenv("AOAI_ENDPOINT")
    deployment = os.getenv("AOAI_DEPLOYMENT")
    api_key = os.getenv("AOAI_API_KEY")
    api_version = os.getenv("AOAI_API_VERSION", "2024-10-21")

    if not endpoint or not deployment or not api_key:
        return raw_insights

    base_endpoint = endpoint.rstrip("/")
    url = (
        f"{base_endpoint}/openai/deployments/{deployment}/chat/completions"
        f"?api-version={api_version}"
    )

    payload = {
        "messages": [
            {
                "role": "system",
                "content": (
                    "Voce e um analista de operacoes logisticas. "
                    "Transforme dados tecnicos em insights curtos, claros e acionaveis."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Gere um resumo executivo para a filial {filial} em portugues. "
                    "Use de 3 a 5 bullets, sem inventar dados, com foco em acao.\n\n"
                    f"Dados base:\n{raw_insights}"
                ),
            },
        ],
        "max_tokens": 300,
        "temperature": 0.2,
    }

    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "api-key": api_key,
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
            usage = data.get("usage") or {}
            logging.info(
                "Uso Azure OpenAI | tipo=resumo_executivo | filial=%s | prompt_tokens=%s | completion_tokens=%s | total_tokens=%s",
                filial,
                usage.get("prompt_tokens"),
                usage.get("completion_tokens"),
                usage.get("total_tokens"),
            )
            choices = data.get("choices") or []
            if choices:
                content = choices[0].get("message", {}).get("content", "").strip()
                if content:
                    return content
    except urllib.error.HTTPError as exc:
        logging.error("Falha HTTP ao gerar insight com IA para filial %s: %s", filial, exc)
    except Exception as exc:
        logging.error("Falha ao gerar insight com IA para filial %s: %s", filial, exc)

    return raw_insights


def _build_insight_text(
    insights_df: pd.DataFrame,
    insights_unidade_col: str | None,
    filial: str,
) -> str:
    if insights_df.empty or not insights_unidade_col:
        return (
            "CSV de insights nao configurado ou sem coluna Unidade Emissora identificada. "
            "Defina INSIGHTS_SOURCE_FOLDER/INSIGHTS_SOURCE_FILENAME e inclua coluna Unidade Emissora para personalizacao."
        )

    # Regra oficial: filial do destinatario corresponde ao codigo da Unidade Emissora.
    branch_df = insights_df[
        insights_df[insights_unidade_col].astype(str).str.strip().str.casefold()
        == str(filial).strip().casefold()
    ]

    logging.info(
        "Filial %s mapeada por %s (%s linhas).",
        filial,
        insights_unidade_col,
        len(branch_df),
    )

    raw_insights = _build_rule_based_insights(branch_df, filial, totals_source_df=insights_df)
    return _refine_with_ai_if_configured(raw_insights, filial)


@app.function_name(name="process_csv")
@app.schedule(schedule="0 0 12 * * *", arg_name="mytimer", run_on_startup=False)
def process_csv(mytimer: func.TimerRequest) -> None:

    logging.info("Iniciando processamento por destinatario")

    try:
        # DATA LAKE
        account_name = os.environ["AZURE_STORAGE_ACCOUNT_NAME"]

        credential = DefaultAzureCredential()

        service_client = DataLakeServiceClient(
            account_url=f"https://{account_name}.dfs.core.windows.net",
            credential=credential,
        )

        file_system = service_client.get_file_system_client("raw")
        filiais_mapping = _load_filiais_mapping(service_client)

        df = _read_csv_from_datalake(file_system, RECIPIENTS_CSV_PATH, sep=",")
        allowed_units = {
            str(unit).strip().casefold()
            for unit in df.get("filial", pd.Series(dtype=str)).dropna().astype(str)
            if str(unit).strip()
        }

        insights_df = pd.DataFrame()
        insights_unidade_col = None
        insights_filial_col = None
        try:
            insights_df, insights_source_paths = _load_insights_from_datalake(
                file_system,
                INSIGHTS_SOURCE_FOLDER,
                INSIGHTS_SOURCE_FILENAME,
                allowed_units=allowed_units,
            )
            insights_unidade_col = _find_column(
                insights_df,
                ["Unidade Emissora", "unidade emissora", "unidade emissora ", "unidade"],
            )
            insights_filial_col = _find_column(
                insights_df,
                ["Cidade do Remetente", "cidade do remetente", "filial", "branch", "unidade", "loja"],
            )

            if not insights_unidade_col:
                raise ValueError("Coluna Unidade Emissora nao encontrada nos arquivos de insights.")

            logging.info(
                "CSVs de insights carregados (%s arquivos): %s registros. Coluna unidade emissora: %s | coluna cidade/fallback: %s",
                len(insights_source_paths),
                len(insights_df),
                insights_unidade_col,
                insights_filial_col,
            )
        except Exception as exc:
            logging.warning(
                "Nao foi possivel carregar CSVs de insights em %s (arquivo preferido=%s): %s",
                INSIGHTS_SOURCE_FOLDER,
                INSIGHTS_SOURCE_FILENAME or "auto",
                exc,
            )

        logging.info("Total destinatarios: %s", len(df))

        # EMAIL CLIENT
        connection_string = os.environ["ACS_CONNECTION_STRING"]
        email_client = EmailClient.from_connection_string(connection_string)

        # LOOP POR DESTINATARIO
        for _, row in df.iterrows():
            email = row["email"]
            filial = str(row["filial"]).strip()
            filial_display = filiais_mapping.get(filial.casefold(), filial)
            cpf = str(row["cpf"])

            # Mantem uma versao estruturada para o PDF (sem depender de refinamento por IA).
            if not insights_df.empty and insights_unidade_col:
                branch_df = insights_df[
                    insights_df[insights_unidade_col].astype(str).str.strip().str.casefold()
                    == filial.casefold()
                ]
            elif not insights_df.empty and insights_filial_col:
                branch_df = insights_df[
                    insights_df[insights_filial_col].astype(str).str.strip().str.casefold()
                    == filial.casefold()
                ]
                logging.warning(
                    "Usando fallback por cidade para filial %s por ausencia de Unidade Emissora.",
                    filial,
                )
            else:
                branch_df = pd.DataFrame()

            raw_insight_for_pdf = _build_rule_based_insights(
                branch_df,
                str(filial),
                totals_source_df=insights_df,
            )
            summary_table, detail_table, expedidos_table, recebidos_table, uf_table, clientes_table, afastados_table, metric_lines = _extract_frete_tables_for_pdf(raw_insight_for_pdf)

            # Tabela de Cliente Pagador do ano anterior (mesmo trimestre)
            prev_year = pd.Timestamp.now().year - 1
            clientes_prev_text = _build_cliente_pagador_table(
                insights_df if not insights_df.empty else pd.DataFrame(),
                filial,
                target_year=prev_year,
            )
            _, _, _, _, _, clientes_prev_table, _, _ = _extract_frete_tables_for_pdf(clientes_prev_text)

            senha_pdf = cpf[:3]

            logging.info(
                "Processando: %s | Filial sigla: %s | Filial exibicao: %s",
                email,
                filial,
                filial_display,
            )

            pdf_path = None
            try:
                # GERAR PDF
                with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
                    pdf_path = tmp_file.name

                c = canvas.Canvas(pdf_path, pagesize=letter)

                c.drawString(100, 770, "Relatorio Operacional - Cruzeiro")
                c.drawString(100, 750, f"Filial: {filial_display}")

                y = 700

                y = _draw_summary_table_example_layout(c, str(filial_display), summary_table, y)
                total_comment = _build_operational_comment(summary_table, str(filial_display), "total")
                if total_comment:
                    y -= 6
                    if y <= 120:
                        c.showPage()
                        y = 760
                    y = _draw_wrapped_text(c, total_comment, y, x=50, max_width=520)
                    y -= 8

                y -= 24
                y = _draw_table_on_canvas(c, "Detalhe CV/CP/FV/FP", detail_table, y)

                if expedidos_table:
                    if y <= 180:
                        c.showPage()
                        y = 760
                    y = _draw_summary_table_example_layout(
                        c,
                        str(filial_display),
                        expedidos_table,
                        y,
                        bloco_titulo="EXPEDIDOS",
                        secao_titulo="Valores Expedidos (Frete Final)",
                    )
                    exp_comment = _build_operational_comment(expedidos_table, str(filial_display), "expedidos")
                    if exp_comment:
                        y -= 6
                        if y <= 120:
                            c.showPage()
                            y = 760
                        y = _draw_wrapped_text(c, exp_comment, y, x=50, max_width=520)
                        y -= 8

                if recebidos_table:
                    if y <= 180:
                        c.showPage()
                        y = 760
                    y = _draw_summary_table_example_layout(
                        c,
                        str(filial_display),
                        recebidos_table,
                        y,
                        bloco_titulo="RECEBIDOS",
                        secao_titulo="Valores Recebidos (Frete Final)",
                    )
                    rec_comment = _build_operational_comment(recebidos_table, str(filial_display), "recebidos")
                    if rec_comment:
                        y -= 6
                        if y <= 120:
                            c.showPage()
                            y = 760
                        y = _draw_wrapped_text(c, rec_comment, y, x=50, max_width=520)
                        y -= 8

                if uf_table:
                    if y <= 180:
                        c.showPage()
                        y = 760
                    y = _draw_table_on_canvas(c, "Valores por UF (Frete Final)", uf_table, y)
                    uf_comment = _build_operational_comment(uf_table, str(filial_display), "fluxos para fora do estado")
                    if uf_comment:
                        y -= 6
                        if y <= 120:
                            c.showPage()
                            y = 760
                        y = _draw_wrapped_text(c, uf_comment, y, x=50, max_width=520)
                        y -= 8

                if clientes_table:
                    if CLIENTES_TABLE_LANDSCAPE:
                        has_afastados_landscape = bool(afastados_table and AFASTADOS_TABLE_LANDSCAPE)
                        c.showPage()
                        c.setPageSize(landscape(letter))
                        land_w, land_h = landscape(letter)
                        y_land = land_h - 40
                        cur_year = pd.Timestamp.now().year
                        y_land = _draw_table_on_canvas(
                            c,
                            f"Valores por Cliente Pagador (Frete Final) — {cur_year}",
                            clientes_table,
                            y_land,
                        )
                        if clientes_prev_table:
                            y_land -= 20
                            if y_land > 80:
                                _draw_table_on_canvas(
                                    c,
                                    f"Valores por Cliente Pagador (Frete Final) — {cur_year - 1}",
                                    clientes_prev_table,
                                    y_land,
                                )
                        if not has_afastados_landscape:
                            c.showPage()
                            c.setPageSize(letter)
                            y = 760
                    else:
                        if y <= 180:
                            c.showPage()
                            y = 760
                        y = _draw_table_on_canvas(c, "Valores por Cliente Pagador (Frete Final)", clientes_table, y)

                if afastados_table:
                    if AFASTADOS_TABLE_LANDSCAPE:
                        c.showPage()
                        c.setPageSize(landscape(letter))
                        _, land_h = landscape(letter)
                        y_land = land_h - 40
                        y_land = _draw_table_on_canvas(
                            c,
                            "Clientes sem contato (+30 dias)",
                            afastados_table,
                            y_land,
                        )
                        c.showPage()
                        c.setPageSize(letter)
                        y = 760
                    else:
                        if y <= 180:
                            c.showPage()
                            y = 760
                        y = _draw_table_on_canvas(c, "Clientes sem contato (+30 dias)", afastados_table, y)

                if metric_lines:
                    if y <= 140:
                        c.showPage()
                        y = 760

                    y -= 14
                    c.setFont("Helvetica-Bold", 11)
                    c.drawString(50, y, "Insights Complementares")
                    y -= 18

                    visible_metric_lines = metric_lines[:8]
                    for idx, line in enumerate(visible_metric_lines):
                        if y <= 120:
                            c.showPage()
                            y = 760

                        metric_type, metric_name, formatted_values = _format_metric_line_for_pdf(line)
                        if metric_type and metric_name:
                            c.setFont("Helvetica-Bold", 8.5)
                            c.drawString(55, y, metric_name)
                            y -= 11
                            c.setFont("Helvetica", 8)
                            c.drawString(65, y, formatted_values)
                            y -= 10
                        else:
                            c.setFont("Helvetica", 8)
                            c.drawString(55, y, line)
                            y -= 10

                        # Linha em branco entre um item e o proximo titulo/valor.
                        if idx < len(visible_metric_lines) - 1:
                            y -= 8

                c.save()

                # PROTEGER PDF
                reader = PdfReader(pdf_path)
                writer = PdfWriter()

                for page in reader.pages:
                    writer.add_page(page)

                writer.encrypt(senha_pdf)

                with open(pdf_path, "wb") as f:
                    writer.write(f)

                logging.info("PDF protegido (senha parcial CPF)")

                # ENVIAR EMAIL
                with open(pdf_path, "rb") as f:
                    pdf_bytes = f.read()

                message = {
                    "senderAddress": "DoNotReply@86c8d0f7-12e2-42d8-8573-fc2482fa34c7.azurecomm.net",
                    "recipients": {
                        "to": [{"address": email}],
                    },
                    "content": {
                        "subject": f"Relatorio Filial {filial}",
                        "plainText": (
                            "Seu relatorio esta em anexo. Utilize os 3 primeiros digitos do CPF para acesso.\n\n"
                            "Os insights e tabelas (CIF/FOB e detalhamento) estao apenas no PDF anexo."
                        ),
                    },
                    "attachments": [
                        {
                            "name": f"relatorio_{filial}.pdf",
                            "contentType": "application/pdf",
                            "contentInBase64": base64.b64encode(pdf_bytes).decode(),
                        }
                    ],
                }

                _send_email_with_retry(email_client, message, email)

                logging.info("Email enviado para %s", email)
                time.sleep(INTER_EMAIL_DELAY_SECONDS)

            except HttpResponseError as e:
                raise
            finally:
                if pdf_path and os.path.exists(pdf_path):
                    os.remove(pdf_path)

        logging.info("PROCESSAMENTO FINALIZADO PARA TODOS OS DESTINATARIOS")

    except Exception as e:
        logging.error("ERRO: %s", str(e))
