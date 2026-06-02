import logging
import azure.functions as func
import os
import base64
import time
import json
import urllib.request
import urllib.error
import unicodedata

from azure.identity import DefaultAzureCredential
from azure.storage.filedatalake import DataLakeServiceClient

from io import BytesIO
import pandas as pd

from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.pdfgen import canvas
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

_INSIGHTS_REQUIRED_COLUMNS = [
    "Unidade Emissora", "unidade emissora", "unidade emissora ", "unidade",
    "Unidade Receptora", "unidade receptora",
    "UF Destinatario", "UF do Destinatario", "UF destino", "UF de destino",
    "UF Remetente", "UF do Remetente", "UF Origem", "UF de origem",
    "UF Receptora", "UF da Unidade Receptora", "UF Recebedora",
    "Cidade do Remetente", "cidade do remetente",
    "Tipo do Frete", "tipo do frete",
    "Tipo de Baixa", "tipo de baixa",
    "Data de Emissao", "data de emissao",
    "Valor do Frete", "valor do frete",
    "Valor Liquidado", "valor liquidado",
    "Tipo de Movimentacao", "tipo de movimentacao", "tipo movimentacao",
    "Direcao", "direcao", "Entrada/Saida", "entrada saida",
    "Recebido/Expedido", "recebido expedido",
    "Status Operacao", "status operacao",
]


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
                unidade_col = _find_column(
                    source_df,
                    ["Unidade Emissora", "unidade emissora", "unidade emissora ", "unidade"],
                )
                if unidade_col:
                    before_count = len(source_df)
                    source_df = source_df[
                        source_df[unidade_col].astype(str).str.strip().str.casefold().isin(allowed_units)
                    ].copy()
                    logging.info(
                        "Filtro por unidades em %s: %s -> %s linhas.",
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


def _safe_growth_percent(old_value: float, new_value: float) -> str:
    if old_value == 0:
        return "-"
    return f"{((new_value / old_value) - 1) * 100:.0f}%"


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
    bloco_txt = bloco_nome.lower()

    if growth > 0:
        return (
            f"No consolidado de {bloco_txt}, a filial {filial.upper()} apresentou crescimento de {desempenho}, "
            f"com evolucao de {valor_ano1} para {valor_ano2} no periodo analisado."
        )
    if growth < 0:
        return (
            f"No consolidado de {bloco_txt}, a filial {filial.upper()} registrou uma acomodacao de {abs(growth):.0f}%, "
            f"com variacao de {valor_ano1} para {valor_ano2}, indicando oportunidade de acompanhamento operacional."
        )
    return (
        f"No consolidado de {bloco_txt}, a filial {filial.upper()} manteve estabilidade no periodo, "
        f"com resultado de {valor_ano1} para {valor_ano2}."
    )


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


def _extract_frete_tables_for_pdf(
    insight_text: str,
) -> tuple[list[list[str]], list[list[str]], list[list[str]], list[list[str]], list[list[str]], list[str]]:
    summary_table: list[list[str]] = []
    detail_table: list[list[str]] = []
    expedidos_table: list[list[str]] = []
    recebidos_table: list[list[str]] = []
    uf_table: list[list[str]] = []
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

        if line.startswith("Linha |") and section in {"expedidos", "recebidos", "uf"}:
            row = [cell.strip() for cell in line.split("|")]
            if section == "expedidos":
                expedidos_table.append(row)
            elif section == "recebidos":
                recebidos_table.append(row)
            else:
                uf_table.append(row)
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

        if section in {"summary", "detail", "expedidos", "recebidos", "uf"} and "|" in line:
            row = [cell.strip() for cell in line.split("|")]
            if section == "summary":
                summary_table.append(row)
            elif section == "detail":
                detail_table.append(row)
            elif section == "expedidos":
                expedidos_table.append(row)
            elif section == "recebidos":
                recebidos_table.append(row)
            else:
                uf_table.append(row)
            continue

        if section == "metrics" and line.startswith("-"):
            metric_lines.append(line)

    return summary_table, detail_table, expedidos_table, recebidos_table, uf_table, metric_lines


def _draw_table_on_canvas(pdf: canvas.Canvas, title: str, table_data: list[list[str]], y_start: float) -> float:
    if not table_data:
        return y_start

    pdf.setFont("Helvetica-Bold", 10)
    pdf.drawString(50, y_start - 4, title)

    col_count = len(table_data[0])
    if col_count == 6:
        col_widths = [90, 60, 105, 60, 105, 80]
    elif col_count == 4:
        col_widths = [120, 130, 130, 120]
    elif col_count == 3:
        col_widths = [180, 120, 200]
    else:
        col_widths = [500 / max(col_count, 1)] * col_count

    table = Table(table_data, colWidths=col_widths)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0B2C6B")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
                ("BACKGROUND", (0, 1), (-1, -1), colors.whitesmoke),
                ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
            ]
        )
    )

    width, height = table.wrapOn(pdf, 520, 700)
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
    table.setStyle(
        TableStyle(
            [
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
        )
    )

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
            summary_table, detail_table, expedidos_table, recebidos_table, uf_table, metric_lines = _extract_frete_tables_for_pdf(raw_insight_for_pdf)

            senha_pdf = cpf[:3]

            logging.info("Processando: %s | Filial: %s", email, filial)

            pdf_path = None
            try:
                # GERAR PDF
                with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
                    pdf_path = tmp_file.name

                c = canvas.Canvas(pdf_path, pagesize=letter)

                c.drawString(100, 770, "Relatorio Operacional - Cruzeiro")
                c.drawString(100, 750, f"Filial: {filial}")

                y = 700

                total_comment = _build_soft_operational_comment(summary_table, str(filial), "total")
                if total_comment:
                    if y <= 140:
                        c.showPage()
                        y = 760
                    y = _draw_wrapped_text(c, total_comment, y, x=50, max_width=520)
                    y -= 8

                y = _draw_summary_table_example_layout(c, str(filial), summary_table, y)
                y -= 24
                y = _draw_table_on_canvas(c, "Detalhe CV/CP/FV/FP", detail_table, y)

                if expedidos_table:
                    if y <= 180:
                        c.showPage()
                        y = 760
                    y -= 18
                    exp_comment = _build_soft_operational_comment(expedidos_table, str(filial), "expedidos")
                    if exp_comment:
                        y = _draw_wrapped_text(c, exp_comment, y, x=50, max_width=520)
                        y -= 6
                    y = _draw_summary_table_example_layout(
                        c,
                        str(filial),
                        expedidos_table,
                        y,
                        bloco_titulo="EXPEDIDOS",
                        secao_titulo="Valores Expedidos (Frete Final)",
                    )

                if recebidos_table:
                    if y <= 180:
                        c.showPage()
                        y = 760
                    y -= 18
                    rec_comment = _build_soft_operational_comment(recebidos_table, str(filial), "recebidos")
                    if rec_comment:
                        y = _draw_wrapped_text(c, rec_comment, y, x=50, max_width=520)
                        y -= 6
                    y = _draw_summary_table_example_layout(
                        c,
                        str(filial),
                        recebidos_table,
                        y,
                        bloco_titulo="RECEBIDOS",
                        secao_titulo="Valores Recebidos (Frete Final)",
                    )

                if uf_table:
                    if y <= 180:
                        c.showPage()
                        y = 760
                    y -= 18
                    uf_comment = _build_soft_operational_comment(uf_table, str(filial), "fluxos para fora do estado")
                    if uf_comment:
                        y = _draw_wrapped_text(c, uf_comment, y, x=50, max_width=520)
                        y -= 6
                    y = _draw_table_on_canvas(c, "Valores por UF (Frete Final)", uf_table, y)

                if metric_lines:
                    if y <= 140:
                        c.showPage()
                        y = 760

                    y -= 14
                    c.setFont("Helvetica-Bold", 11)
                    c.drawString(50, y, "Insights Complementares")
                    y -= 18

                    for line in metric_lines[:8]:
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
