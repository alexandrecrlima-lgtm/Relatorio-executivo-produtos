import base64
import json
import os
import sys
from datetime import datetime
import requests

# 1. Obter variáveis de ambiente (GitHub Secrets)
JIRA_BASE_URL = os.environ.get("JIRA_BASE_URL", "").rstrip("/")
JIRA_USER_EMAIL = os.environ.get("JIRA_USER_EMAIL", "")
JIRA_API_TOKEN = os.environ.get("JIRA_API_TOKEN", "")

if not all([JIRA_BASE_URL, JIRA_USER_EMAIL, JIRA_API_TOKEN]):
    print("❌ Erro: Variáveis JIRA_BASE_URL, JIRA_USER_EMAIL ou JIRA_API_TOKEN não configuradas.")
    sys.exit(1)

# 2. Configurar Headers de Autenticação Basic Auth
auth_str = base64.b64encode(f"{JIRA_USER_EMAIL}:{JIRA_API_TOKEN}".encode("utf-8")).decode("utf-8")
headers = {
    "Accept": "application/json",
    "Content-Type": "application/json",
    "Authorization": f"Basic {auth_str}",
}

def fetch_all_jira_issues(jql_query, fields=None):
    """
    Busca todas as issues do Jira com suporte a paginação automática via /rest/api/3/search.
    """
    if fields is None:
        fields = [
            "key", "summary", "status", "assignee", 
            "reporter", "created", "updated", "resolutiondate", 
            "priority", "issuetype"
        ]

    search_url = f"{JIRA_BASE_URL}/rest/api/3/search"
    start_at = 0
    max_results = 100
    all_issues = []

    print(f"🔍 Executando JQL: {jql_query}")

    while True:
        payload = {
            "jql": jql_query,
            "startAt": start_at,
            "maxResults": max_results,
            "fields": fields,
        }

        try:
            response = requests.post(search_url, json=payload, headers=headers, timeout=30)
            
            if response.status_code != 200:
                print(f"❌ Erro HTTP {response.status_code}: {response.text}")
                break

            data = response.json()
            issues = data.get("issues", [])
            total = data.get("total", 0)

            if not issues:
                break

            all_issues.extend(issues)
            print(f"   -> Coletados {len(all_issues)} de {total} chamados...")

            start_at += len(issues)
            if start_at >= total:
                break

        except requests.exceptions.RequestException as e:
            print(f"❌ Erro na requisição: {e}")
            break

    print(f"✅ Total final coletado: {len(all_issues)} chamados.\n")
    return all_issues

def main():
    # Defina sua JQL de consulta aqui
    # Exemplo com grupos de suporte / backlog:
    jql = (
        'project = "SAC" '
        'ORDER BY created DESC'
    )

    issues = fetch_all_jira_issues(jql)

    if not issues:
        print("⚠️ Aviso: Nenhuma issue encontrada. Mantendo base anterior.")
        return

    # Garante a existência do diretório de saída
    os.makedirs("data", exist_ok=True)
    output_file = "data/jira_issues.json"

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(issues, f, ensure_ascii=False, indent=2)

    print(f"💾 Dados salvos com sucesso em: {output_file}")

if __name__ == "__main__":
    main()
