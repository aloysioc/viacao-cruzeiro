import re
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from function_app import _build_rule_based_insights


def _extract_total(insight_text: str, label: str) -> float:
    pattern = rf"{re.escape(label)}: total=([0-9]+\.[0-9]+)"
    match = re.search(pattern, insight_text)
    if not match:
        raise ValueError(f"Nao foi possivel encontrar a linha: {label}")
    return float(match.group(1))


def main() -> None:
    # Exemplo repassado pelo cliente.
    df = pd.DataFrame(
        [
            {
                "Unidade Emissora": "ACL",
                "Unidade Receptora": "SGO",
                "Tipo de Baixa": "LIQUIDADO",
                "Valor Liquidado": "42,18",
                "Valor do Frete": "42,18",
            },
            {
                "Unidade Emissora": "ACL",
                "Unidade Receptora": "ALC",
                "Tipo de Baixa": "LIQUIDADO",
                "Valor Liquidado": "95,45",
                "Valor do Frete": "90,46",
            },
            {
                "Unidade Emissora": "ACL",
                "Unidade Receptora": "CGR",
                "Tipo de Baixa": "FATURADO",
                "Valor Liquidado": "0,00",
                "Valor do Frete": "37,22",
            },
        ]
    )

    expected = {
        "ACL": {"expedido": 174.85, "recebido": 0.00},
        "SGO": {"expedido": 0.00, "recebido": 42.18},
        "ALC": {"expedido": 0.00, "recebido": 95.45},
        "CGR": {"expedido": 0.00, "recebido": 37.22},
    }

    print("Validacao da regra de negocio (sem destinatarios)")
    print("-" * 56)

    for filial, target in expected.items():
        branch_df = df[df["Unidade Emissora"].astype(str).str.strip().str.casefold() == filial.casefold()].copy()
        insight_text = _build_rule_based_insights(branch_df, filial, totals_source_df=df)

        expedido = _extract_total(insight_text, "Valor expedido final (Unidade Emissora)")
        recebido = _extract_total(insight_text, "Valor recebido final (Unidade Receptora)")

        ok_expedido = abs(expedido - target["expedido"]) < 0.01
        ok_recebido = abs(recebido - target["recebido"]) < 0.01
        status = "OK" if ok_expedido and ok_recebido else "FALHOU"

        print(
            f"{filial}: {status} | expedido={expedido:.2f} (esperado {target['expedido']:.2f})"
            f" | recebido={recebido:.2f} (esperado {target['recebido']:.2f})"
        )

    print("-" * 56)
    print("Fim da validacao.")


if __name__ == "__main__":
    main()
