
# Melo Alves Tax Governance

MVP funcional em Python e Streamlit para gestão de:

- clientes e empresas;
- conflito de interesses;
- projetos e diagnósticos;
- matriz de riscos;
- plano de ação;
- data room;
- créditos tributários;
- contratos públicos;
- reequilíbrio econômico-financeiro;
- ciclos mensais;
- reuniões;
- relatórios em PDF;
- assistente de IA via endpoint compatível com OpenAI;
- usuários e auditoria.

## 1. Requisitos

- Python 3.11 ou superior
- pip

## 2. Instalação local

Abra o terminal dentro da pasta do projeto:

```bash
python -m venv .venv
```

Windows:

```bash
.venv\Scripts\activate
```

macOS/Linux:

```bash
source .venv/bin/activate
```

Instale:

```bash
pip install -r requirements.txt
```

Execute:

```bash
streamlit run app.py
```

O navegador abrirá em:

```text
http://localhost:8501
```

## 3. Acesso inicial

- E-mail: `admin@meloalves.local`
- Senha: `Admin@123`

Troque essa senha antes de qualquer teste com terceiros.

## 4. Integração com Kimi

A integração é genérica e pressupõe um endpoint no formato compatível com Chat Completions.

Configure as variáveis:

```bash
KIMI_API_URL=https://SEU-ENDPOINT/v1/chat/completions
KIMI_API_KEY=SUA-CHAVE
KIMI_MODEL=SEU-MODELO
```

No Streamlit Community Cloud, use **Settings > Secrets**. Como este MVP lê variáveis de ambiente,
uma alternativa é adaptar para `st.secrets` ou publicar pelo Render com as variáveis configuradas.

## 5. Publicação no Streamlit Community Cloud

1. Crie uma conta no GitHub.
2. Crie um repositório.
3. Envie `app.py` e `requirements.txt`.
4. Acesse o Streamlit Community Cloud.
5. Conecte sua conta GitHub.
6. Escolha o repositório e o arquivo `app.py`.
7. Clique em Deploy.

A aplicação receberá um endereço terminado em `.streamlit.app`.

### Atenção sobre persistência

O Streamlit Community Cloud é excelente para demonstração, mas o armazenamento local pode ser reiniciado.
Para dados permanentes, use PostgreSQL/Supabase e armazenamento de arquivos externo.

## 6. Publicação no Render

O projeto inclui `render.yaml` e `Dockerfile`.

1. Envie os arquivos para o GitHub.
2. No Render, crie um novo Web Service.
3. Conecte o repositório.
4. Use Docker ou o comando:
   `streamlit run app.py --server.address 0.0.0.0 --server.port $PORT`
5. Configure as variáveis de ambiente.
6. Para produção, conecte um banco PostgreSQL e disco persistente.

## 7. Avisos

Este é um MVP tecnológico. Antes de uso profissional com dados fiscais reais:

- migre SQLite para PostgreSQL;
- use armazenamento S3 ou Supabase;
- implemente autenticação multifator;
- contrate revisão de segurança;
- configure backup e restauração;
- implemente antivírus de upload;
- formalize LGPD e política de retenção;
- revise todos os textos e fluxos jurídicos;
- não permita que IA aprove conclusões jurídicas ou contábeis.

## 8. Estrutura

```text
app.py              aplicação completa
requirements.txt    dependências
Dockerfile          container
render.yaml         implantação no Render
.env.example        variáveis
.gitignore          arquivos ignorados
```
