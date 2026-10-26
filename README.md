# Meu Financeiro

Aplicativo pessoal de finanças que roda neste computador. O PostgreSQL guarda os registros; a interface abre pelo ícone **Meu Financeiro** no menu do Ubuntu. O mesmo banco atende ao servidor MCP local usado pelo Codex.

## Começar

1. Abra **Meu Financeiro** pelo menu de aplicativos.
2. Cadastre uma conta e o saldo inicial. Depois, crie as categorias que usa.
3. Registre receitas e despesas. Para compras no cartão, use **Contas e cartões → Nova compra**, pois o pagamento da fatura não deve repetir a despesa.
4. Defina um limite ao criar ou editar uma categoria de despesa, ou em **Orçamentos**. Escolha mês civil, dia fixo do mês ou intervalo de N dias, semanas ou meses. Marque como entretenimento as categorias de lazer que desejar acompanhar em conjunto.

O seletor **Mês** muda os relatórios de gastos do mês civil; os limites mostram o ciclo vigente de cada categoria, que pode atravessar meses. O ícone de calendário abre as visões por dia, semana, mês e ano. Em **Orçamentos**, cada categoria de despesa oferece **Lançar gasto**, **Editar** e **Definir limite**. O formulário mostra o primeiro período e a próxima renovação antes de salvar. Compras manuais do cartão podem ser editadas ou enviadas à **Lixeira** na lista de gastos, na fatura, nos detalhes e no histórico; não é preciso informar um motivo. A exclusão ajusta parcelas e o pagamento manual da fatura, quando houver, e pode ser desfeita pela Lixeira. Em **Patrimônio**, metas podem ser criadas sem saldo e acompanhadas por contas escolhidas. O botão superior alterna imediatamente entre claro e escuro; o perfil conserva também a opção de seguir o sistema.

Saldos e patrimônio mostram a posição atual. Valores de investimentos são informados manualmente, sem cotação automática. A tela de patrimônio permite guardar uma fotografia datada para acompanhar a evolução a partir dela.

## Onde encontrar ajuda

- [Instalação e solução de falhas](docs/INSTALACAO.md)
- [Backup e restauração](docs/BACKUP_E_RESTAURACAO.md)
- [Ferramentas MCP e Codex](docs/MCP.md)
- [Regras financeiras](docs/REGRAS_FINANCEIRAS.md)
- [Segurança e privacidade](docs/SEGURANCA.md)
- [Resultados dos testes](docs/PLANO_DE_TESTES.md)

A integração com outros assistentes é tratada separadamente: [Claude](docs/INTEGRACAO_CLAUDE.md), [Gemini](docs/INTEGRACAO_GEMINI.md) e [ChatGPT web](docs/INTEGRACAO_CHATGPT.md).

## Estrutura

`frontend/` contém a interface React; `backend/app/`, a API e as regras financeiras; `mcp_server/`, as ferramentas STDIO; `migrations/`, o esquema PostgreSQL; `scripts/`, instalação, execução e backup. Nenhum dado pessoal ou senha fica no repositório.
