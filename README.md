# Meu Financeiro

Aplicativo pessoal de finanças que roda neste computador. O PostgreSQL guarda os registros e a interface abre pelo ícone **Meu Financeiro** no menu do Ubuntu. O servidor MCP local lê o mesmo banco, então qualquer assistente de IA compatível com MCP, como Claude, Codex ou Gemini, pode consultar e registrar seus dados.

## Começar

1. Abra **Meu Financeiro** pelo menu de aplicativos.
2. Cadastre uma conta com o saldo inicial e crie as categorias que você usa.
3. Registre suas receitas e despesas. Compras no cartão entram em **Contas e cartões → Nova compra**. Assim, o pagamento da fatura não conta a despesa duas vezes.
4. Defina um limite ao criar ou editar uma categoria de despesa, ou em **Orçamentos**. O ciclo pode ser o mês civil, um dia fixo do mês ou um intervalo de N dias, semanas ou meses. Se quiser acompanhar o lazer em conjunto, marque essas categorias como entretenimento.

O seletor **Mês** controla os relatórios de gastos do mês civil. Os limites seguem o ciclo vigente de cada categoria, que pode atravessar meses. Para ver um ciclo passado ou futuro, use **Consultar ciclo na data** em **Orçamentos** e escolha o dia. O ícone de calendário abre as visões por dia, semana, mês e ano.

Cada categoria de despesa tem os botões **Lançar gasto**, **Editar** e **Definir limite**. Antes de salvar, o formulário mostra o primeiro período e a próxima renovação.

As compras manuais no cartão podem ser editadas ou enviadas à **Lixeira** pela lista de gastos, pela fatura, pelos detalhes e pelo histórico, sem precisar informar motivo. A exclusão ajusta as parcelas e o pagamento manual da fatura, se houver, e dá para desfazê-la pela Lixeira.

Em **Patrimônio**, você pode criar metas sem saldo e acompanhá-las por contas à sua escolha. O botão no topo alterna na hora entre tema claro e escuro, e o perfil também permite seguir o tema do sistema.

Saldos e patrimônio mostram a posição atual. Você informa os valores dos investimentos manualmente, pois não há cotação automática. Na tela de patrimônio, é possível guardar uma fotografia datada e acompanhar a evolução a partir dela.

## Onde encontrar ajuda

- [Instalação e solução de falhas](docs/INSTALACAO.md)
- [Backup e restauração](docs/BACKUP_E_RESTAURACAO.md)
- [Ferramentas MCP](docs/MCP.md)
- [Regras financeiras](docs/REGRAS_FINANCEIRAS.md)
- [Segurança e privacidade](docs/SEGURANCA.md)
- [Resultados dos testes](docs/PLANO_DE_TESTES.md)

A integração com outros assistentes tem documentação própria: [Claude](docs/INTEGRACAO_CLAUDE.md), [Gemini](docs/INTEGRACAO_GEMINI.md) e [ChatGPT web](docs/INTEGRACAO_CHATGPT.md).

## Estrutura

- `frontend/`: interface React
- `backend/app/`: API e regras financeiras
- `mcp_server/`: ferramentas STDIO
- `migrations/`: esquema do PostgreSQL
- `scripts/`: instalação, execução e backup

Nenhum dado pessoal nem senha fica no repositório.
