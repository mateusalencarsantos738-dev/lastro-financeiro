# Integração MCP local e Codex

O servidor usa o SDK oficial Python do Model Context Protocol com transporte STDIO. Cada chamada abre uma sessão no mesmo PostgreSQL da interface e usa as regras do backend. Ele não aceita SQL, comandos de sistema nem caminhos de arquivo fornecidos pelo agente. Valores monetários são strings decimais, como `"42.50"`; datas usam `AAAA-MM-DD`. Identificadores são UUIDs obtidos por consulta.

## Codex nesta máquina

A entrada `meu_financeiro` foi acrescentada a `~/.codex/config.toml` com backup prévio. O comando configurado é o caminho absoluto de `scripts/run-mcp.sh`. A política `default_tools_approval_mode = "writes"` permite consultas e solicita aprovação para gravações. A configuração existente dos outros servidores foi preservada. Confira com:

```bash
codex mcp get meu_financeiro
codex mcp list
```

O próprio Codex CLI descobriu e executou uma leitura e gravou uma despesa sintética usando uma substituição **somente da sessão de teste** para `meu_financeiro_test`. A persistência foi confirmada no PostgreSQL. Na configuração normal, o servidor aponta ao banco pessoal. Diga ao agente qual conta e categoria usar, ou peça primeiro que as liste. Não peça para presumir uma conta padrão que não existe.

## Ferramentas disponíveis

| Grupo | Ferramentas | Parâmetros principais |
| --- | --- | --- |
| Visão e contas | `finance_get_overview`, `finance_get_balances`, `finance_list_categories` | mês opcional na visão |
| Movimentações | `finance_list_transactions`, `finance_get_transaction`, `finance_create_transaction`, `finance_update_transaction`, `finance_create_transfer`, `finance_get_deletion_preview`, `finance_get_transaction_trash`, `finance_delete_transaction`, `finance_restore_transaction` | período/categoria; tipo, valor, conta, data e chave; correção comum exige motivo; exclusão genérica exige versão e confirmação |
| Orçamento | `finance_get_budget_status`, `finance_set_budget`, `finance_get_category_spending`, `finance_get_entertainment` | data de consulta; categoria, limite, vigência e periodicidade na escrita |
| Compromissos | `finance_get_upcoming_bills`, `finance_get_cards`, `finance_get_invoices`, `finance_create_card_purchase`, `finance_list_card_purchases`, `finance_get_card_purchase`, `finance_update_card_purchase`, `finance_delete_card_purchase`, `finance_restore_card_purchase`, `finance_pay_invoice` | cartão, compra, parcelas, fatura e conta de pagamento; compras manuais podem ser corrigidas sem justificativa |
| Patrimônio | `finance_get_investments`, `finance_create_investment_event`, `finance_record_investment_valuation`, `finance_get_net_worth`, `finance_get_net_worth_history`, `finance_save_net_worth_snapshot`, `finance_get_goals` | investimento, conta, tipo de evento, valor e data quando aplicável |
| Comparação | `finance_get_monthly_comparison` | 2 a 24 meses |

As descrições e os esquemas completos são publicados na descoberta MCP. Criações de movimentações, compras e avaliações exigem `idempotency_key`: repita a **mesma chave e os mesmos dados** numa tentativa de repetição. Uma chave reaproveitada com outro conteúdo é rejeitada. A correção genérica altera receitas, despesas ou reembolsos comuns e exige motivo. Para compras manuais no cartão, use `finance_list_card_purchases` com filtros de cartão, categoria, data, descrição e valor, confirme que há apenas uma correspondência, consulte `finance_get_card_purchase` e envie o ID e a versão a `finance_update_card_purchase` ou `finance_delete_card_purchase`. A edição especializada altera somente os campos informados e não exige motivo. A exclusão especializada usa o ID explícito e não exige uma segunda confirmação textual.

`finance_set_budget` aceita `period_type` (`calendar_month`, `monthly_day`, `days`, `weeks`, `months`), `interval_count` de 1 a 120, `renewal_day` de 1 a 31 apenas para `monthly_day`, e `effective_start` opcional. O campo legado `month` continua sendo uma data ISO obrigatória e é usado como início quando `effective_start` não é informado. `finance_get_budget_status` recebe a data de referência no campo `month` e retorna o ciclo que contém essa data, inclusive `period_start`, `period_end`, `next_renewal`, `state`, `spent`, `remaining` e `percent_used`. `finance_list_categories` informa a configuração vigente ou a próxima programada. `finance_get_category_spending` responde a uma pergunta diferente: total gasto no intervalo de datas pedido, independentemente do ciclo do limite. Todos usam as mesmas regras do domínio que a API e o dashboard.

`finance_list_categories(scope="active"|"archived"|"all")` também informa cor, ícone, estado e data de visibilidade. `finance_preview_category_archive` mostra o impacto antes da escrita. `finance_archive_category` e `finance_restore_category` exigem `confirmed=true` e usam as mesmas regras de domínio que a API. O arquivamento preserva UUID, transações e limites; novas movimentações na categoria arquivada são recusadas pelo backend. `finance_get_category_spending` continua incluindo os gastos históricos da categoria original, mesmo arquivada. A prova `scripts/probe_category_mcp.py` exerce essas ferramentas pelo protocolo STDIO no banco sintético `meu_financeiro_test`.

Na exclusão genérica, consulte `finance_get_deletion_preview` antes de gravar. A exclusão envia o registro à lixeira com o mesmo UUID; consultas financeiras normais deixam de contá-lo. Compras parceladas são tratadas como um conjunto. Quando uma fatura já foi paga, a correção recalcula o pagamento manual correspondente; isso altera também o saldo registrado da conta usada no pagamento. A restauração recompõe o mesmo conjunto, sem duplicar valores. Cartão, ciclo ou quantidade de parcelas já pagos não podem ser movidos; valor, descrição e categoria podem ser corrigidos. A listagem de metas separa objetivo, contribuição, reserva, saldo acompanhado e disponibilidade estimada; a de categorias inclui o identificador do ícone.

## Diagnóstico

Execute `./scripts/probe-mcp.sh` para testar o protocolo no banco separado. Para verificar o banco privado, use `systemctl --user status meu-financeiro-postgres.service`. Mensagens do MCP ficam em stderr; stdout é reservado ao protocolo. Erro de banco indisponível aparece como erro da ferramenta e não como resultado financeiro vazio.

O Codex CLI e o SDK MCP foram testados. Um cliente que rode em nuvem pode transmitir os campos retornados pelas ferramentas ao fornecedor do modelo; avalie o conteúdo da consulta antes de autorizar o uso.

Fontes consultadas em 26/10/2026: [SDK oficial MCP Python](https://py.sdk.modelcontextprotocol.io/), [CLI do Codex](https://learn.chatgpt.com/docs/cli/reference), [referência de configuração do Codex](https://learn.chatgpt.com/docs/config-file/config-reference).
