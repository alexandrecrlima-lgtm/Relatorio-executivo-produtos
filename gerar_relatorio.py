import os
import json
import requests
from datetime import datetime

# ==============================================================================
# CONFIGURAÇÃO DE AMBIENTE E TRATAMENTO DA URL
# ==============================================================================
domain = os.environ.get("JIRA_DOMAIN", "").strip()
email = os.environ.get("JIRA_EMAIL", "").strip()
token = os.environ.get("JIRA_API_TOKEN", "").strip()

if domain and not domain.startswith("http://") and not domain.startswith("https://"):
    domain = f"https://{domain}"

domain = domain.rstrip("/")

# ==============================================================================
# MAPEAMENTO DOS PRODUTOS
# ==============================================================================
MAPEAMENTO_PRODUTOS = {
    "mensalista": {
        "name": "Mensalista Digital & Estapar",
        "keywords": ["mensalista", "credencial", "estapar digital"]
    },
    "za": {
        "name": "Estacionamento Rotativo / Zona Azul",
        "keywords": ["zona azul", "rotativo", "cad", "fiscalizacao"]
    },
    "login": {
        "name": "Login, Cadastro & Acesso Zul+",
        "keywords": ["login", "cadastro", "sms", "token", "senha", "conta"]
    },
    "tag": {
        "name": "Tag de Pedágio & Extensão Zul",
        "keywords": ["tag", "pedagio", "recarga tag"]
    },
    "reserva": {
        "name": "Estapar Reserva & Pátios",
        "keywords": ["reserva", "porto seguro", "patio", "vaga"]
    },
    "pay": {
        "name": "Estapar Pay / Pagar Estacionamento",
        "keywords": ["pay", "pagar estacionamento", "qr code", "pix"]
    },
    "tributos": {
        "name": "Tributos (Multas, IPVA & CRLV)",
        "keywords": ["tributo", "multa", "ipva", "crlv", "detran"]
    },
    "seguro": {
        "name": "Seguro Auto & Proteção",
        "keywords": ["seguro", "apolice", "sinistro"]
    },
    "baterias": {
        "name": "Baterias Moura & Parceiros",
        "keywords": ["bateria", "moura", "instalacao"]
    },
    "frotistas": {
        "name": "Frotistas & Gestão B2B",
        "keywords": ["frotista", "b2b", "frota", "corporativo"]
    },
    "sustentacao": {
        "name": "Suporte Operacional & Sustentação N3",
        "keywords": ["sustentacao", "banco", "script", "api", "n3", "logs"]
    }
}

def categorizar_chamado(issue):
    fields = issue.get("fields", {})
    components = [c.get("name", "").lower() for c in fields.get("components", [])]
    summary = fields.get("summary", "").lower()
    
    prod_intercom = str(fields.get("customfield_11629") or "").lower()
    motivo = str(fields.get("customfield_10476") or "").lower()
    
    texto_busca = f"{' '.join(components)} {summary} {prod_intercom} {motivo}"

    for key, info in MAPEAMENTO_PRODUTOS.items():
        for kw in info["keywords"]:
            if kw in texto_busca:
                return key
    return "sustentacao"

def calcular_diferenca_horas(dt_inicio_str, dt_fim_str):
    if not dt_inicio_str or not dt_fim_str:
        return None
    try:
        dt_inicio = datetime.strptime(dt_inicio_str[:19], "%Y-%m-%dT%H:%M:%S")
        dt_fim = datetime.strptime(dt_fim_str[:19], "%Y-%m-%dT%H:%M:%S")
        diff = (dt_fim - dt_inicio).total_seconds() / 3600.0
        return max(0.0, diff)
    except Exception:
        return None

def processar_chamados_jira(issues):
    products_data = {}
    for key, info in MAPEAMENTO_PRODUTOS.items():
        products_data[key] = {
            "name": info["name"],
            "total": 0,
            "sla_cumpridos": 0,
            "total_resolvidos": 0,
            "soma_horas_resolucao": 0.0,
            "months": [0] * 12,
            "motives_map": {}
        }

    for issue in issues:
        fields = issue.get("fields", {})
        cat_key = categorizar_chamado(issue)
        prod = products_data[cat_key]
        
        # 1. Contagem mensal por data de criação
        created_str = fields.get("created", "")
        if created_str:
            try:
                dt = datetime.strptime(created_str[:10], "%Y-%m-%d")
                mes_index = dt.month - 1
                if 0 <= mes_index <= 11:
                    prod["months"][mes_index] += 1
            except Exception:
                pass

        prod["total"] += 1
        
        # 2. MTTR Dinâmico e Cálculo de SLA
        resolution_date_str = fields.get("resolutiondate")
        if resolution_date_str and created_str:
            horas = calcular_diferenca_horas(created_str, resolution_date_str)
            if horas is not None:
                prod["soma_horas_resolucao"] += horas
                prod["total_resolvidos"] += 1
                if horas <= 24.0:
                    prod["sla_cumpridos"] += 1
        else:
            prod["sla_cumpridos"] += 1

        # 3. Motivos Dinâmicos
        resumo = fields.get("customfield_10476") or fields.get("customfield_11631") or fields.get("summary", "Outros Chamados")
        if isinstance(resumo, dict):
            resumo = resumo.get("value", "Outros Chamados")
        resumo_str = str(resumo).strip()
            
        motivos = prod["motives_map"]
        motivos[resumo_str] = motivos.get(resumo_str, 0) + 1

    # Finalização das métricas por produto
    for key, prod in products_data.items():
        total_prod = prod["total"]
        
        if total_prod > 0:
            pct_sla = (prod["sla_cumpridos"] / total_prod) * 100.0
            prod["sla"] = f"{pct_sla:.1f}%"
        else:
            prod["sla"] = "100.0%"

        if prod["total_resolvidos"] > 0:
            media_horas = prod["soma_horas_resolucao"] / prod["total_resolvidos"]
            dias = media_horas / 24.0
            prod["mttr"] = f"{media_horas:.1f} h (~{dias:.2f}d)"
        else:
            prod["mttr"] = "N/A"

        motivos_ordenados = sorted(prod["motives_map"].items(), key=lambda x: x[1], reverse=True)[:5]
        prod["motives"] = []
        div_total = total_prod if total_prod > 0 else 1
        for nome_motivo, qtd in motivos_ordenados:
            pct = f"{((qtd / div_total) * 100):.1f}%"
            prod["motives"].append({"name": nome_motivo, "qty": qtd, "pct": pct})
        
        del prod["motives_map"]
        del prod["sla_cumpridos"]
        del prod["total_resolvidos"]
        del prod["soma_horas_resolucao"]

    for key in products_data:
        products_data[key]["months"] = products_data[key]["months"][:10]

    return products_data

def executar_busca_v3(url, headers, auth, jql):
    issues_totais = []
    next_page_token = None

    while True:
        payload = {
            "jql": jql,
            "maxResults": 100,
            "fields": [
                "summary", "status", "components", "created", "resolutiondate", "priority",
                "customfield_10767", "customfield_22530", "customfield_11629",
                "customfield_10476", "customfield_11631", "level"
            ]
        }
        
        if next_page_token:
            payload["nextPageToken"] = next_page_token

        try:
            resp = requests.post(url, headers=headers, auth=auth, json=payload)
            if resp.status_code != 200:
                print(f"❌ Erro HTTP {resp.status_code}: {resp.text[:300]}")
                break

            data = resp.json()
            issues = data.get("issues", [])
            print(f"✅ Status 200 OK. Lote retornado: {len(issues)} chamados.")
            
            if not issues:
                break

            issues_totais.extend(issues)
            next_page_token = data.get("nextPageToken")
            
            if not next_page_token:
                break
        except Exception as e:
            print(f"❌ Exceção ao executar chamada API: {e}")
            break

    return issues_totais

def buscar_dados_jira():
    if not domain or not token or not email:
        print("❌ Erro: Variáveis de ambiente JIRA_DOMAIN, JIRA_EMAIL ou JIRA_API_TOKEN não configuradas.")
        return None

    url = f"{domain}/rest/api/3/search/jql"
    auth = (email, token)
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json"
    }

    # 🎯 JQL EXATA FORNECIDA POR VOCÊ TRADUZIDA PARA SINTAXE DE API (Nomes + IDs dos Custom Fields)
    jql = (
        'project in (TICKET, ECOIT) AND ('
        'level in ("Ecommerce - Suporte Sistemas", "Ecommerce - Suporte Sistemas N3", "Sustentação Intercom - Suporte Sistemas") OR '
        '"Segurança" in ("Ecommerce - Suporte Sistemas", "Ecommerce - Suporte Sistemas N3", "Sustentação Intercom - Suporte Sistemas") OR '
        'cf[10767] in ("Ecommerce - Suporte Sistemas", "Ecommerce - Suporte Sistemas N3") OR '
        'cf[22530] in ("Ecommerce - Suporte Sistemas", "Ecommerce - Suporte Sistemas N3") OR '
        '"Grupo Solucionador" in ("Ecommerce - Suporte Sistemas", "Ecommerce - Suporte Sistemas N3") OR '
        'labels in ("Ecommerce-Sistemas", "Ecommerce") OR '
        '"Request Type" = "Intercom Incidentes"'
        ') AND created >= "2026-01-01
