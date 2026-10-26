# Arquitetura e ambiente

## Levantamento de 26/10/2026

O computador usa Ubuntu 26.04.1 LTS com GNOME/Wayland e arquitetura x86_64. Havia 6,7 GiB de RAM e cerca de 80 GiB livres no volume do projeto. Python 3.14.4, Node 24.18, npm 11.16, Git 2.53, PostgreSQL 18.6 e systemd 259 estavam disponíveis. O cluster PostgreSQL do sistema estava parado e não foi alterado. Docker estava instalado, mas o daemon não estava acessível; a instalação nativa evita depender dele. Codex CLI 0.162.1 estava presente; Claude e Gemini não. O repositório estava vazio e não havia `AGENTS.md`.

## Decisões aplicadas

A interface React/TypeScript é compilada pelo Vite e servida pela mesma aplicação FastAPI que expõe `/api`. SQLAlchemy 2 e Alembic cuidam da persistência e das migrações. O domínio em `backend/app/domain.py` calcula saldos, orçamento, consumo, cartão e patrimônio. A API e o MCP STDIO chamam esses serviços; o MCP não depende de a interface estar aberta.

```text
Navegador local → FastAPI (127.0.0.1:8765) → domínio → PostgreSQL privado
                                            ↑
Codex/cliente MCP → processo STDIO ─────────┘
```

O PostgreSQL do aplicativo é um cluster do usuário em `~/.local/share/meu-financeiro/postgres/data`, porta 55432 em **socket Unix**, sem escuta TCP. Dois bancos separam dados pessoais de testes: `meu_financeiro` e `meu_financeiro_test`. A aplicação conecta como `finance_app`; a senha fica fora do projeto, em `~/.config/meu-financeiro/`.

Dois serviços `systemd --user` controlam banco e API separadamente. Abrir o ícone inicia o banco, verifica a API e abre o navegador. Parar a API deixa o banco disponível para o MCP. O comando MCP resolve o caminho do projeto sem depender do diretório atual. A API recusa iniciar com esquema desatualizado; as migrações são aplicadas pelo instalador, não pelo clique no ícone.

Valores BRL ficam em `NUMERIC(18,2)` e são calculados com `Decimal`. A interface envia strings decimais e usa números JavaScript somente para dimensões de gráficos e barras. Transferências entre contas têm duas pernas atômicas; compra no cartão gera consumo e parcelas, e a fatura é liquidada por transferência. Avaliações de investimentos e correções ficam registradas com data e histórico.

## Fronteiras e limites

Tudo funciona sem internet após instalar dependências. Não há acesso bancário, preços de mercado, envio automático a modelos externos ou sincronização em nuvem. O navegador local não exige login; consulte [Segurança](SEGURANCA.md) sobre a fronteira de confiança dessa escolha. A evolução patrimonial começa nas fotografias registradas pelo usuário; não há reconstrução confiável de datas anteriores sem histórico completo de avaliações.

Fontes técnicas consultadas em 26/10/2026: [PostgreSQL numeric](https://www.postgresql.org/docs/current/datatype-numeric.html), [SQLAlchemy Session](https://docs.sqlalchemy.org/en/20/orm/session_basics.html), [MCP Python SDK](https://py.sdk.modelcontextprotocol.io/), [FastAPI](https://fastapi.tiangolo.com/), [Vite](https://vite.dev/guide/).
