import os
import json
import time
import requests
from requests.auth import HTTPBasicAuth

# ==========================================
# 1. Configurações e Variáveis de Ambiente
# ==========================================
JIRA_DOMAIN = os.environ.get("JIRA_DOMAIN", "seu-dominio.atlassian.net")
JIRA_EMAIL = os.environ.get("JIRA_EMAIL")
JIRA_API_TOKEN = os.environ.get("JIRA_API_TOKEN")

if not JIRA_EMAIL or not JIRA_API_TOKEN:
    raise ValueError("As variáveis JIRA_EMAIL e JIRA_API_TOKEN precisam estar configuradas no ambiente.")

BASE_URL = f"https://{JIRA_DOMAIN}/rest/api/3/search/jql"
AUTH = HTTPBasicAuth(JIRA_EMAIL, JIRA_API_TOKEN)
HEADERS = {
    "Accept": "application/json",
    "Content-Type": "application/json; charset=utf-8"
}

# ==========================================
# 2. JQL Oficial Ajustada com IDs Reais
# ==========================================
JQL_QUERY = """
project in (TICKET, ECOIT) AND (
    level in ("Ecommerce - Suporte Sistemas", "Ecommerce - Suporte Sistemas N3", "Sustentação Intercom - Suporte Sistemas")
    OR cf[10767] in ("Ecommerce - Suporte Sistemas", "Ecommerce - Suporte Sistemas N3")
    OR labels in ("Ecommerce-Sistemas", "Ecommerce")
    OR "Request Type" = "Intercom Incidentes"
) AND created >= "2026-01-01 00:00"
""".strip()

# Mapeamento explícito dos campos de interesse
FIELDS_TO_FETCH = [
    "key",
    "summary",
    "status",
    "created",
    "updated",
    "labels",
    "level",               # Nível de Segurança
    "customfield_10767",   # Grupo Solucionador
    "customfield_11629",   # Produto Intercom
    "customfield_10812",   # Produtos Intercom (Option)
    "customfield_11631",   # Assunto Primário
    "customfield_10476",   # Motivo / Causa Raiz
    "customfield_11630",   # Canal de Atendimento - Intercom
    "customfield_11056",   # Incidente ou Requisição
    "customfield_10023",   # SLA Tempo de Resolução
    "customfield_10022"    # SLA Tempo até a Primeira Resposta
]

def parse_custom_field(value):
    """Auxiliar para extrair o valor legível de campos do Jira que podem ser dicionários ou listas."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return value.get("value") or value.get("name") or str(value)
    if isinstance(value, list):
        return [parse_custom_field(item) for item in value]
    return str(value)

def fetch_all_jira_issues():
    """Realiza a extração paginada utilizando o nextPageToken da API v3."""
    all_issues = []
    next_page_token = None
    page = 1

    print("🚀 Iniciando extração de dados do Jira Cloud...")

    while True:
        payload = {
            "jql": JQL_QUERY,
            "maxResults": 100,
            "fields": FIELDS_TO_FETCH
        }
        if next_page_token:
            payload["nextPageToken"] = next_page_token

        response = requests.post(
            BASE_URL,
            data=json.dumps(payload),
            headers=HEADERS,
            auth=AUTH,
            timeout=30
        )

        if response.status_code != 200:
            print(f"❌ Erro na requisição (Status {response.status_code}): {response.text}")
            response.raise_for_status()

        data = response.json()
        issues = data.get("issues", [])
        all_issues.extend(issues)

        print(f"📦 Página {page} processada | +{len(issues)} chamados (Total acumulado: {len(all_issues)})")

        next_page_token = data.get("nextPageToken")
        if not next_page_token:
            break
            
        page += 1
        time.sleep(0.1)  # Respeito ao Rate Limit da API Cloud

    print(f"✅ Extração concluída! Total extraído: {len(all_issues)} chamados.")
    return all_issues

def process_and_normalize_issues(raw_issues):
    """Trata e normaliza o JSON bruto em um formato simplificado para o relatório HTML."""
    processed_data = []

    for issue in raw_issues:
        fields = issue.get("fields", {})

        # Extração tratada de cada campo customizado
        item = {
            "key": issue.get("key"),
            "resumo": fields.get("summary", ""),
            "status": fields.get("status", {}).get("name", "") if fields.get("status") else "",
            "data_criacao": fields.get("created", ""),
            "data_atualizacao": fields.get("updated", ""),
            "labels": fields.get("labels", []),
            "nivel_seguranca": fields.get("level", {}).get("name") if fields.get("level") else "",
            "grupo_solucionador": parse_custom_field(fields.get("customfield_10767")),
            "produto_intercom": fields.get("customfield_11629") or parse_custom_field(fields.get("customfield_10812")) or "Não Especificado",
            "assunto_primario": parse_custom_field(fields.get("customfield_11631")) or "Outros",
            "motivo_causa_raiz": parse_custom_field(fields.get("customfield_10476")) or "N/A",
            "canal_atendimento": parse_custom_field(fields.get("customfield_11630")) or "Chat",
            "tipo_classificacao": parse_custom_field(fields.get("customfield_11056")) or "Incidente",
        }

        processed_data.append(item)

    return processed_data

if __name__ == "__main__":
    raw_data = fetch_all_jira_issues()
    cleaned_data = process_and_normalize_issues(raw_data)

    # Salva o resultado tratado em JSON local para inspeção/utilização no build do HTML
    output_filename = "dados_jira_consolidado.json"
    with open(output_filename, "w", encoding="utf-8") as f:
        json.dump(cleaned_data, f, ensure_ascii=False, indent=2)

    print(f"🎉 Arquivo final salvo com sucesso: {output_filename}")
