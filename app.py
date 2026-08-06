import os, io, re, json, hmac, hashlib, secrets, sqlite3
from pathlib import Path
from datetime import datetime
import requests, fitz, pandas as pd, streamlit as st
from docx import Document

APP='Melo Alves Tax Governance'
DB=Path(os.getenv('DATABASE_PATH','melo_alves_v2.db'))
UP=Path(os.getenv('UPLOAD_DIR','uploads')); UP.mkdir(exist_ok=True)
st.set_page_config(page_title=APP,page_icon='⚖️',layout='wide')
st.markdown('''<style>.block-container{padding-top:1.2rem}.card{border:1px solid #e4e7ec;border-radius:12px;padding:14px;background:white;margin-bottom:10px}.small{font-size:.82rem;color:#667085}</style>''',unsafe_allow_html=True)

def cx():
    c=sqlite3.connect(DB,check_same_thread=False); c.row_factory=sqlite3.Row; c.execute('PRAGMA foreign_keys=ON'); return c

def ex(sql,p=()):
    with cx() as c:
        cur=c.execute(sql,p); c.commit(); return cur.lastrowid

def q(sql,p=()):
    with cx() as c: return [dict(r) for r in c.execute(sql,p).fetchall()]

def one(sql,p=()):
    r=q(sql,p); return r[0] if r else None

def init():
    s='''
    CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY,name TEXT,email TEXT UNIQUE,password_hash TEXT,salt TEXT,role TEXT,active INTEGER,created_at TEXT);
    CREATE TABLE IF NOT EXISTS clients(id INTEGER PRIMARY KEY,legal_name TEXT,trade_name TEXT,cnpj TEXT,tax_regime TEXT,created_at TEXT);
    CREATE TABLE IF NOT EXISTS cases(id INTEGER PRIMARY KEY,client_id INTEGER,title TEXT,case_type TEXT,urgency TEXT,status TEXT,pain_summary TEXT,pain_details TEXT,objectives TEXT,ai_preliminary TEXT,ai_diagnosis TEXT,created_at TEXT,updated_at TEXT,FOREIGN KEY(client_id) REFERENCES clients(id));
    CREATE TABLE IF NOT EXISTS requirements(id INTEGER PRIMARY KEY,case_id INTEGER,rkey TEXT,label TEXT,required INTEGER,status TEXT,notes TEXT,UNIQUE(case_id,rkey),FOREIGN KEY(case_id) REFERENCES cases(id));
    CREATE TABLE IF NOT EXISTS documents(id INTEGER PRIMARY KEY,case_id INTEGER,rkey TEXT,label TEXT,original_name TEXT,path TEXT,sha256 TEXT,extracted_text TEXT,created_at TEXT,FOREIGN KEY(case_id) REFERENCES cases(id));
    CREATE TABLE IF NOT EXISTS generated(id INTEGER PRIMARY KEY,case_id INTEGER,doc_type TEXT,title TEXT,content TEXT,created_at TEXT,FOREIGN KEY(case_id) REFERENCES cases(id));
    '''
    with cx() as c: c.executescript(s); c.commit()

def ph(pw,salt=None):
    s=bytes.fromhex(salt) if salt else secrets.token_bytes(16)
    d=hashlib.pbkdf2_hmac('sha256',pw.encode(),s,180000)
    return d.hex(),s.hex()

def verify(pw,h,s): return hmac.compare_digest(ph(pw,s)[0],h)

init()
if not one('SELECT id FROM users LIMIT 1'):
    h,s=ph(os.getenv('ADMIN_PASSWORD','Admin@123'))
    ex('INSERT INTO users(name,email,password_hash,salt,role,active,created_at) VALUES(?,?,?,?,?,?,?)',('Administrador Melo Alves','admin@meloalves.local',h,s,'Administrador',1,datetime.now().isoformat()))

BASE=[
('relatorio_fiscal','Relatório de Situação Fiscal atualizado',1,'Receita Federal/PGFN completo e recente.'),
('cnd','CND/CPEN e demais certidões',1,'Federal, estadual, municipal, FGTS e trabalhista.'),
('societario','Contrato social, alterações e procurações',1,'Documentos de representação.'),
('ecf','ECF dos últimos 5 anos',1,'Arquivo, recibo e apuração do IRPJ/CSLL.'),
('ecd','ECD, balancetes e razão',1,'Últimos 5 anos, conforme pertinência.'),
('dctf','DCTF/DCTFWeb e recibos',1,'Declarações e respectivos recibos.'),
('pagamentos','DARFs, pagamentos e parcelamentos',1,'Comprovantes e extratos.'),
('fontes','Fontes pagadoras e retenções',0,'DIRF/EFD-Reinf e relatórios do e-CAC.'),
('ato','Auto de infração, intimação ou despacho',0,'Documento integral e ciência.'),
('proc_adm','Processo administrativo completo',0,'Capa a capa.'),
('proc_jud','Processo judicial completo',0,'Capa a capa.'),
('contratos','Editais e contratos públicos',0,'Edital, proposta, contrato, aditivos e execução.'),
('creditos','Planilha de créditos e memória de cálculo',0,'Origem, período, base, valor, uso e saldo.'),
('outros','Outros documentos relevantes',0,'Qualquer prova adicional.')]
TYPES=['PER/DCOMP não homologado','Auto de infração','Impedimento de CND/CPEN','Recuperação de crédito','Compensação/restituição','Execução fiscal/dívida ativa','Reequilíbrio de contrato público','Consulta tributária','Outro']

def ck(tp):
    need=set()
    if tp in ['PER/DCOMP não homologado','Recuperação de crédito','Compensação/restituição']: need|={'fontes','ato','proc_adm','creditos'}
    if tp=='Auto de infração': need|={'ato','proc_adm'}
    if tp=='Impedimento de CND/CPEN': need|={'ato','proc_adm'}
    if tp=='Execução fiscal/dívida ativa': need|={'proc_adm','proc_jud'}
    if tp=='Reequilíbrio de contrato público': need|={'contratos','creditos'}
    return [(k,l,1 if req or k in need else 0,n) for k,l,req,n in BASE]

def extract(path):
    try:
        s=path.suffix.lower()
        if s=='.pdf':
            d=fitz.open(path); return '\n'.join(f'--- PÁGINA {i+1} ---\n{p.get_text("text")}' for i,p in enumerate(d))[:500000]
        if s=='.docx': return '\n'.join(p.text for p in Document(path).paragraphs)[:500000]
        if s in ['.txt','.md','.csv']: return path.read_text(encoding='utf-8',errors='ignore')[:500000]
        if s in ['.xlsx','.xls']:
            b=pd.read_excel(path,sheet_name=None); return '\n'.join(f'--- {n} ---\n{df.astype(str).to_csv(index=False)}' for n,df in b.items())[:500000]
    except Exception as e: return f'[ERRO DE EXTRAÇÃO: {e}]'
    return ''

def secret(name,default=''):
    return str(st.secrets[name]) if name in st.secrets else os.getenv(name,default)

def kimi(system,user):
    key=secret('KIMI_API_KEY'); base=secret('KIMI_BASE_URL','https://api.moonshot.ai/v1').rstrip('/'); model=secret('KIMI_MODEL','kimi-k2.5')
    if not key: raise RuntimeError('Configure KIMI_API_KEY nos Secrets do Streamlit.')
    payload={'model':model,'messages':[{'role':'system','content':system},{'role':'user','content':user}],'temperature':0.1,'response_format':{'type':'json_object'}}
    r=requests.post(base+'/chat/completions',headers={'Authorization':f'Bearer {key}','Content-Type':'application/json'},json=payload,timeout=180)
    r.raise_for_status(); return r.json()['choices'][0]['message']['content']

def kimi_text(system,user):
    key=secret('KIMI_API_KEY'); base=secret('KIMI_BASE_URL','https://api.moonshot.ai/v1').rstrip('/'); model=secret('KIMI_MODEL','kimi-k2.5')
    if not key: raise RuntimeError('Configure KIMI_API_KEY nos Secrets do Streamlit.')
    payload={'model':model,'messages':[{'role':'system','content':system},{'role':'user','content':user}],'temperature':0.1}
    r=requests.post(base+'/chat/completions',headers={'Authorization':f'Bearer {key}','Content-Type':'application/json'},json=payload,timeout=180)
    r.raise_for_status(); return r.json()['choices'][0]['message']['content']

def ctx(case_id):
    c=one('''SELECT ca.*,cl.legal_name,cl.cnpj,cl.tax_regime FROM cases ca JOIN clients cl ON cl.id=ca.client_id WHERE ca.id=?''',(case_id,))
    docs=q('SELECT label,original_name,extracted_text FROM documents WHERE case_id=?',(case_id,))
    out=[]; size=0
    for d in docs:
        t=d['extracted_text'] or ''; rem=160000-size
        if rem<=0: break
        out.append(f"\n### {d['label']} — {d['original_name']}\n{t[:rem]}"); size+=min(len(t),rem)
    return c,'\n'.join(out)

PRELIM='''Você faz triagem documental tributária brasileira. Não invente fatos, leis, datas ou valores. Diferencie fato documental, alegação e inferência. Responda JSON válido com: resumo, fatos_identificados[], prazos_identificados[], valores_identificados[], divergencias[], documentos_faltantes[], perguntas_ao_cliente[], nivel_suficiencia, alertas_urgentes[].'''
DIAG='''Você apoia advogado tributarista brasileiro. Baseie-se somente nos documentos. Não invente normas ou julgados. Separe administrativo e judicial, identifique créditos potenciais, requisitos, riscos, documentos e plano de ação. Responda JSON válido com: conclusao_executiva, linha_do_tempo[], creditos_potenciais[], administrativo[], judicial[], riscos[], documentos_complementares[], plano_acao[], observacoes_eticas.'''
PIECE='''Redija MINUTA PRELIMINAR tributária brasileira. Use apenas os fatos fornecidos. Onde faltar dado use [PREENCHER]. Estruture endereçamento, identificação, fatos, tempestividade se aplicável, fundamentos preliminares, provas, pedidos, anexos e fecho. Comece com: MINUTA PRELIMINAR — EXIGE REVISÃO E ASSINATURA DO ADVOGADO RESPONSÁVEL.'''

def parse(s):
    try:return json.loads(s)
    except:
        m=re.search(r'\{.*\}',s,re.S)
        return json.loads(m.group(0)) if m else {'conteudo_bruto':s}

def make_docx(title,content):
    d=Document(); d.add_heading(title,0); d.add_paragraph('MINUTA PRELIMINAR — EXIGE REVISÃO E ASSINATURA DO ADVOGADO RESPONSÁVEL')
    for line in content.split('\n'): d.add_paragraph(line)
    b=io.BytesIO(); d.save(b); return b.getvalue()

def login():
    _,c,_=st.columns([1,1,1])
    with c:
        st.markdown('## ⚖️ Melo Alves'); st.caption('Tax Governance — acesso restrito')
        with st.form('login'):
            email=st.text_input('E-mail',value='admin@meloalves.local'); pw=st.text_input('Senha',type='password',value='Admin@123'); ok=st.form_submit_button('Entrar',use_container_width=True)
        if ok:
            u=one('SELECT * FROM users WHERE lower(email)=lower(?) AND active=1',(email,))
            if u and verify(pw,u['password_hash'],u['salt']): st.session_state.user={'email':u['email'],'name':u['name'],'role':u['role']}; st.rerun()
            st.error('Credenciais inválidas.')
        st.info('Acesso inicial: admin@meloalves.local / Admin@123')

if 'user' not in st.session_state: login(); st.stop()

with st.sidebar:
    st.markdown('## ⚖️ MELO ALVES'); st.caption('Tax Governance'); st.write('**'+st.session_state.user['name']+'**'); st.divider()
    page=st.radio('Menu',['Dashboard','Novo caso','Meus casos','Documentos gerados','Configurações'],label_visibility='collapsed')
    if st.button('Sair',use_container_width=True): st.session_state.clear(); st.rerun()

def head(t,s=''): st.markdown('# '+t); st.caption(s); st.divider()

def opts_clients(): return {f"{r['trade_name'] or r['legal_name']} — {r['legal_name']}":r['id'] for r in q('SELECT * FROM clients ORDER BY legal_name')}
def opts_cases(): return {f"#{r['id']} — {r['title']} — {r['legal_name']}":r['id'] for r in q('''SELECT ca.id,ca.title,cl.legal_name FROM cases ca JOIN clients cl ON cl.id=ca.client_id ORDER BY ca.updated_at DESC''')}

def show(title,items):
    st.markdown('**'+title+'**')
    if not items: st.caption('Nenhum item identificado.')
    for x in items or []: st.write('•',x if isinstance(x,str) else json.dumps(x,ensure_ascii=False))

if page=='Dashboard':
    head('Dashboard','Validação do fluxo tributário com IA.')
    cases=q('SELECT * FROM cases'); c1,c2,c3=st.columns(3); c1.metric('Casos',len(cases)); c2.metric('Em análise',sum(c['status']=='Análise preliminar' for c in cases)); c3.metric('Diagnosticados',sum(c['status']=='Diagnóstico' for c in cases))
    rows=q('''SELECT ca.id,ca.title,ca.case_type,ca.urgency,ca.status,cl.legal_name FROM cases ca JOIN clients cl ON cl.id=ca.client_id ORDER BY ca.updated_at DESC''')
    if rows: st.dataframe(pd.DataFrame(rows),use_container_width=True,hide_index=True)
    else: st.info('Crie seu primeiro caso.')

elif page=='Novo caso':
    head('Novo caso','Cadastre o cliente e inicie o checklist.')
    a,b=st.tabs(['Cliente','Caso'])
    with a:
        with st.form('client'):
            c1,c2=st.columns(2); legal=c1.text_input('Razão social *'); trade=c2.text_input('Nome fantasia'); cnpj=c1.text_input('CNPJ'); regime=c2.selectbox('Regime',['Simples Nacional','Lucro Presumido','Lucro Real','Outro'])
            if st.form_submit_button('Cadastrar') and legal.strip(): ex('INSERT INTO clients(legal_name,trade_name,cnpj,tax_regime,created_at) VALUES(?,?,?,?,?)',(legal,trade,cnpj,regime,datetime.now().isoformat())); st.success('Cliente cadastrado.'); st.rerun()
    with b:
        op=opts_clients()
        if not op: st.warning('Cadastre um cliente primeiro.')
        else:
            with st.form('case'):
                cli=st.selectbox('Cliente',list(op)); title=st.text_input('Título do caso *'); c1,c2=st.columns(2); tp=c1.selectbox('Tipo',TYPES); urg=c2.selectbox('Urgência',['Crítica','Alta','Normal'])
                if st.form_submit_button('Criar caso') and title.strip():
                    cid=ex('INSERT INTO cases(client_id,title,case_type,urgency,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?)',(op[cli],title,tp,urg,'Documentos',datetime.now().isoformat(),datetime.now().isoformat()))
                    for k,l,r,n in ck(tp): ex('INSERT INTO requirements(case_id,rkey,label,required,status,notes) VALUES(?,?,?,?,?,?)',(cid,k,l,r,'Pendente',n))
                    st.session_state.case_id=cid; st.success('Caso criado. Abra Meus casos.')

elif page=='Meus casos':
    head('Meus casos','Checklist → dor → análise → diagnóstico → minuta.')
    op=opts_cases()
    if not op: st.info('Nenhum caso.'); st.stop()
    lab=st.selectbox('Caso',list(op)); cid=op[lab]; st.session_state.case_id=cid
    case=one('''SELECT ca.*,cl.legal_name,cl.cnpj,cl.tax_regime FROM cases ca JOIN clients cl ON cl.id=ca.client_id WHERE ca.id=?''',(cid,))
    st.markdown('### '+case['title']); st.caption(f"{case['legal_name']} | {case['case_type']} | {case['urgency']} | {case['status']}")
    t1,t2,t3,t4=st.tabs(['1. Documentos','2. Dor do cliente','3. Análise preliminar','4. Diagnóstico'])
    with t1:
        for r in q('SELECT * FROM requirements WHERE case_id=? ORDER BY required DESC,id',(cid,)):
            with st.expander(('🔴 ' if r['required'] else '⚪ ')+r['label']+' — '+r['status']):
                st.caption(r['notes']); ups=st.file_uploader('Selecionar arquivo(s)',type=['pdf','docx','txt','md','csv','xlsx','xls'],accept_multiple_files=True,key=f"u{cid}{r['rkey']}")
                if ups and st.button('Salvar',key=f"s{cid}{r['rkey']}"):
                    folder=UP/str(cid); folder.mkdir(exist_ok=True)
                    for up in ups:
                        data=up.getvalue(); name=re.sub(r'[^A-Za-z0-9._-]+','_',Path(up.name).name); p=folder/(datetime.now().strftime('%Y%m%d%H%M%S%f')+'_'+name); p.write_bytes(data)
                        ex('INSERT INTO documents(case_id,rkey,label,original_name,path,sha256,extracted_text,created_at) VALUES(?,?,?,?,?,?,?,?)',(cid,r['rkey'],r['label'],up.name,str(p),hashlib.sha256(data).hexdigest(),extract(p),datetime.now().isoformat()))
                    ex("UPDATE requirements SET status='Anexado' WHERE case_id=? AND rkey=?",(cid,r['rkey'])); st.success('Salvo.'); st.rerun()
                docs=q('SELECT original_name,LENGTH(extracted_text) caracteres FROM documents WHERE case_id=? AND rkey=?',(cid,r['rkey']))
                if docs: st.dataframe(pd.DataFrame(docs),use_container_width=True,hide_index=True)
    with t2:
        with st.form('pain'):
            s=st.text_area('Resumo da dor',value=case['pain_summary'] or ''); d=st.text_area('Descrição detalhada',value=case['pain_details'] or '',height=220); o=st.text_area('Objetivos',value=case['objectives'] or '')
            if st.form_submit_button('Salvar descrição'): ex("UPDATE cases SET pain_summary=?,pain_details=?,objectives=?,status='Descrição da dor',updated_at=? WHERE id=?",(s,d,o,datetime.now().isoformat(),cid)); st.success('Salvo.'); st.rerun()
    with t3:
        if st.button('Executar análise preliminar com Kimi',type='primary'):
            c,docs=ctx(cid); req=q('SELECT label,required,status,notes FROM requirements WHERE case_id=?',(cid,))
            prompt=f"CASO: {json.dumps(c,ensure_ascii=False,default=str)}\nCHECKLIST: {json.dumps(req,ensure_ascii=False)}\nDOCUMENTOS:\n{docs}"
            try:
                with st.spinner('Analisando...'): res=kimi(PRELIM,prompt)
                ex("UPDATE cases SET ai_preliminary=?,status='Análise preliminar',updated_at=? WHERE id=?",(res,datetime.now().isoformat(),cid)); st.success('Concluído.'); st.rerun()
            except Exception as e: st.error(str(e))
        case=one('SELECT * FROM cases WHERE id=?',(cid,))
        if case['ai_preliminary']:
            a=parse(case['ai_preliminary']); st.write(a.get('resumo','')); c1,c2=st.columns(2)
            with c1: show('Fatos',a.get('fatos_identificados')); show('Prazos',a.get('prazos_identificados')); show('Valores',a.get('valores_identificados'))
            with c2: st.metric('Suficiência',a.get('nivel_suficiencia','-')); show('Faltantes',a.get('documentos_faltantes')); show('Alertas',a.get('alertas_urgentes')); show('Perguntas',a.get('perguntas_ao_cliente'))
    with t4:
        case=one('SELECT * FROM cases WHERE id=?',(cid,))
        if not case['ai_preliminary']: st.warning('Execute a análise preliminar primeiro.')
        elif st.button('Gerar diagnóstico com Kimi',type='primary'):
            c,docs=ctx(cid); prompt=f"CASO: {json.dumps(c,ensure_ascii=False,default=str)}\nANÁLISE PRELIMINAR:{c['ai_preliminary']}\nDOCUMENTOS:{docs}"
            try:
                with st.spinner('Gerando diagnóstico...'): res=kimi(DIAG,prompt)
                ex("UPDATE cases SET ai_diagnosis=?,status='Diagnóstico',updated_at=? WHERE id=?",(res,datetime.now().isoformat(),cid)); st.success('Gerado.'); st.rerun()
            except Exception as e: st.error(str(e))
        case=one('SELECT * FROM cases WHERE id=?',(cid,))
        if case['ai_diagnosis']:
            a=parse(case['ai_diagnosis']); st.subheader('Conclusão executiva'); st.write(a.get('conclusao_executiva',''))
            z=st.tabs(['Créditos','Administrativo','Judicial','Riscos','Plano de ação','Gerar minuta'])
            with z[0]: show('Créditos potenciais',a.get('creditos_potenciais'))
            with z[1]: show('Medidas administrativas',a.get('administrativo'))
            with z[2]: show('Medidas judiciais',a.get('judicial'))
            with z[3]: show('Riscos',a.get('riscos')); show('Documentos complementares',a.get('documentos_complementares'))
            with z[4]: show('Plano',a.get('plano_acao')); st.caption(a.get('observacoes_eticas',''))
            with z[5]:
                dt=st.selectbox('Tipo',['Manifestação de inconformidade','Requerimento administrativo','Pedido de diligência','Recurso voluntário','Mandado de segurança','Ação declaratória','Parecer executivo']); extra=st.text_area('Orientações adicionais')
                if st.button('Gerar minuta'):
                    c,docs=ctx(cid); prompt=f"TIPO:{dt}\nCASO:{json.dumps(c,ensure_ascii=False,default=str)}\nDIAGNÓSTICO:{c['ai_diagnosis']}\nDOCUMENTOS:{docs}\nORIENTAÇÕES:{extra}"
                    try:
                        with st.spinner('Gerando...'): text=kimi_text(PIECE,prompt)
                        gid=ex('INSERT INTO generated(case_id,doc_type,title,content,created_at) VALUES(?,?,?,?,?)',(cid,dt,f'{dt} — {c["title"]}',text,datetime.now().isoformat())); st.session_state.gid=gid; st.success('Minuta gerada.')
                    except Exception as e: st.error(str(e))
                if 'gid' in st.session_state:
                    g=one('SELECT * FROM generated WHERE id=?',(st.session_state.gid,))
                    if g and g['case_id']==cid: st.text_area('Minuta',g['content'],height=500); st.download_button('Baixar DOCX',make_docx(g['title'],g['content']),file_name=f'minuta_{g["id"]}.docx')

elif page=='Documentos gerados':
    head('Documentos gerados','Minutas preliminares.')
    for g in q('''SELECT g.*,c.title case_title,cl.legal_name FROM generated g JOIN cases c ON c.id=g.case_id JOIN clients cl ON cl.id=c.client_id ORDER BY g.created_at DESC'''):
        with st.expander(f"{g['doc_type']} — {g['legal_name']} — {g['created_at'][:16]}"):
            st.write(g['content']); st.download_button('Baixar DOCX',make_docx(g['title'],g['content']),file_name=f'minuta_{g["id"]}.docx',key=f'd{g["id"]}')

elif page=='Configurações':
    head('Configurações','Integração com a Kimi.')
    st.metric('KIMI_API_KEY','Configurada' if secret('KIMI_API_KEY') else 'Pendente')
    st.code('''KIMI_API_KEY = "SUA_CHAVE"\nKIMI_BASE_URL = "https://api.moonshot.ai/v1"\nKIMI_MODEL = "MODELO_DISPONIVEL_NA_SUA_CONTA"''',language='toml')
    st.warning('Para dados reais, migre SQLite e arquivos locais para PostgreSQL/Supabase e Storage externo. O Community Cloud pode reiniciar o armazenamento local.')
    st.info('O sistema gera a peça e o pacote documental. Protocolo automático no e-CAC/PJe exige integração autorizada, credenciais e certificado digital.')
