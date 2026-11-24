#!/usr/bin/env python3
"""
Lista os contactos com mensagens de HOJE com status "falhou" na API OLÁ (Pavulla).

Autenticação e URL base iguais ao enviar_sms.py: HTTP Basic com o token como
utilizador e palavra-passe vazia, contra https://api.ola.pavulla.com.

Uso:
    export OLA_API_TOKEN="o_teu_token"
    python3 ola_falhas_hoje.py

Opções:
    --data AAAA-MM-DD   usar outro dia em vez de hoje
    --csv ficheiro.csv  nome do CSV de saída (por omissão: falhas_AAAA-MM-DD.csv)

Variável opcional: OLA_BASE_URL (por omissão https://api.ola.pavulla.com).

Só usa a biblioteca padrão do Python (3.9+).
"""
import argparse
import base64
import csv
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Africa/Maputo")
BASE_URL = os.environ.get("OLA_BASE_URL", "https://api.ola.pavulla.com").rstrip("/")
API_TOKEN = os.environ.get("OLA_API_TOKEN", "aaAQSFAQiTnRwYB9oyCIBlURpGACji1OrhY9Vr9stgLbYPmotRPope51U7corUhm")
# Basic auth: token como utilizador, palavra-passe vazia (equivale a auth=(token, "") no requests)
AUTH_HEADER = "Basic " + base64.b64encode(f"{API_TOKEN}:".encode()).decode()
PAGE_SIZE = 100  # máximo permitido pela API
STATUS = "failed"


def fetch_page(params: dict) -> dict:
    url = f"{BASE_URL}/v1/messages?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"Authorization": AUTH_HEADER})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        corpo = e.read().decode("utf-8", errors="replace")[:500]
        sys.exit(f"Erro HTTP {e.code} da API: {corpo}")
    except urllib.error.URLError as e:
        sys.exit(f"Não foi possível ligar à API ({BASE_URL}): {e.reason}")


def list_failed(day_start: datetime, day_end: datetime) -> list:
    params = {
        "status": STATUS,
        "limite": PAGE_SIZE,
        "hora_inicio": day_start.isoformat(),
        "hora_fim": day_end.isoformat(),
    }
    messages = []
    while True:
        page = fetch_page(params)
        data = page.get("data", [])
        messages.extend(data)
        if not page.get("has_more") or not data:
            break
        params["inicio_apos"] = data[-1]["id"]  # cursor: continuar depois da última mensagem
    # garantia extra caso o filtro do servidor seja sensível a maiúsculas
    return [m for m in messages if str(m.get("status", "")).lower() == STATUS]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", help="dia a consultar (AAAA-MM-DD); por omissão, hoje")
    ap.add_argument("--csv", help="ficheiro CSV de saída")
    args = ap.parse_args()

    if not API_TOKEN:
        sys.exit("Define a variável de ambiente OLA_API_TOKEN com o teu token da API.")

    dia = datetime.strptime(args.data, "%Y-%m-%d").date() if args.data else datetime.now(TZ).date()
    inicio = datetime.combine(dia, time.min, tzinfo=TZ)
    fim = inicio + timedelta(days=1) - timedelta(seconds=1)

    msgs = list_failed(inicio, fim)

    # um contacto pode ter várias falhas: agrupar por destinatário
    contactos = {}
    for m in msgs:
        r = m.get("recipient") or "?"
        c = contactos.setdefault(r, {"falhas": 0, "ultima_falha": "", "mensagem": ""})
        c["falhas"] += 1
        quando = m.get("failed_at") or m.get("updated_at") or ""
        if quando >= c["ultima_falha"]:
            c["ultima_falha"] = quando
            c["mensagem"] = m.get("content", "")

    print(f"{dia}: {len(msgs)} mensagens falhadas, {len(contactos)} contactos únicos\n")
    for r, c in sorted(contactos.items()):
        print(f"{r}  (falhas: {c['falhas']})")

    saida = args.csv or f"falhas_{dia}.csv"
    with open(saida, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["destinatario", "falhas", "ultima_falha", "mensagem"])
        for r, c in sorted(contactos.items()):
            w.writerow([r, c["falhas"], c["ultima_falha"], c["mensagem"]])
    print(f"\nCSV guardado em: {saida}")


if __name__ == "__main__":
    main()
