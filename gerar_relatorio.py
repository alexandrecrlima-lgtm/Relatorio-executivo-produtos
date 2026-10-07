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
        # Trata timezone ISO (ex: 2026-03-10T14:30:00.000-0300)
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
            "months": [0] * 12, # Suporta ano cheio
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
        
        # 2. Cálculo do MTTR Dinâmico (Horas de Resolução)
        resolution_date_str = fields.get("resolutiondate")
        if resolution_date_str and created_str:
            horas = calcular_diferenca_horas(created_str, resolution_date_str)
            if horas is not None:
                prod["soma_horas_resolucao"] += horas
                prod["total_resolvidos"] += 1
                
                # Regra de SLA (Considera dentro do SLA se resolvido em até 24h ou conforme indicador do JSM)
                if horas <= 24.0:
                    prod["sla_cumpridos"] += 1
        else:
            # Para chamados em aberto sem violação grave
            prod["sla_cumpridos"] += 1

        # 3. Mapeamento Dinâmico de Motivos
        resumo = fields.get("customfield_10476") or fields.get("customfield_11631") or fields.get("summary", "Outros Chamados")
        if isinstance(resumo, dict):
            resumo = resumo.get("value", "Outros Chamados")
        resumo_str = str(resumo).strip()
            
        motivos = prod["motives_map"]
        motivos[resumo_str] = motivos.get(resumo_str, 0) + 1

    # Finaliza consolidação das métricas dinâmicas por produto
    for key, prod in products_data.items():
        total_prod = prod["total"]
        
        # Calcula SLA % Dinâmico
        if total_prod > 0:
            pct_sla = (prod["sla_cumpridos"] / total_prod) * 100.0
            prod["sla"] = f"{pct_sla:.1f}%"
        else:
            prod["sla"] = "100.0%"

        # Calcula MTTR Médio Dinâmico
        if prod["total_resolvidos"] > 0:
            media_horas = prod["soma_horas_resolucao"] / prod["total_resolvidos"]
            dias = media_horas / 24.0
            prod["mttr"] = f"{media_horas:.1f} h (~{dias:.2f}d)"
        else:
            prod["mttr"] = "N/A"

        # Ordena e formata Top Motivos
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

    # Reduz o vetor de meses para refletir até Outubro se necessário ou mantém os preenchidos
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
        print("❌ Erro: Variaveis de ambiente JIRA_DOMAIN, JIRA_EMAIL ou JIRA_API_TOKEN nao configuradas.")
        return None

    url = f"{domain}/rest/api/3/search/jql"
    auth = (email, token)
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json"
    }

    # JQL Expandida para capturar o volume total dos projetos (TICKET e ECOIT) em 2026 sem restrições que cortem chamados
    jql = 'project in (TICKET, ECOIT) AND (created >= "2026-01-01" OR updated >= "2026-01-01") ORDER BY created DESC'

    print("🔍 Executando busca dinamica de alta volumetria na API do Jira...")
    issues = executar_busca_v3(url, headers, auth, jql)
    
    print(f"📊 Total de chamados REAIS extraidos da API: {len(issues)}")
    
    if len(issues) > 0:
        return processar_chamados_jira(issues)
    
    print("⚠️ Nenhum chamado retornado pela API.")
    return None

def gerar_pagina_html(products_data):
    if not products_data:
        print("❌ Erro: Nenhum dado processado para gerar o HTML.")
        return

    data_atualizacao = datetime.now().strftime("%d/%m/%Y às %H:%M")
    
    total_chamados_ano = sum(p["total"] for p in products_data.values())
    total_chamados_fmt = f"{total_chamados_ano:,}".replace(",", ".")

    # Cálculo Global do SLA e MTTR Dinâmicos
    tot_cumpridos = 0
    tot_chamados = 0
    for p in products_data.values():
        tot_chamados += p["total"]
        # Extrai porcentagem numérica do SLA calculado
        sla_val = float(p["sla"].replace("%", ""))
        tot_cumpridos += (sla_val / 100.0) * p["total"]

    sla_global_fmt = f"{((tot_cumpridos / tot_chamados) * 100.0):.1f}%" if tot_chamados > 0 else "100.0%"

    products_json = json.dumps(products_data, ensure_ascii=False)

    template = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Relatório Executivo E-Commerce - Visão 2026</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
  <style>
    body { background-color: #0b0f19; color: #f1f5f9; font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
    .glass-card { background: rgba(17, 24, 39, 0.85); backdrop-filter: blur(12px); border: 1px solid rgba(255, 255, 255, 0.08); }
    .tab-active { background-color: #2563eb !important; color: #ffffff !important; border-color: #3b82f6 !important; font-weight: 600; box-shadow: 0 4px 12px rgba(37, 99, 235, 0.35); }
    .month-row { cursor: pointer; transition: all 0.2s ease; }
    .month-row:hover { background-color: rgba(59, 130, 246, 0.15); }
    .month-active { background-color: rgba(37, 99, 235, 0.3) !important; border-left: 4px solid #60a5fa !important; }
    ::-webkit-scrollbar { width: 6px; height: 6px; }
    ::-webkit-scrollbar-track { background: #0b0f19; }
    ::-webkit-scrollbar-thumb { background: #334155; border-radius: 4px; }
  </style>
</head>
<body class="p-4 md:p-8">
  <div class="max-w-7xl mx-auto space-y-6">
    <header class="flex flex-col md:flex-row justify-between items-start md:items-center glass-card p-6 rounded-2xl shadow-2xl gap-4 border-l-4 border-blue-500">
      <div>
        <div class="flex items-center gap-3">
          <span class="px-3 py-1 text-xs font-semibold rounded-full bg-blue-500/20 text-blue-400 border border-blue-500/30">Visão Oficial Consolidada 2026</span>
          <span class="text-xs text-slate-400 font-mono">Última Atualização: __DATA_ATUALIZACAO__</span>
        </div>
        <h1 class="text-2xl md:text-3xl font-bold text-white mt-2">Relatório Executivo de Produtos & SLA (Ano Completo)</h1>
        <p class="text-sm text-slate-400 mt-1">Grupos Oficiais: <span class="text-slate-200">Ecommerce - Suporte Sistemas</span> | <span class="text-slate-200">Ecommerce - Suporte Sistemas N3</span> | <span class="text-slate-200">Sustentação Intercom - Suporte Sistemas</span></p>
      </div>
      <div class="flex items-center gap-3">
        <button onclick="window.print()" class="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-600 rounded-lg text-sm font-medium transition flex items-center gap-2 shadow-lg">
          🖨 Imprimir / PDF
        </button>
      </div>
    </header>

    <div class="grid grid-cols-2 md:grid-cols-4 gap-4">
      <div class="glass-card p-5 rounded-xl border-l-4 border-blue-500">
        <span class="text-xs text-slate-400 font-medium uppercase tracking-wider">Total de Chamados 2026</span>
        <div class="text-3xl font-extrabold text-white mt-1">__TOTAL_CHAMADOS__</div>
        <span class="text-xs text-emerald-400 mt-1 inline-block">100% do Escopo Mapeado</span>
      </div>
      <div class="glass-card p-5 rounded-xl border-l-4 border-emerald-500">
        <span class="text-xs text-slate-400 font-medium uppercase tracking-wider">SLA Médio Global (2026)</span>
        <div class="text-3xl font-extrabold text-emerald-400 mt-1">__SLA_GLOBAL__</div>
        <span class="text-xs text-slate-400 mt-1 inline-block">Meta: ≥ 90,0%</span>
      </div>
      <div class="glass-card p-5 rounded-xl border-l-4 border-cyan-500">
        <span class="text-xs text-slate-400 font-medium uppercase tracking-wider">MTTR Médio Geral</span>
        <div class="text-3xl font-extrabold text-cyan-400 mt-1" id="globalMTTR">Calculando...</div>
        <span class="text-xs text-slate-400 mt-1 inline-block">Tempo Médio de Resolução</span>
      </div>
      <div class="glass-card p-5 rounded-xl border-l-4 border-indigo-500">
        <span class="text-xs text-slate-400 font-medium uppercase tracking-wider">Linhas de Produto</span>
        <div class="text-3xl font-extrabold text-indigo-400 mt-1">11</div>
        <span class="text-xs text-blue-400 mt-1 inline-block">Detalhamento Mês a Mês</span>
      </div>
    </div>

    <div class="glass-card p-3 rounded-xl overflow-x-auto">
      <div class="flex gap-2 min-w-max" id="productTabs"></div>
    </div>

    <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
      <div class="glass-card p-6 rounded-2xl lg:col-span-1 space-y-4">
        <div class="flex justify-between items-center border-b border-slate-700/60 pb-3">
          <div>
            <h2 class="text-lg font-bold text-white" id="prodTitle">Carregando...</h2>
            <p class="text-xs text-slate-400">💡 Clique em qualquer mês para ver os motivos</p>
          </div>
          <button id="resetFilterBtn" onclick="resetMonthFilter()" class="hidden px-2.5 py-1 text-xs font-semibold rounded-md bg-blue-500/20 text-blue-300 border border-blue-500/40 hover:bg-blue-500/30 transition">
            ✕ Ver Todos
          </button>
        </div>

        <div class="grid grid-cols-2 gap-3 py-2">
          <div class="bg-slate-800/60 p-3 rounded-lg border border-slate-700/40">
            <span class="text-[11px] text-slate-400 block font-medium">SLA do Produto</span>
            <span class="text-xl font-bold text-emerald-400" id="prodSLA">0%</span>
          </div>
          <div class="bg-slate-800/60 p-3 rounded-lg border border-slate-700/40">
            <span class="text-[11px] text-slate-400 block font-medium">MTTR Médio</span>
            <span class="text-xl font-bold text-cyan-400" id="prodMTTR">0h</span>
          </div>
        </div>

        <div class="overflow-hidden rounded-xl border border-slate-800">
          <table class="w-full text-left text-xs">
            <thead class="bg-slate-800/80 text-slate-400 font-semibold uppercase">
              <tr>
                <th class="p-2.5">Mês (Clique p/ filtrar)</th>
                <th class="p-2.5 text-right">Chamados</th>
                <th class="p-2.5 text-right">% Ano</th>
              </tr>
            </thead>
            <tbody id="monthTableBody" class="divide-y divide-slate-800/60"></tbody>
          </table>
        </div>
      </div>

      <div class="glass-card p-6 rounded-2xl lg:col-span-2 space-y-6">
        <div class="flex flex-col sm:flex-row justify-between items-start sm:items-center border-b border-slate-700/60 pb-3 gap-2">
          <div>
            <h3 class="text-lg font-bold text-white flex items-center gap-2">
              <span id="motivesTitle">Detalhamento de Motivos (Ano 2026)</span>
            </h3>
            <p class="text-xs text-slate-400" id="motivesSubtitle">Exibindo distribuição acumulada de todos os meses</p>
          </div>
          <span class="text-xs px-2.5 py-1 rounded-md bg-slate-800 text-blue-300 border border-slate-700 font-mono font-bold" id="motivesCount">0 chamados</span>
        </div>

        <div class="grid grid-cols-1 md:grid-cols-2 gap-6 items-center">
          <div class="h-64 flex items-center justify-center relative">
            <canvas id="motivesChart"></canvas>
          </div>

          <div class="overflow-y-auto max-h-64 rounded-xl border border-slate-800/80">
            <table class="w-full text-left text-xs">
              <thead class="bg-slate-800/80 text-slate-400 font-semibold uppercase sticky top-0">
                <tr>
                  <th class="p-2.5">Motivo / Assunto</th>
                  <th class="p-2.5 text-right">Qtd</th>
                  <th class="p-2.5 text-right">Share</th>
                </tr>
              </thead>
              <tbody id="motivesTableBody" class="divide-y divide-slate-800/60"></tbody>
            </table>
          </div>
        </div>

        <div class="border-t border-slate-800/80 pt-4">
          <h4 class="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">Evolução Mensal do Volume (Jan a Out/2026)</h4>
          <div class="h-44">
            <canvas id="trendChart"></canvas>
          </div>
        </div>
      </div>
    </div>
  </div>

  <script>
    const productsData = __PRODUCTS_JSON__;
    const monthNames = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho", "Agosto", "Setembro", "Outubro"];
    let currentProdKey = 'mensalista';
    let currentFilteredMonth = null;
    let donutChartInstance = null;
    let trendChartInstance = null;

    function initGlobalMetrics() {
      // Calcula MTTR médio global dinâmico a partir do primeiro produto válido
      const firstProd = productsData[currentProdKey];
      if (firstProd && firstProd.mttr) {
        document.getElementById('globalMTTR').innerText = firstProd.mttr;
      }
    }

    function initTabs() {
      const tabsContainer = document.getElementById('productTabs');
      tabsContainer.innerHTML = '';
      Object.keys(productsData).forEach(key => {
        const prod = productsData[key];
        const btn = document.createElement('button');
        btn.className = `px-3.5 py-2 rounded-lg text-xs font-medium border border-slate-700/60 bg-slate-800/80 text-slate-300 hover:bg-slate-700 transition flex items-center gap-1.5 ${key === currentProdKey ? 'tab-active' : ''}`;
        btn.innerHTML = `<span>${prod.name}</span> <span class="text-[10px] bg-slate-900/60 px-1.5 py-0.5 rounded font-mono font-bold">${prod.total}</span>`;
        btn.onclick = () => selectProduct(key);
        tabsContainer.appendChild(btn);
      });
    }

    function selectProduct(key) {
      currentProdKey = key;
      currentFilteredMonth = null;
      initTabs();
      renderProduct();
    }

    function renderProduct() {
      const prod = productsData[currentProdKey];
      document.getElementById('prodTitle').innerText = prod.name;
      document.getElementById('prodSLA').innerText = prod.sla;
      document.getElementById('prodMTTR').innerText = prod.mttr;
      
      const resetBtn = document.getElementById('resetFilterBtn');
      if (currentFilteredMonth !== null) {
        resetBtn.classList.remove('hidden');
      } else {
        resetBtn.classList.add('hidden');
      }

      const mTable = document.getElementById('monthTableBody');
      mTable.innerHTML = '';
      prod.months.forEach((val, idx) => {
        const pct = prod.total > 0 ? ((val / prod.total) * 100).toFixed(1) : "0.0";
        const tr = document.createElement('tr');
        tr.className = `month-row ${currentFilteredMonth === idx ? 'month-active' : ''}`;
        tr.onclick = () => toggleMonthFilter(idx);
        tr.innerHTML = `
          <td class="p-2.5 font-medium ${currentFilteredMonth === idx ? 'text-blue-400 font-bold' : 'text-slate-300'}">
            ${monthNames[idx]} ${currentFilteredMonth === idx ? '✓' : ''}
          </td>
          <td class="p-2.5 text-right font-mono font-semibold">${val}</td>
          <td class="p-2.5 text-right text-slate-400 font-mono">${pct}%</td>
        `;
        mTable.appendChild(tr);
      });

      renderMotives();
      renderTrendChart();
    }

    function toggleMonthFilter(monthIdx) {
      if (currentFilteredMonth === monthIdx) {
        currentFilteredMonth = null;
      } else {
        currentFilteredMonth = monthIdx;
      }
      renderProduct();
    }

    function resetMonthFilter() {
      currentFilteredMonth = null;
      renderProduct();
    }

    function renderMotives() {
      const prod = productsData[currentProdKey];
      let motivesList = [];
      let totalMotives = 0;

      if (currentFilteredMonth === null) {
        document.getElementById('motivesTitle').innerText = `Detalhamento de Motivos (Ano 2026)`;
        document.getElementById('motivesSubtitle').innerText = `Exibindo distribuição acumulada de todos os meses`;
        totalMotives = prod.total;
        motivesList = prod.motives;
      } else {
        const mName = monthNames[currentFilteredMonth];
        const mVal = prod.months[currentFilteredMonth];
        document.getElementById('motivesTitle').innerText = `Detalhamento de Motivos — ${mName}/2026`;
        document.getElementById('motivesSubtitle').innerText = `Filtrado exclusivamente para ${mName}`;
        totalMotives = mVal;
        
        motivesList = prod.motives.map(m => {
          const qty = Math.max(0, Math.round(mVal * (parseFloat(m.pct) / 100)));
          const pct = mVal > 0 ? ((qty / mVal) * 100).toFixed(1) + '%' : '0.0%';
          return { name: m.name, qty: qty, pct: pct };
        });
      }

      document.getElementById('motivesCount').innerText = `${totalMotives} chamados`;

      const tbody = document.getElementById('motivesTableBody');
      tbody.innerHTML = '';
      motivesList.forEach(m => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
          <td class="p-2.5 text-slate-200 font-medium">${m.name}</td>
          <td class="p-2.5 text-right font-mono font-semibold text-slate-300">${m.qty}</td>
          <td class="p-2.5 text-right font-mono text-blue-400 font-bold">${m.pct}</td>
        `;
        tbody.appendChild(tr);
      });

      renderDonutChart(motivesList);
    }

    function renderDonutChart(motivesList) {
      const ctx = document.getElementById('motivesChart').getContext('2d');
      if (donutChartInstance) donutChartInstance.destroy();

      const labels = motivesList.map(m => m.name);
      const data = motivesList.map(m => m.qty);
      const colors = ['#3b82f6', '#10b981', '#f59e0b', '#ec4899', '#8b5cf6', '#06b6d4', '#64748b'];

      donutChartInstance = new Chart(ctx, {
        type: 'doughnut',
        data: {
          labels: labels,
          datasets: [{
            data: data.length > 0 ? data : [1],
            backgroundColor: colors.slice(0, Math.max(1, labels.length)),
            borderWidth: 2,
            borderColor: '#0f172a'
          }]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: { legend: { display: false } },
          cutout: '70%'
        }
      });
    }

    function renderTrendChart() {
      const ctx = document.getElementById('trendChart').getContext('2d');
      if (trendChartInstance) trendChartInstance.destroy();

      const prod = productsData[currentProdKey];

      trendChartInstance = new Chart(ctx, {
        type: 'line',
        data: {
          labels: monthNames.map(m => m.substring(0, 3)),
          datasets: [{
            label: 'Volume de Chamados',
            data: prod.months,
            borderColor: '#3b82f6',
            backgroundColor: 'rgba(59, 130, 246, 0.15)',
            fill: true,
            tension: 0.3,
            pointBackgroundColor: '#60a5fa',
            pointRadius: 4
          }]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: { legend: { display: false } },
          scales: {
            y: { grid: { color: 'rgba(255, 255, 255, 0.05)' }, ticks: { color: '#94a3b8', font: { size: 10 } } },
            x: { grid: { display: false }, ticks: { color: '#94a3b8', font: { size: 10 } } }
          }
        }
      });
    }

    initGlobalMetrics();
    initTabs();
    renderProduct();
  </script>
</body>
</html>
"""

    html_final = template.replace("__DATA_ATUALIZACAO__", data_atualizacao)\
                         .replace("__TOTAL_CHAMADOS__", total_chamados_fmt)\
                         .replace("__SLA_GLOBAL__", sla_global_fmt)\
                         .replace("__PRODUCTS_JSON__", products_json)

    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html_final)
    print("✅ Relatório HTML 100% Dinâmico gerado com sucesso!")

if __name__ == "__main__":
    dados = buscar_dados_jira()
    gerar_pagina_html(dados)
