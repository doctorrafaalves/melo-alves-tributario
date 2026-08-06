
import os
import io
import csv
import json
import hmac
import hashlib
import secrets
import sqlite3
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd
import plotly.express as px
import requests
import streamlit as st
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak


APP_NAME = "Melo Alves Tax Governance"
DB_PATH = Path(os.getenv("DATABASE_PATH", "melo_alves.db"))
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "uploads"))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

RISK_LEVELS = ["Crítico", "Alto", "Médio", "Baixo", "Oportunidade"]
TASK_STATUS = [
    "Não iniciada", "Aguardando cliente", "Aguardando contador",
    "Aguardando advogado", "Em análise", "Em revisão",
    "Concluída", "Cancelada", "Bloqueada"
]
PROJECT_STATUS = ["Planejado", "Em andamento", "Em revisão", "Concluído", "Suspenso"]
DOCUMENT_STATUS = ["Recebido", "Pendente de classificação", "Em validação", "Validado", "Rejeitado", "Substituído", "Arquivado"]
CREDIT_STATUS = [
    "Identificado", "Documentação pendente", "Conciliado",
    "Validado pelo contador", "Revisado pelo advogado",
    "Aprovado para utilização", "Utilizado", "Ressarcido",
    "Rejeitado", "Em discussão"
]


# =========================================================
# CONFIGURAÇÃO
# =========================================================

st.set_page_config(
    page_title=APP_NAME,
    page_icon="⚖️",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
    .block-container {padding-top: 1.2rem; padding-bottom: 2rem;}
    .main-title {font-size: 2.1rem; font-weight: 800; margin-bottom: 0;}
    .sub-title {font-size: 1rem; color: #667085; margin-top: 0;}
    .card {
        border: 1px solid #e4e7ec;
        border-radius: 12px;
        padding: 16px;
        background: white;
        margin-bottom: 12px;
    }
    .risk-critical {border-left: 6px solid #b42318;}
    .risk-high {border-left: 6px solid #f79009;}
    .risk-medium {border-left: 6px solid #fdb022;}
    .risk-low {border-left: 6px solid #12b76a;}
    .risk-opportunity {border-left: 6px solid #1570ef;}
    .small-muted {font-size: .82rem; color: #667085;}
    [data-testid="stMetricValue"] {font-size: 1.7rem;}
    footer {visibility: hidden;}
</style>
""", unsafe_allow_html=True)


# =========================================================
# BANCO DE DADOS
# =========================================================

def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def execute(sql, params=()):
    with get_conn() as conn:
        cur = conn.execute(sql, params)
        conn.commit()
        return cur.lastrowid


def query(sql, params=()):
    with get_conn() as conn:
        return [dict(row) for row in conn.execute(sql, params).fetchall()]


def query_one(sql, params=()):
    rows = query(sql, params)
    return rows[0] if rows else None


def init_db():
    schema = """
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        salt TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'Administrador',
        active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS clients (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        legal_name TEXT NOT NULL,
        trade_name TEXT,
        cnpj TEXT,
        tax_regime TEXT,
        annual_revenue REAL DEFAULT 0,
        sector TEXT,
        erp TEXT,
        accountant TEXT,
        status TEXT DEFAULT 'Ativo',
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS companies (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        client_id INTEGER NOT NULL,
        legal_name TEXT NOT NULL,
        cnpj TEXT,
        company_type TEXT DEFAULT 'Matriz',
        tax_regime TEXT,
        state TEXT,
        city TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY(client_id) REFERENCES clients(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS conflict_checks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        client_name TEXT NOT NULL,
        cnpj TEXT,
        related_parties TEXT,
        public_bodies TEXT,
        description TEXT,
        status TEXT NOT NULL,
        decision TEXT,
        responsible TEXT,
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS projects (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        client_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        project_type TEXT NOT NULL,
        status TEXT NOT NULL,
        responsible TEXT,
        start_date TEXT,
        due_date TEXT,
        description TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY(client_id) REFERENCES clients(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS risks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        client_id INTEGER NOT NULL,
        project_id INTEGER,
        title TEXT NOT NULL,
        category TEXT,
        description TEXT,
        cause TEXT,
        consequence TEXT,
        probability INTEGER DEFAULT 1,
        impact INTEGER DEFAULT 1,
        level TEXT NOT NULL,
        monthly_value REAL DEFAULT 0,
        annual_value REAL DEFAULT 0,
        evidence TEXT,
        legal_basis TEXT,
        treatment TEXT,
        responsible TEXT,
        due_date TEXT,
        status TEXT DEFAULT 'Aberto',
        legal_validation TEXT DEFAULT 'Pendente',
        accounting_validation TEXT DEFAULT 'Pendente',
        created_at TEXT NOT NULL,
        FOREIGN KEY(client_id) REFERENCES clients(id) ON DELETE CASCADE,
        FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE SET NULL
    );

    CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        client_id INTEGER NOT NULL,
        project_id INTEGER,
        title TEXT NOT NULL,
        description TEXT,
        responsible TEXT,
        priority TEXT,
        due_date TEXT,
        status TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY(client_id) REFERENCES clients(id) ON DELETE CASCADE,
        FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE SET NULL
    );

    CREATE TABLE IF NOT EXISTS documents (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        client_id INTEGER NOT NULL,
        category TEXT NOT NULL,
        subcategory TEXT,
        original_name TEXT NOT NULL,
        stored_path TEXT NOT NULL,
        period TEXT,
        status TEXT NOT NULL,
        hash_sha256 TEXT NOT NULL,
        notes TEXT,
        uploaded_by TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY(client_id) REFERENCES clients(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS tax_credits (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        client_id INTEGER NOT NULL,
        tax_name TEXT,
        period TEXT,
        origin TEXT,
        supplier TEXT,
        operation_value REAL DEFAULT 0,
        credit_value REAL DEFAULT 0,
        legal_basis TEXT,
        payment_status TEXT,
        status TEXT NOT NULL,
        accounting_validation TEXT DEFAULT 'Pendente',
        legal_validation TEXT DEFAULT 'Pendente',
        notes TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY(client_id) REFERENCES clients(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS public_contracts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        client_id INTEGER NOT NULL,
        public_body TEXT NOT NULL,
        contract_number TEXT,
        object TEXT,
        original_value REAL DEFAULT 0,
        current_value REAL DEFAULT 0,
        start_date TEXT,
        end_date TEXT,
        risk_matrix TEXT,
        status TEXT DEFAULT 'Ativo',
        created_at TEXT NOT NULL,
        FOREIGN KEY(client_id) REFERENCES clients(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS rebalancing_cases (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        client_id INTEGER NOT NULL,
        public_contract_id INTEGER,
        event_description TEXT NOT NULL,
        event_date TEXT,
        gross_impact REAL DEFAULT 0,
        credits_effect REAL DEFAULT 0,
        net_impact REAL DEFAULT 0,
        amount_claimed REAL DEFAULT 0,
        amount_recognized REAL DEFAULT 0,
        amount_received REAL DEFAULT 0,
        stage TEXT,
        probability TEXT,
        status TEXT,
        notes TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY(client_id) REFERENCES clients(id) ON DELETE CASCADE,
        FOREIGN KEY(public_contract_id) REFERENCES public_contracts(id) ON DELETE SET NULL
    );

    CREATE TABLE IF NOT EXISTS meetings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        client_id INTEGER NOT NULL,
        meeting_date TEXT NOT NULL,
        participants TEXT,
        agenda TEXT,
        summary TEXT,
        decisions TEXT,
        next_steps TEXT,
        status TEXT DEFAULT 'Minuta',
        created_at TEXT NOT NULL,
        FOREIGN KEY(client_id) REFERENCES clients(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS monthly_cycles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        client_id INTEGER NOT NULL,
        reference_month TEXT NOT NULL,
        documentary_compliance TEXT,
        credit_governance TEXT,
        liquidity TEXT,
        contracts_pricing TEXT,
        litigation_evidence TEXT,
        executive_summary TEXT,
        status TEXT DEFAULT 'Em andamento',
        created_at TEXT NOT NULL,
        UNIQUE(client_id, reference_month),
        FOREIGN KEY(client_id) REFERENCES clients(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS audit_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_email TEXT,
        action TEXT NOT NULL,
        entity TEXT,
        entity_id TEXT,
        details TEXT,
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS ai_interactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_email TEXT,
        client_id INTEGER,
        prompt TEXT,
        response TEXT,
        model TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY(client_id) REFERENCES clients(id) ON DELETE SET NULL
    );
    """
    with get_conn() as conn:
        conn.executescript(schema)
        conn.commit()


def password_hash(password: str, salt_hex: Optional[str] = None):
    salt = bytes.fromhex(salt_hex) if salt_hex else secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 180_000)
    return digest.hex(), salt.hex()


def verify_password(password: str, expected_hash: str, salt_hex: str):
    calculated, _ = password_hash(password, salt_hex)
    return hmac.compare_digest(calculated, expected_hash)


def log_action(action, entity="", entity_id="", details=""):
    email = st.session_state.get("user", {}).get("email", "sistema")
    execute(
        "INSERT INTO audit_logs(user_email, action, entity, entity_id, details, created_at) VALUES(?,?,?,?,?,?)",
        (email, action, entity, str(entity_id), details, datetime.now().isoformat())
    )


def seed_demo():
    if not query_one("SELECT id FROM users LIMIT 1"):
        p_hash, salt = password_hash(os.getenv("ADMIN_PASSWORD", "Admin@123"))
        execute(
            "INSERT INTO users(name,email,password_hash,salt,role,active,created_at) VALUES(?,?,?,?,?,?,?)",
            ("Administrador Melo Alves", "admin@meloalves.local", p_hash, salt, "Administrador", 1, datetime.now().isoformat())
        )

    if not query_one("SELECT id FROM clients LIMIT 1"):
        cid = execute(
            """INSERT INTO clients(legal_name,trade_name,cnpj,tax_regime,annual_revenue,sector,erp,accountant,status,created_at)
               VALUES(?,?,?,?,?,?,?,?,?,?)""",
            ("Empresa Brasil Serviços Integrados Ltda.", "Brasil Serviços", "00.000.000/0001-00",
             "Lucro Presumido", 25_000_000, "Facilities e contratos públicos", "ERP Exemplo",
             "Contabilidade Demonstração", "Ativo", datetime.now().isoformat())
        )
        execute(
            """INSERT INTO companies(client_id,legal_name,cnpj,company_type,tax_regime,state,city,created_at)
               VALUES(?,?,?,?,?,?,?,?)""",
            (cid, "Empresa Brasil Serviços Integrados Ltda.", "00.000.000/0001-00", "Matriz",
             "Lucro Presumido", "DF", "Brasília", datetime.now().isoformat())
        )
        pid = execute(
            """INSERT INTO projects(client_id,name,project_type,status,responsible,start_date,due_date,description,created_at)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            (cid, "Diagnóstico de Transição Tributária 360", "Diagnóstico", "Em andamento",
             "Rafael de Melo Alves", date.today().isoformat(), (date.today()+timedelta(days=45)).isoformat(),
             "Projeto demonstrativo para validação da metodologia.", datetime.now().isoformat())
        )
        execute(
            """INSERT INTO risks(client_id,project_id,title,category,description,cause,consequence,probability,impact,level,
               monthly_value,annual_value,evidence,legal_basis,treatment,responsible,due_date,status,created_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (cid, pid, "Contratos sem cláusula adequada de mudança tributária", "Contrato público",
             "Contratos de longo prazo não possuem mecanismo detalhado para demonstrar impacto líquido.",
             "Modelo contratual anterior à reforma", "Risco de erosão de margem e discussão administrativa",
             4, 5, "Crítico", 45_000, 540_000, "Amostra de contratos", "Análise preliminar pendente",
             "Mapear contratos, reconstruir planilha e preparar matriz de impacto", "Rafael",
             (date.today()+timedelta(days=30)).isoformat(), "Aberto", datetime.now().isoformat())
        )
        execute(
            """INSERT INTO tasks(client_id,project_id,title,description,responsible,priority,due_date,status,created_at)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            (cid, pid, "Receber DRE mensalizada", "Solicitar últimos 12 meses ao contador.",
             "Contabilidade", "Alta", (date.today()+timedelta(days=7)).isoformat(),
             "Aguardando contador", datetime.now().isoformat())
        )
        contract_id = execute(
            """INSERT INTO public_contracts(client_id,public_body,contract_number,object,original_value,current_value,
               start_date,end_date,risk_matrix,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (cid, "Órgão Público Demonstrativo", "001/2026", "Serviços continuados de facilities",
             8_000_000, 8_000_000, date.today().isoformat(),
             (date.today()+timedelta(days=730)).isoformat(), "Matriz em análise", "Ativo",
             datetime.now().isoformat())
        )
        execute(
            """INSERT INTO rebalancing_cases(client_id,public_contract_id,event_description,event_date,gross_impact,
               credits_effect,net_impact,amount_claimed,amount_recognized,amount_received,stage,probability,status,notes,created_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (cid, contract_id, "Impacto tributário demonstrativo", date.today().isoformat(),
             500_000, 160_000, 340_000, 340_000, 0, 0, "Análise documental",
             "Em avaliação", "Em andamento", "Valores fictícios.", datetime.now().isoformat())
        )


init_db()
seed_demo()


# =========================================================
# UTILIDADES
# =========================================================

def brl(value):
    value = float(value or 0)
    formatted = f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {formatted}"


def format_date(value):
    if not value:
        return "-"
    try:
        return datetime.fromisoformat(str(value)).strftime("%d/%m/%Y")
    except Exception:
        return str(value)


def dataframe(rows):
    return pd.DataFrame(rows) if rows else pd.DataFrame()


def client_options():
    clients = query("SELECT id, legal_name, trade_name FROM clients ORDER BY legal_name")
    return {f"{c['trade_name'] or c['legal_name']} — {c['legal_name']}": c["id"] for c in clients}


def select_client(label="Cliente", key=None):
    options = client_options()
    if not options:
        st.warning("Cadastre um cliente primeiro.")
        return None
    selected = st.selectbox(label, list(options.keys()), key=key)
    return options[selected]


def page_header(title, subtitle=""):
    st.markdown(f'<p class="main-title">{title}</p>', unsafe_allow_html=True)
    if subtitle:
        st.markdown(f'<p class="sub-title">{subtitle}</p>', unsafe_allow_html=True)
    st.divider()


def risk_css(level):
    return {
        "Crítico": "risk-critical",
        "Alto": "risk-high",
        "Médio": "risk-medium",
        "Baixo": "risk-low",
        "Oportunidade": "risk-opportunity"
    }.get(level, "")


def generate_pdf_report(client_id: int):
    client = query_one("SELECT * FROM clients WHERE id=?", (client_id,))
    risks = query("SELECT * FROM risks WHERE client_id=? ORDER BY impact DESC, probability DESC", (client_id,))
    tasks = query("SELECT * FROM tasks WHERE client_id=? ORDER BY due_date", (client_id,))
    credits = query("SELECT * FROM tax_credits WHERE client_id=?", (client_id,))
    contracts = query("SELECT * FROM public_contracts WHERE client_id=?", (client_id,))

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=1.5*cm, leftMargin=1.5*cm,
                            topMargin=1.5*cm, bottomMargin=1.5*cm)
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="CenterTitle", parent=styles["Title"], alignment=TA_CENTER, fontSize=18))
    styles.add(ParagraphStyle(name="Small", parent=styles["BodyText"], fontSize=8, leading=10))
    story = [
        Paragraph("MELO ALVES TAX GOVERNANCE", styles["CenterTitle"]),
        Spacer(1, 8),
        Paragraph("Relatório Executivo de Governança Tributária", styles["Heading2"]),
        Spacer(1, 12),
        Paragraph(f"<b>Cliente:</b> {client['legal_name']}", styles["BodyText"]),
        Paragraph(f"<b>Regime tributário:</b> {client.get('tax_regime') or '-'}", styles["BodyText"]),
        Paragraph(f"<b>Data:</b> {datetime.now().strftime('%d/%m/%Y %H:%M')}", styles["BodyText"]),
        Spacer(1, 16),
        Paragraph("Aviso", styles["Heading2"]),
        Paragraph(
            "Documento gerencial preliminar. As conclusões jurídicas, contábeis e financeiras "
            "dependem de validação profissional e da qualidade dos dados fornecidos.", styles["BodyText"]
        ),
        PageBreak(),
        Paragraph("1. Sumário de riscos", styles["Heading1"]),
    ]

    if risks:
        data = [["Nível", "Risco", "Valor anual", "Status"]]
        for r in risks:
            data.append([r["level"], r["title"][:70], brl(r["annual_value"]), r["status"]])
        table = Table(data, colWidths=[2.3*cm, 9.2*cm, 3.1*cm, 2.6*cm])
        table.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#1d2939")),
            ("TEXTCOLOR", (0,0), (-1,0), colors.white),
            ("GRID", (0,0), (-1,-1), .3, colors.grey),
            ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
            ("FONTSIZE", (0,0), (-1,-1), 7),
            ("VALIGN", (0,0), (-1,-1), "TOP"),
            ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, colors.HexColor("#f9fafb")]),
        ]))
        story.append(table)
    else:
        story.append(Paragraph("Nenhum risco cadastrado.", styles["BodyText"]))

    story.extend([Spacer(1, 18), Paragraph("2. Créditos tributários", styles["Heading1"])])
    total_credit = sum(float(c["credit_value"] or 0) for c in credits)
    story.append(Paragraph(f"Total registrado: <b>{brl(total_credit)}</b>", styles["BodyText"]))

    story.extend([Spacer(1, 18), Paragraph("3. Contratos públicos", styles["Heading1"])])
    story.append(Paragraph(f"Contratos cadastrados: <b>{len(contracts)}</b>", styles["BodyText"]))

    story.extend([Spacer(1, 18), Paragraph("4. Plano de ação", styles["Heading1"])])
    if tasks:
        data = [["Tarefa", "Responsável", "Prazo", "Status"]]
        for t in tasks:
            data.append([t["title"][:65], t["responsible"] or "-", format_date(t["due_date"]), t["status"]])
        table = Table(data, colWidths=[8*cm, 3.4*cm, 2.5*cm, 3.3*cm])
        table.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#1d2939")),
            ("TEXTCOLOR", (0,0), (-1,0), colors.white),
            ("GRID", (0,0), (-1,-1), .3, colors.grey),
            ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
            ("FONTSIZE", (0,0), (-1,-1), 7),
            ("VALIGN", (0,0), (-1,-1), "TOP"),
        ]))
        story.append(table)
    else:
        story.append(Paragraph("Nenhuma tarefa cadastrada.", styles["BodyText"]))

    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()


def ask_kimi(system_prompt: str, user_prompt: str):
    api_url = os.getenv("KIMI_API_URL", "").strip()
    api_key = os.getenv("KIMI_API_KEY", "").strip()
    model = os.getenv("KIMI_MODEL", "kimi").strip()

    if not api_url or not api_key:
        raise RuntimeError(
            "Configure KIMI_API_URL e KIMI_API_KEY nas variáveis de ambiente. "
            "A integração foi deixada genérica para aceitar endpoint compatível com OpenAI."
        )

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.2,
    }
    response = requests.post(
        api_url,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=payload,
        timeout=120,
    )
    response.raise_for_status()
    data = response.json()
    return data["choices"][0]["message"]["content"], model


# =========================================================
# AUTENTICAÇÃO
# =========================================================

def login_page():
    col1, col2, col3 = st.columns([1, 1.2, 1])
    with col2:
        st.markdown("<br><br>", unsafe_allow_html=True)
        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.markdown("## ⚖️ Melo Alves")
        st.caption("Tax Governance — acesso restrito")
        with st.form("login"):
            email = st.text_input("E-mail", value="admin@meloalves.local")
            password = st.text_input("Senha", type="password", value="Admin@123")
            submitted = st.form_submit_button("Entrar", use_container_width=True)
        if submitted:
            user = query_one("SELECT * FROM users WHERE lower(email)=lower(?) AND active=1", (email.strip(),))
            if user and verify_password(password, user["password_hash"], user["salt"]):
                st.session_state.user = {
                    "id": user["id"], "name": user["name"],
                    "email": user["email"], "role": user["role"]
                }
                log_action("LOGIN", "users", user["id"])
                st.rerun()
            else:
                st.error("E-mail ou senha inválidos.")
        st.info("Acesso inicial: admin@meloalves.local / Admin@123")
        st.markdown("</div>", unsafe_allow_html=True)


if "user" not in st.session_state:
    login_page()
    st.stop()


# =========================================================
# NAVEGAÇÃO
# =========================================================

with st.sidebar:
    st.markdown("## ⚖️ MELO ALVES")
    st.caption("Tax Governance")
    st.markdown(f"**{st.session_state.user['name']}**")
    st.caption(st.session_state.user["role"])
    st.divider()

    page = st.radio(
        "Navegação",
        [
            "Dashboard",
            "Clientes e empresas",
            "Conflito de interesses",
            "Projetos e diagnósticos",
            "Matriz de riscos",
            "Plano de ação",
            "Documentos",
            "Créditos tributários",
            "Contratos públicos",
            "Reequilíbrio",
            "Ciclo mensal",
            "Reuniões",
            "Relatórios",
            "Assistente de IA",
            "Usuários",
            "Auditoria",
            "Configurações",
        ],
        label_visibility="collapsed"
    )
    st.divider()
    if st.button("Sair", use_container_width=True):
        log_action("LOGOUT")
        st.session_state.clear()
        st.rerun()


# =========================================================
# DASHBOARD
# =========================================================

if page == "Dashboard":
    page_header("Dashboard executivo", "Visão consolidada da operação tributária e jurídica.")

    clients = query("SELECT * FROM clients WHERE status='Ativo'")
    projects = query("SELECT * FROM projects WHERE status NOT IN ('Concluído','Suspenso')")
    risks = query("SELECT * FROM risks WHERE status!='Concluído'")
    tasks = query("SELECT * FROM tasks WHERE status NOT IN ('Concluída','Cancelada')")
    credits = query("SELECT * FROM tax_credits")
    rebalance = query("SELECT * FROM rebalancing_cases")

    critical = sum(1 for r in risks if r["level"] == "Crítico")
    annual_exposure = sum(float(r["annual_value"] or 0) for r in risks)
    credit_total = sum(float(c["credit_value"] or 0) for c in credits)
    amount_claimed = sum(float(r["amount_claimed"] or 0) for r in rebalance)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Clientes ativos", len(clients))
    c2.metric("Projetos em andamento", len(projects))
    c3.metric("Riscos críticos", critical)
    c4.metric("Tarefas abertas", len(tasks))

    c1, c2, c3 = st.columns(3)
    c1.metric("Exposição anual cadastrada", brl(annual_exposure))
    c2.metric("Créditos em governança", brl(credit_total))
    c3.metric("Reequilíbrios pleiteados", brl(amount_claimed))

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Riscos por nível")
        if risks:
            risk_df = dataframe(risks)
            chart = risk_df.groupby("level").size().reset_index(name="quantidade")
            st.plotly_chart(px.bar(chart, x="level", y="quantidade", text="quantidade"), use_container_width=True)
        else:
            st.info("Nenhum risco cadastrado.")

    with col2:
        st.subheader("Tarefas por status")
        if tasks:
            task_df = dataframe(tasks)
            chart = task_df.groupby("status").size().reset_index(name="quantidade")
            st.plotly_chart(px.pie(chart, names="status", values="quantidade", hole=.45), use_container_width=True)
        else:
            st.info("Nenhuma tarefa aberta.")

    st.subheader("Prazos próximos")
    next_tasks = query("""
        SELECT t.*, c.trade_name, c.legal_name
        FROM tasks t JOIN clients c ON c.id=t.client_id
        WHERE t.status NOT IN ('Concluída','Cancelada') AND t.due_date IS NOT NULL
        ORDER BY t.due_date LIMIT 10
    """)
    if next_tasks:
        df = dataframe(next_tasks)[["title","trade_name","responsible","priority","due_date","status"]]
        df.columns = ["Tarefa","Cliente","Responsável","Prioridade","Prazo","Status"]
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("Nenhum prazo próximo.")


# =========================================================
# CLIENTES
# =========================================================

elif page == "Clientes e empresas":
    page_header("Clientes e empresas", "Cadastro de grupos, empresas, CNPJs e responsáveis.")

    tab1, tab2 = st.tabs(["Clientes", "Empresas e estabelecimentos"])

    with tab1:
        with st.expander("Cadastrar cliente", expanded=False):
            with st.form("new_client"):
                c1, c2 = st.columns(2)
                legal_name = c1.text_input("Razão social *")
                trade_name = c2.text_input("Nome fantasia")
                cnpj = c1.text_input("CNPJ")
                tax_regime = c2.selectbox("Regime tributário", ["Simples Nacional", "Lucro Presumido", "Lucro Real", "Outro"])
                annual_revenue = c1.number_input("Faturamento anual", min_value=0.0, step=10000.0)
                sector = c2.text_input("Setor")
                erp = c1.text_input("ERP")
                accountant = c2.text_input("Contador/escritório contábil")
                if st.form_submit_button("Cadastrar cliente"):
                    if not legal_name.strip():
                        st.error("Informe a razão social.")
                    else:
                        cid = execute(
                            """INSERT INTO clients(legal_name,trade_name,cnpj,tax_regime,annual_revenue,sector,erp,accountant,status,created_at)
                               VALUES(?,?,?,?,?,?,?,?,?,?)""",
                            (legal_name, trade_name, cnpj, tax_regime, annual_revenue, sector, erp, accountant,
                             "Ativo", datetime.now().isoformat())
                        )
                        log_action("CRIAR", "clients", cid, legal_name)
                        st.success("Cliente cadastrado.")
                        st.rerun()

        rows = query("SELECT * FROM clients ORDER BY legal_name")
        if rows:
            df = dataframe(rows)[["id","legal_name","trade_name","cnpj","tax_regime","annual_revenue","sector","status"]]
            df["annual_revenue"] = df["annual_revenue"].apply(brl)
            df.columns = ["ID","Razão social","Nome fantasia","CNPJ","Regime","Faturamento anual","Setor","Status"]
            st.dataframe(df, use_container_width=True, hide_index=True)

            edit_id = st.selectbox("Selecionar cliente para editar", [r["id"] for r in rows],
                                   format_func=lambda x: next(r["legal_name"] for r in rows if r["id"] == x))
            selected = query_one("SELECT * FROM clients WHERE id=?", (edit_id,))
            with st.form("edit_client"):
                c1, c2 = st.columns(2)
                e_legal = c1.text_input("Razão social", value=selected["legal_name"])
                e_trade = c2.text_input("Nome fantasia", value=selected["trade_name"] or "")
                e_regime = c1.selectbox("Regime", ["Simples Nacional", "Lucro Presumido", "Lucro Real", "Outro"],
                                        index=["Simples Nacional", "Lucro Presumido", "Lucro Real", "Outro"].index(selected["tax_regime"]) if selected["tax_regime"] in ["Simples Nacional", "Lucro Presumido", "Lucro Real", "Outro"] else 3)
                e_status = c2.selectbox("Status", ["Ativo", "Inativo"], index=0 if selected["status"] == "Ativo" else 1)
                if st.form_submit_button("Salvar alterações"):
                    execute("UPDATE clients SET legal_name=?,trade_name=?,tax_regime=?,status=? WHERE id=?",
                            (e_legal, e_trade, e_regime, e_status, edit_id))
                    log_action("EDITAR", "clients", edit_id)
                    st.success("Alterações salvas.")
                    st.rerun()
        else:
            st.info("Nenhum cliente cadastrado.")

    with tab2:
        cid = select_client("Cliente da empresa", "company_client")
        if cid:
            with st.form("new_company"):
                c1, c2 = st.columns(2)
                legal_name = c1.text_input("Razão social da empresa *")
                cnpj = c2.text_input("CNPJ")
                company_type = c1.selectbox("Tipo", ["Matriz", "Filial", "Controlada", "Coligada"])
                tax_regime = c2.selectbox("Regime tributário", ["Simples Nacional", "Lucro Presumido", "Lucro Real", "Outro"])
                state = c1.text_input("UF")
                city = c2.text_input("Cidade")
                if st.form_submit_button("Cadastrar empresa"):
                    if legal_name.strip():
                        company_id = execute(
                            """INSERT INTO companies(client_id,legal_name,cnpj,company_type,tax_regime,state,city,created_at)
                               VALUES(?,?,?,?,?,?,?,?)""",
                            (cid, legal_name, cnpj, company_type, tax_regime, state, city, datetime.now().isoformat())
                        )
                        log_action("CRIAR", "companies", company_id)
                        st.success("Empresa cadastrada.")
                        st.rerun()

            companies = query("SELECT * FROM companies WHERE client_id=? ORDER BY legal_name", (cid,))
            if companies:
                st.dataframe(dataframe(companies)[["legal_name","cnpj","company_type","tax_regime","state","city"]],
                             use_container_width=True, hide_index=True)


# =========================================================
# CONFLITO
# =========================================================

elif page == "Conflito de interesses":
    page_header("Conflito de interesses", "Triagem obrigatória antes da contratação.")

    with st.form("conflict"):
        c1, c2 = st.columns(2)
        client_name = c1.text_input("Potencial cliente *")
        cnpj = c2.text_input("CNPJ")
        related = c1.text_area("Sócios, empresas e partes relacionadas")
        bodies = c2.text_area("Órgãos públicos e autoridades relacionadas")
        description = st.text_area("Objeto da possível contratação")
        status = st.selectbox("Resultado", [
            "Em análise", "Sem conflito identificado", "Conflito potencial",
            "Conflito confirmado", "Contratação recusada", "Contratação aprovada com restrições"
        ])
        decision = st.text_area("Decisão e justificativa")
        responsible = st.text_input("Responsável", value=st.session_state.user["name"])
        if st.form_submit_button("Registrar análise"):
            if client_name.strip():
                rid = execute(
                    """INSERT INTO conflict_checks(client_name,cnpj,related_parties,public_bodies,description,status,decision,responsible,created_at)
                       VALUES(?,?,?,?,?,?,?,?,?)""",
                    (client_name, cnpj, related, bodies, description, status, decision, responsible, datetime.now().isoformat())
                )
                log_action("CRIAR", "conflict_checks", rid)
                st.success("Análise registrada.")
                st.rerun()

    rows = query("SELECT * FROM conflict_checks ORDER BY created_at DESC")
    if rows:
        df = dataframe(rows)[["client_name","cnpj","status","responsible","created_at"]]
        df.columns = ["Potencial cliente","CNPJ","Status","Responsável","Criado em"]
        st.dataframe(df, use_container_width=True, hide_index=True)


# =========================================================
# PROJETOS
# =========================================================

elif page == "Projetos e diagnósticos":
    page_header("Projetos e diagnósticos", "Diagnóstico 360, consulta, contencioso e projetos especiais.")

    cid = select_client()
    if cid:
        with st.expander("Criar projeto"):
            with st.form("new_project"):
                name = st.text_input("Nome do projeto *")
                c1, c2 = st.columns(2)
                project_type = c1.selectbox("Tipo", [
                    "Diagnóstico", "Programa mensal", "Reequilíbrio", "Consulta formal",
                    "Contencioso administrativo", "Contencioso judicial", "Outro"
                ])
                status = c2.selectbox("Status", PROJECT_STATUS)
                responsible = c1.text_input("Responsável", value=st.session_state.user["name"])
                start_date = c2.date_input("Início", value=date.today())
                due_date = c1.date_input("Prazo", value=date.today()+timedelta(days=45))
                description = st.text_area("Descrição")
                if st.form_submit_button("Criar projeto"):
                    if name.strip():
                        pid = execute(
                            """INSERT INTO projects(client_id,name,project_type,status,responsible,start_date,due_date,description,created_at)
                               VALUES(?,?,?,?,?,?,?,?,?)""",
                            (cid, name, project_type, status, responsible, start_date.isoformat(),
                             due_date.isoformat(), description, datetime.now().isoformat())
                        )
                        log_action("CRIAR", "projects", pid)
                        st.success("Projeto criado.")
                        st.rerun()

        projects = query("SELECT * FROM projects WHERE client_id=? ORDER BY created_at DESC", (cid,))
        if projects:
            df = dataframe(projects)[["id","name","project_type","status","responsible","start_date","due_date"]]
            df.columns = ["ID","Projeto","Tipo","Status","Responsável","Início","Prazo"]
            st.dataframe(df, use_container_width=True, hide_index=True)
        else:
            st.info("Nenhum projeto cadastrado.")


# =========================================================
# RISCOS
# =========================================================

elif page == "Matriz de riscos":
    page_header("Matriz de riscos e oportunidades", "Probabilidade, impacto, valor e plano de tratamento.")

    cid = select_client()
    if cid:
        projects = query("SELECT id,name FROM projects WHERE client_id=?", (cid,))
        project_map = {"Sem projeto": None, **{p["name"]: p["id"] for p in projects}}

        with st.expander("Cadastrar risco ou oportunidade"):
            with st.form("new_risk"):
                title = st.text_input("Título *")
                c1, c2, c3 = st.columns(3)
                project_name = c1.selectbox("Projeto", list(project_map.keys()))
                category = c2.selectbox("Categoria", [
                    "Conformidade", "Crédito", "Caixa", "Preço", "Contrato público",
                    "Contrato privado", "Obrigação acessória", "Autuação", "Processo",
                    "Fornecedor", "Documentação", "Sistema", "Proteção de dados", "Oportunidade legítima"
                ])
                level = c3.selectbox("Nível", RISK_LEVELS)
                description = st.text_area("Descrição")
                cause = st.text_area("Causa")
                consequence = st.text_area("Consequência")
                probability = c1.slider("Probabilidade", 1, 5, 3)
                impact = c2.slider("Impacto", 1, 5, 3)
                monthly_value = c1.number_input("Valor mensal", min_value=0.0)
                annual_value = c2.number_input("Valor anual", min_value=0.0)
                evidence = st.text_area("Evidências")
                legal_basis = st.text_area("Fundamento preliminar")
                treatment = st.text_area("Tratamento recomendado")
                responsible = c1.text_input("Responsável")
                due_date = c2.date_input("Prazo", value=date.today()+timedelta(days=30))
                if st.form_submit_button("Cadastrar risco"):
                    if title.strip():
                        rid = execute(
                            """INSERT INTO risks(client_id,project_id,title,category,description,cause,consequence,probability,
                               impact,level,monthly_value,annual_value,evidence,legal_basis,treatment,responsible,due_date,status,created_at)
                               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                            (cid, project_map[project_name], title, category, description, cause, consequence,
                             probability, impact, level, monthly_value, annual_value, evidence, legal_basis,
                             treatment, responsible, due_date.isoformat(), "Aberto", datetime.now().isoformat())
                        )
                        log_action("CRIAR", "risks", rid)
                        st.success("Risco cadastrado.")
                        st.rerun()

        risks = query("SELECT * FROM risks WHERE client_id=? ORDER BY impact DESC, probability DESC", (cid,))
        if risks:
            c1, c2, c3 = st.columns(3)
            c1.metric("Itens cadastrados", len(risks))
            c2.metric("Exposição anual", brl(sum(float(r["annual_value"] or 0) for r in risks)))
            c3.metric("Críticos", sum(1 for r in risks if r["level"] == "Crítico"))

            matrix = dataframe(risks)
            fig = px.scatter(
                matrix, x="probability", y="impact", size="annual_value", hover_name="title",
                symbol="level", range_x=[0.5,5.5], range_y=[0.5,5.5],
                labels={"probability":"Probabilidade","impact":"Impacto","level":"Nível"}
            )
            st.plotly_chart(fig, use_container_width=True)

            for r in risks:
                st.markdown(
                    f"""<div class="card {risk_css(r['level'])}">
                    <b>{r['level']} — {r['title']}</b><br>
                    <span class="small-muted">{r['category'] or '-'} | Exposição anual: {brl(r['annual_value'])}
                    | Responsável: {r['responsible'] or '-'}</span><br><br>
                    {r['description'] or ''}
                    </div>""",
                    unsafe_allow_html=True
                )
        else:
            st.info("Nenhum risco cadastrado.")


# =========================================================
# TAREFAS
# =========================================================

elif page == "Plano de ação":
    page_header("Plano de ação", "Tarefas, responsáveis, prazos e dependências.")

    cid = select_client()
    if cid:
        projects = query("SELECT id,name FROM projects WHERE client_id=?", (cid,))
        project_map = {"Sem projeto": None, **{p["name"]: p["id"] for p in projects}}
        with st.expander("Nova tarefa"):
            with st.form("new_task"):
                title = st.text_input("Tarefa *")
                description = st.text_area("Descrição")
                c1, c2, c3 = st.columns(3)
                project_name = c1.selectbox("Projeto", list(project_map.keys()))
                responsible = c2.text_input("Responsável")
                priority = c3.selectbox("Prioridade", ["Crítica", "Alta", "Média", "Baixa"])
                due_date = c1.date_input("Prazo", value=date.today()+timedelta(days=7))
                status = c2.selectbox("Status", TASK_STATUS)
                if st.form_submit_button("Criar tarefa"):
                    if title.strip():
                        tid = execute(
                            """INSERT INTO tasks(client_id,project_id,title,description,responsible,priority,due_date,status,created_at)
                               VALUES(?,?,?,?,?,?,?,?,?)""",
                            (cid, project_map[project_name], title, description, responsible, priority,
                             due_date.isoformat(), status, datetime.now().isoformat())
                        )
                        log_action("CRIAR", "tasks", tid)
                        st.success("Tarefa criada.")
                        st.rerun()

        tasks = query("SELECT * FROM tasks WHERE client_id=? ORDER BY due_date", (cid,))
        if tasks:
            df = dataframe(tasks)[["id","title","responsible","priority","due_date","status"]]
            df.columns = ["ID","Tarefa","Responsável","Prioridade","Prazo","Status"]
            st.dataframe(df, use_container_width=True, hide_index=True)

            task_id = st.selectbox("Atualizar tarefa", [t["id"] for t in tasks],
                                   format_func=lambda x: next(t["title"] for t in tasks if t["id"] == x))
            task = query_one("SELECT * FROM tasks WHERE id=?", (task_id,))
            new_status = st.selectbox("Novo status", TASK_STATUS, index=TASK_STATUS.index(task["status"]))
            if st.button("Atualizar status"):
                execute("UPDATE tasks SET status=? WHERE id=?", (new_status, task_id))
                log_action("ATUALIZAR_STATUS", "tasks", task_id, new_status)
                st.success("Status atualizado.")
                st.rerun()


# =========================================================
# DOCUMENTOS
# =========================================================

elif page == "Documentos":
    page_header("Data room e documentos", "Armazenamento segregado, hash e classificação.")

    cid = select_client()
    if cid:
        with st.form("upload_form", clear_on_submit=True):
            files = st.file_uploader("Enviar documentos", accept_multiple_files=True)
            c1, c2 = st.columns(2)
            category = c1.selectbox("Categoria", [
                "Societário", "Fiscal", "Contábil", "Financeiro", "Operacional",
                "Contrato privado", "Contrato público", "Contencioso", "Crédito",
                "Ressarcimento", "Parecer", "Relatório", "Reunião", "Evidência"
            ])
            subcategory = c2.text_input("Subcategoria")
            period = c1.text_input("Período de referência")
            status = c2.selectbox("Status", DOCUMENT_STATUS)
            notes = st.text_area("Observações")
            if st.form_submit_button("Salvar documentos"):
                if files:
                    client_dir = UPLOAD_DIR / str(cid)
                    client_dir.mkdir(parents=True, exist_ok=True)
                    for uploaded in files:
                        content = uploaded.getvalue()
                        digest = hashlib.sha256(content).hexdigest()
                        safe_name = f"{datetime.now().strftime('%Y%m%d%H%M%S%f')}_{Path(uploaded.name).name}"
                        path = client_dir / safe_name
                        path.write_bytes(content)
                        did = execute(
                            """INSERT INTO documents(client_id,category,subcategory,original_name,stored_path,period,status,
                               hash_sha256,notes,uploaded_by,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                            (cid, category, subcategory, uploaded.name, str(path), period, status,
                             digest, notes, st.session_state.user["email"], datetime.now().isoformat())
                        )
                        log_action("UPLOAD", "documents", did, uploaded.name)
                    st.success(f"{len(files)} documento(s) salvo(s).")
                    st.rerun()

        docs = query("SELECT * FROM documents WHERE client_id=? ORDER BY created_at DESC", (cid,))
        if docs:
            df = dataframe(docs)[["original_name","category","subcategory","period","status","uploaded_by","created_at"]]
            df.columns = ["Arquivo","Categoria","Subcategoria","Período","Status","Enviado por","Data"]
            st.dataframe(df, use_container_width=True, hide_index=True)

            selected_id = st.selectbox("Documento para download", [d["id"] for d in docs],
                                       format_func=lambda x: next(d["original_name"] for d in docs if d["id"] == x))
            doc = query_one("SELECT * FROM documents WHERE id=?", (selected_id,))
            path = Path(doc["stored_path"])
            if path.exists():
                st.download_button("Baixar documento", path.read_bytes(), file_name=doc["original_name"])
        else:
            st.info("Nenhum documento enviado.")


# =========================================================
# CRÉDITOS
# =========================================================

elif page == "Créditos tributários":
    page_header("Governança de créditos", "Origem, conciliação, validação e utilização.")

    cid = select_client()
    if cid:
        with st.expander("Cadastrar crédito"):
            with st.form("new_credit"):
                c1, c2 = st.columns(2)
                tax_name = c1.text_input("Tributo")
                period = c2.text_input("Período")
                origin = c1.text_input("Origem")
                supplier = c2.text_input("Fornecedor")
                operation_value = c1.number_input("Valor da operação", min_value=0.0)
                credit_value = c2.number_input("Valor do crédito", min_value=0.0)
                legal_basis = st.text_area("Fundamento preliminar")
                payment_status = c1.selectbox("Situação do pagamento", ["Não verificado", "Comprovado", "Pendente", "Divergente"])
                status = c2.selectbox("Status", CREDIT_STATUS)
                notes = st.text_area("Observações")
                if st.form_submit_button("Cadastrar crédito"):
                    credit_id = execute(
                        """INSERT INTO tax_credits(client_id,tax_name,period,origin,supplier,operation_value,credit_value,
                           legal_basis,payment_status,status,notes,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (cid, tax_name, period, origin, supplier, operation_value, credit_value,
                         legal_basis, payment_status, status, notes, datetime.now().isoformat())
                    )
                    log_action("CRIAR", "tax_credits", credit_id)
                    st.success("Crédito cadastrado.")
                    st.rerun()

        rows = query("SELECT * FROM tax_credits WHERE client_id=? ORDER BY created_at DESC", (cid,))
        if rows:
            c1, c2 = st.columns(2)
            c1.metric("Créditos registrados", brl(sum(float(r["credit_value"] or 0) for r in rows)))
            c2.metric("Operações relacionadas", brl(sum(float(r["operation_value"] or 0) for r in rows)))
            df = dataframe(rows)[["tax_name","period","origin","supplier","credit_value","payment_status","status","accounting_validation","legal_validation"]]
            df["credit_value"] = df["credit_value"].apply(brl)
            df.columns = ["Tributo","Período","Origem","Fornecedor","Crédito","Pagamento","Status","Validação contábil","Validação jurídica"]
            st.dataframe(df, use_container_width=True, hide_index=True)
            st.warning("A inclusão no sistema não significa aprovação jurídica para utilização do crédito.")


# =========================================================
# CONTRATOS PÚBLICOS
# =========================================================

elif page == "Contratos públicos":
    page_header("Contratos públicos", "Cadastro, valores, vigência e matriz de riscos.")

    cid = select_client()
    if cid:
        with st.expander("Cadastrar contrato"):
            with st.form("new_public_contract"):
                c1, c2 = st.columns(2)
                public_body = c1.text_input("Órgão ou entidade *")
                contract_number = c2.text_input("Número do contrato")
                object_text = st.text_area("Objeto")
                original_value = c1.number_input("Valor original", min_value=0.0)
                current_value = c2.number_input("Valor atual", min_value=0.0)
                start_date = c1.date_input("Início", value=date.today())
                end_date = c2.date_input("Término", value=date.today()+timedelta(days=365))
                risk_matrix = st.text_area("Matriz de riscos")
                status = st.selectbox("Status", ["Ativo", "Suspenso", "Encerrado", "Em renovação"])
                if st.form_submit_button("Cadastrar contrato"):
                    if public_body.strip():
                        contract_id = execute(
                            """INSERT INTO public_contracts(client_id,public_body,contract_number,object,original_value,
                               current_value,start_date,end_date,risk_matrix,status,created_at)
                               VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                            (cid, public_body, contract_number, object_text, original_value, current_value,
                             start_date.isoformat(), end_date.isoformat(), risk_matrix, status, datetime.now().isoformat())
                        )
                        log_action("CRIAR", "public_contracts", contract_id)
                        st.success("Contrato cadastrado.")
                        st.rerun()

        rows = query("SELECT * FROM public_contracts WHERE client_id=? ORDER BY created_at DESC", (cid,))
        if rows:
            df = dataframe(rows)[["public_body","contract_number","object","original_value","current_value","start_date","end_date","status"]]
            df["original_value"] = df["original_value"].apply(brl)
            df["current_value"] = df["current_value"].apply(brl)
            df.columns = ["Órgão","Contrato","Objeto","Valor original","Valor atual","Início","Término","Status"]
            st.dataframe(df, use_container_width=True, hide_index=True)


# =========================================================
# REEQUILÍBRIO
# =========================================================

elif page == "Reequilíbrio":
    page_header("Reequilíbrio econômico-financeiro", "Demonstração analítica do impacto líquido por contrato.")

    cid = select_client()
    if cid:
        contracts = query("SELECT id,public_body,contract_number FROM public_contracts WHERE client_id=?", (cid,))
        contract_map = {"Sem vínculo": None, **{f"{c['public_body']} — {c['contract_number']}": c["id"] for c in contracts}}
        with st.expander("Novo caso de reequilíbrio"):
            with st.form("new_rebalance"):
                contract_label = st.selectbox("Contrato", list(contract_map.keys()))
                event_description = st.text_area("Evento tributário ou econômico *")
                event_date = st.date_input("Data do evento", value=date.today())
                c1, c2, c3 = st.columns(3)
                gross = c1.number_input("Impacto bruto", min_value=0.0)
                credits_effect = c2.number_input("Efeito dos créditos", min_value=0.0)
                net = gross - credits_effect
                c3.metric("Impacto líquido calculado", brl(net))
                claimed = c1.number_input("Valor pleiteado", min_value=0.0, value=float(net))
                recognized = c2.number_input("Valor reconhecido", min_value=0.0)
                received = c3.number_input("Valor recebido", min_value=0.0)
                stage = c1.selectbox("Etapa", [
                    "Triagem", "Coleta documental", "Reconstrução da proposta", "Memória de cálculo",
                    "Análise jurídica", "Análise contábil", "Requerimento", "Protocolado",
                    "Diligência", "Decisão", "Recurso", "Negociação", "Judicial"
                ])
                probability = c2.selectbox("Avaliação interna", ["Em avaliação", "Baixa", "Média", "Alta"])
                status = c3.selectbox("Status", ["Em andamento", "Aguardando cliente", "Aguardando órgão", "Concluído", "Suspenso"])
                notes = st.text_area("Observações")
                if st.form_submit_button("Cadastrar caso"):
                    if event_description.strip():
                        rid = execute(
                            """INSERT INTO rebalancing_cases(client_id,public_contract_id,event_description,event_date,
                               gross_impact,credits_effect,net_impact,amount_claimed,amount_recognized,amount_received,
                               stage,probability,status,notes,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                            (cid, contract_map[contract_label], event_description, event_date.isoformat(), gross,
                             credits_effect, net, claimed, recognized, received, stage, probability,
                             status, notes, datetime.now().isoformat())
                        )
                        log_action("CRIAR", "rebalancing_cases", rid)
                        st.success("Caso cadastrado.")
                        st.rerun()

        rows = query("SELECT * FROM rebalancing_cases WHERE client_id=? ORDER BY created_at DESC", (cid,))
        if rows:
            c1, c2, c3 = st.columns(3)
            c1.metric("Pleiteado", brl(sum(float(r["amount_claimed"] or 0) for r in rows)))
            c2.metric("Reconhecido", brl(sum(float(r["amount_recognized"] or 0) for r in rows)))
            c3.metric("Recebido", brl(sum(float(r["amount_received"] or 0) for r in rows)))
            df = dataframe(rows)[["event_description","gross_impact","credits_effect","net_impact","amount_claimed","stage","probability","status"]]
            for col in ["gross_impact","credits_effect","net_impact","amount_claimed"]:
                df[col] = df[col].apply(brl)
            df.columns = ["Evento","Impacto bruto","Créditos","Impacto líquido","Pleiteado","Etapa","Avaliação","Status"]
            st.dataframe(df, use_container_width=True, hide_index=True)
            st.info("A mudança tributária não assegura automaticamente o reequilíbrio. O impacto deve ser efetivo, líquido e documentalmente comprovado.")


# =========================================================
# CICLO MENSAL
# =========================================================

elif page == "Ciclo mensal":
    page_header("Programa de Proteção da Liquidez Tributária", "Ciclo mensal estruturado nos cinco pilares.")

    cid = select_client()
    if cid:
        reference = st.text_input("Mês de referência", value=date.today().strftime("%Y-%m"))
        existing = query_one("SELECT * FROM monthly_cycles WHERE client_id=? AND reference_month=?", (cid, reference))
        with st.form("monthly_cycle"):
            documentary = st.text_area("Pilar 1 — Conformidade documental", value=(existing or {}).get("documentary_compliance", ""))
            credits = st.text_area("Pilar 2 — Governança de créditos", value=(existing or {}).get("credit_governance", ""))
            liquidity = st.text_area("Pilar 3 — Liquidez e fluxo de caixa", value=(existing or {}).get("liquidity", ""))
            contracts = st.text_area("Pilar 4 — Contratos e pricing", value=(existing or {}).get("contracts_pricing", ""))
            litigation = st.text_area("Pilar 5 — Contencioso e prova", value=(existing or {}).get("litigation_evidence", ""))
            summary = st.text_area("Sumário executivo", value=(existing or {}).get("executive_summary", ""))
            status = st.selectbox("Status", ["Em andamento", "Em revisão", "Aprovado", "Encerrado"],
                                  index=["Em andamento", "Em revisão", "Aprovado", "Encerrado"].index((existing or {}).get("status", "Em andamento")))
            if st.form_submit_button("Salvar ciclo mensal"):
                if existing:
                    execute(
                        """UPDATE monthly_cycles SET documentary_compliance=?,credit_governance=?,liquidity=?,
                           contracts_pricing=?,litigation_evidence=?,executive_summary=?,status=? WHERE id=?""",
                        (documentary, credits, liquidity, contracts, litigation, summary, status, existing["id"])
                    )
                    mid = existing["id"]
                else:
                    mid = execute(
                        """INSERT INTO monthly_cycles(client_id,reference_month,documentary_compliance,credit_governance,
                           liquidity,contracts_pricing,litigation_evidence,executive_summary,status,created_at)
                           VALUES(?,?,?,?,?,?,?,?,?,?)""",
                        (cid, reference, documentary, credits, liquidity, contracts, litigation, summary,
                         status, datetime.now().isoformat())
                    )
                log_action("SALVAR", "monthly_cycles", mid, reference)
                st.success("Ciclo mensal salvo.")
                st.rerun()


# =========================================================
# REUNIÕES
# =========================================================

elif page == "Reuniões":
    page_header("Reuniões e decisões", "Ata, responsáveis, prazos e aprovação.")

    cid = select_client()
    if cid:
        with st.expander("Registrar reunião"):
            with st.form("new_meeting"):
                meeting_date = st.date_input("Data", value=date.today())
                participants = st.text_input("Participantes")
                agenda = st.text_area("Pauta")
                summary = st.text_area("Resumo")
                decisions = st.text_area("Decisões")
                next_steps = st.text_area("Próximos passos")
                status = st.selectbox("Status", ["Minuta", "Em aprovação", "Aprovada"])
                if st.form_submit_button("Salvar reunião"):
                    mid = execute(
                        """INSERT INTO meetings(client_id,meeting_date,participants,agenda,summary,decisions,next_steps,status,created_at)
                           VALUES(?,?,?,?,?,?,?,?,?)""",
                        (cid, meeting_date.isoformat(), participants, agenda, summary,
                         decisions, next_steps, status, datetime.now().isoformat())
                    )
                    log_action("CRIAR", "meetings", mid)
                    st.success("Reunião registrada.")
                    st.rerun()

        rows = query("SELECT * FROM meetings WHERE client_id=? ORDER BY meeting_date DESC", (cid,))
        for r in rows:
            with st.expander(f"{format_date(r['meeting_date'])} — {r['status']}"):
                st.markdown(f"**Participantes:** {r['participants'] or '-'}")
                st.markdown(f"**Pauta:** {r['agenda'] or '-'}")
                st.markdown(f"**Resumo:** {r['summary'] or '-'}")
                st.markdown(f"**Decisões:** {r['decisions'] or '-'}")
                st.markdown(f"**Próximos passos:** {r['next_steps'] or '-'}")


# =========================================================
# RELATÓRIOS
# =========================================================

elif page == "Relatórios":
    page_header("Relatórios executivos", "Geração de PDF com riscos, créditos, contratos e plano de ação.")

    cid = select_client()
    if cid:
        client = query_one("SELECT * FROM clients WHERE id=?", (cid,))
        st.write(f"Relatório para **{client['legal_name']}**")
        if st.button("Gerar relatório executivo"):
            pdf = generate_pdf_report(cid)
            st.download_button(
                "Baixar PDF",
                data=pdf,
                file_name=f"relatorio_melo_alves_{cid}_{date.today().isoformat()}.pdf",
                mime="application/pdf",
            )


# =========================================================
# IA
# =========================================================

elif page == "Assistente de IA":
    page_header("Assistente de IA", "Apoio à organização, resumo e análise preliminar — com validação humana.")

    cid = select_client()
    if cid:
        client = query_one("SELECT * FROM clients WHERE id=?", (cid,))
        context_rows = query("SELECT title,level,description,evidence,legal_basis FROM risks WHERE client_id=?", (cid,))
        context = json.dumps(context_rows, ensure_ascii=False, indent=2)

        task_type = st.selectbox("Tipo de apoio", [
            "Resumo executivo", "Perguntas para o cliente", "Checklist documental",
            "Plano de ação preliminar", "Organização de fatos", "Análise preliminar de risco"
        ])
        prompt = st.text_area("Instrução", height=180, placeholder="Descreva o que precisa analisar.")
        st.caption("A IA utilizará somente o contexto cadastrado enviado nesta tela.")
        if st.button("Executar análise com Kimi"):
            if not prompt.strip():
                st.warning("Digite uma instrução.")
            else:
                system_prompt = f"""
Você é um assistente de apoio a um escritório tributário brasileiro.
Sua resposta é preliminar e não substitui advogado ou contador.
Não invente normas, decisões, fatos ou valores.
Indique lacunas, documentos necessários e necessidade de validação humana.
Cliente: {client['legal_name']}
Tarefa: {task_type}
Contexto de riscos cadastrados:
{context}
"""
                try:
                    with st.spinner("Processando..."):
                        response, model = ask_kimi(system_prompt, prompt)
                    st.markdown("### Resultado preliminar")
                    st.write(response)
                    iid = execute(
                        "INSERT INTO ai_interactions(user_email,client_id,prompt,response,model,created_at) VALUES(?,?,?,?,?,?)",
                        (st.session_state.user["email"], cid, prompt, response, model, datetime.now().isoformat())
                    )
                    log_action("IA", "ai_interactions", iid, task_type)
                    st.warning("Resultado gerado por IA. Exige revisão e aprovação profissional.")
                except Exception as exc:
                    st.error(str(exc))

        history = query("SELECT * FROM ai_interactions WHERE client_id=? ORDER BY created_at DESC LIMIT 10", (cid,))
        if history:
            st.subheader("Histórico")
            for item in history:
                with st.expander(f"{item['created_at'][:16]} — {item['model']}"):
                    st.markdown("**Pergunta**")
                    st.write(item["prompt"])
                    st.markdown("**Resposta**")
                    st.write(item["response"])


# =========================================================
# USUÁRIOS
# =========================================================

elif page == "Usuários":
    page_header("Usuários e permissões", "Acesso por papéis.")

    if st.session_state.user["role"] != "Administrador":
        st.error("Acesso restrito ao administrador.")
    else:
        with st.expander("Cadastrar usuário"):
            with st.form("new_user"):
                c1, c2 = st.columns(2)
                name = c1.text_input("Nome *")
                email = c2.text_input("E-mail *")
                password = c1.text_input("Senha provisória", type="password")
                role = c2.selectbox("Papel", [
                    "Administrador", "Advogado responsável", "Advogado revisor",
                    "Contador tributarista", "Analista fiscal", "Assistente",
                    "Cliente administrador", "Cliente diretoria", "Cliente contabilidade",
                    "Cliente fiscal/financeiro"
                ])
                if st.form_submit_button("Cadastrar usuário"):
                    if name.strip() and email.strip() and password:
                        p_hash, salt = password_hash(password)
                        try:
                            uid = execute(
                                "INSERT INTO users(name,email,password_hash,salt,role,active,created_at) VALUES(?,?,?,?,?,?,?)",
                                (name, email.lower().strip(), p_hash, salt, role, 1, datetime.now().isoformat())
                            )
                            log_action("CRIAR", "users", uid, email)
                            st.success("Usuário cadastrado.")
                            st.rerun()
                        except sqlite3.IntegrityError:
                            st.error("E-mail já cadastrado.")

        users = query("SELECT id,name,email,role,active,created_at FROM users ORDER BY name")
        st.dataframe(dataframe(users), use_container_width=True, hide_index=True)


# =========================================================
# AUDITORIA
# =========================================================

elif page == "Auditoria":
    page_header("Trilha de auditoria", "Registro de acessos e alterações.")

    if st.session_state.user["role"] != "Administrador":
        st.error("Acesso restrito ao administrador.")
    else:
        logs = query("SELECT * FROM audit_logs ORDER BY created_at DESC LIMIT 1000")
        if logs:
            st.dataframe(dataframe(logs), use_container_width=True, hide_index=True)


# =========================================================
# CONFIGURAÇÕES
# =========================================================

elif page == "Configurações":
    page_header("Configurações", "Parâmetros do ambiente e orientações de segurança.")

    st.subheader("Ambiente")
    st.code(f"""
DATABASE_PATH={DB_PATH}
UPLOAD_DIR={UPLOAD_DIR}
KIMI_API_URL={'configurado' if os.getenv('KIMI_API_URL') else 'não configurado'}
KIMI_API_KEY={'configurado' if os.getenv('KIMI_API_KEY') else 'não configurado'}
KIMI_MODEL={os.getenv('KIMI_MODEL', 'kimi')}
""")
    st.subheader("Avisos")
    st.warning(
        "Este MVP utiliza SQLite e armazenamento local. Para operação profissional multiusuário, "
        "migre para PostgreSQL e armazenamento S3/Supabase, implemente MFA, backups, antivírus de upload, "
        "políticas de retenção e revisão especializada de segurança."
    )
    st.info(
        "Troque imediatamente a senha inicial. Não utilize dados fiscais reais enquanto o ambiente "
        "não estiver configurado com controles de segurança e contratos adequados."
    )
