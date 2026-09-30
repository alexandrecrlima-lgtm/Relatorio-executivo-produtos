import os
import requests
from datetime import datetime

JIRA_DOMAIN = os.environ.get("JIRA_DOMAIN")
JIRA_EMAIL = os.environ.get("JIRA_EMAIL")
JIRA_API_TOKEN = os.environ.get("JIRA_API_TOKEN")

# Ajuste a consulta JQL conforme o nome do seu projeto e status no Jira
JQL_QUERY = "project = 'SUPORTE' AND status in ('Open', 'In Progress', 'Waiting for customer')"

def buscar_chamados_jira():
    url = f"https://{JIRA_DOMAIN}/rest/api/3/search/jql"
    auth = (JIRA_EMAIL, JIRA_API_TOKEN)
    headers = {"Accept": "application/json"}
    
    params = {
        "jql": JQL_QUERY,
        "maxResults": 100,
        "fields": ["summary", "status", "assignee", "created", "priority"]
    }

    response = requests.get(url, headers=headers, auth=auth, params=params)
    response.raise_for_status()
    return response.json().get("issues", [])

def gerar_html(issues):
    agora = datetime.now().strftime("%d/%m/%Y às %H:%M")
    
    linhas_tabela = ""
    for issue in issues:
        chave = issue.get("key", "")
        fields = issue.get("fields", {})
        resumo = fields.get("summary", "")
        status = fields.get("status", {}).get("name", "N/A")
        prioridade = fields.get("priority", {}).get("name", "N/A") if fields.get("priority") else "N/A"
        
        assignee_obj = fields.get("assignee")
        responsavel = assignee_obj.get("displayName", "Não atribuído") if assignee_obj else "Não atribuído"

        linhas_tabela += f"""
        <tr>
            <td><strong>{chave}</strong></td>
            <td>{resumo}</td>
            <td><span class="badge">{status}</span></td>
            <td>{prioridade}</td>
            <td>{responsavel}</td>
        </tr>
        """

    html = f"""
    <!DOCTYPE html>
    <html lang="pt-BR">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Status da Sustentação de Produtos</title>
        <style>
            body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; margin: 30px; background-color: #f4f5f7; color: #172b4d; }}
            .card {{ background: white; padding: 24px; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.12); }}
            h1 {{ margin-top: 0; color: #0052cc; }}
            .updated {{ font-size: 0.9em; color: #6b778c; margin-bottom: 20px; }}
            table {{ width: 100%; border-collapse: collapse; margin-top: 15px; }}
            th, td {{ padding: 12px; text-align: left; border-bottom: 1px solid #dfe1e6; }}
            th {{ background-color: #fafbfc; color: #5e6c84; font-size: 0.85em; text-transform: uppercase; }}
            .badge {{ background: #deebff; color: #0747a6; padding: 4px 8px; border-radius: 3px; font-weight: 600; font-size: 0.85em; }}
        </style>
    </head>
    <body>
        <div class="card">
            <h1>Relatório de Sustentação a Produtos Digitais</h1>
            <p class="updated">Última atualização automática: <strong>{agora}</strong></p>
            <p>Total de chamados em atendimento: <strong>{len(issues)}</strong></p>
            
            <table>
                <thead>
                    <tr>
                        <th>Chave</th>
                        <th>Resumo</th>
                        <th>Status</th>
                        <th>Prioridade</th>
                        <th>Responsável</th>
                    </tr>
                </thead>
                <tbody>
                    {linhas_tabela}
                </tbody>
            </table>
        </div>
    </body>
    </html>
    """
    
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html)

if __name__ == "__main__":
    dados = buscar_chamados_jira()
    gerar_html(dados)
    print("Relatório HTML gerado com sucesso!")
