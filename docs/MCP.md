# Integração MCP local e Codex

O servidor usa o SDK oficial Python do Model Context Protocol com transporte STDIO (`mcp_server/server.py`). Cada chamada abre uma sessão no mesmo PostgreSQL da interface web e reutiliza integralmente os serviços de domínio de `backend/app/domain.py` e `backend/app/categories.py`. Ele não aceita SQL arbitrário, comandos de sistema nem caminhos de arquivo fornecidos pelo agente. Valores monetários são strings decimais com duas casas (ex.: `"42.50"`); datas usam `AAAA-MM-DD`; identificadores são UUIDs obtidos por consulta.

## Codex Desktop e CLI nesta máquina

A entrada `meu_financeiro` está configurada em `~/.codex/config.toml` apontando para `/home/teus/Documents/ChatGPT/lastro-financeiro/scripts/run-mcp.sh`, com `cwd = "/home/teus/Documents/ChatGPT/lastro-financeiro"`, `startup_timeout_sec = 30`, `default_tools_approval_mode = "writes"` e variáveis de barramento de sessão (`XDG_RUNTIME_DIR` e `DBUS_SESSION_BUS_ADDRESS`).

### Correção de inicialização no Codex Desktop (STDIO)

O launcher STDIO do Codex Desktop inicia servidores MCP com ambiente sanitizado (sem `DBUS_SESSION_BUS_ADDRESS` e `XDG_RUNTIME_DIR`). Anteriormente, `scripts/start-postgres.sh` executava `systemctl --user start meu-financeiro-postgres.service` antes de verificar `pg_isready`, causando falha imediata no handshake `initialize` quando o D-Bus de usuário não estava no ambiente.

Agora:
1. `scripts/start-postgres.sh` verifica primeiro `pg_isready -q -h "$SOCKET_DIR" -p 55432` e retorna imediatamente (`exit 0`) quando o PostgreSQL local já está ativo, sem depender do `systemctl --user` nem emitir ruído em `stdout`/`stderr`.
2. Caso o banco precise ser iniciado, o script define `HOME`, `XDG_RUNTIME_DIR` e `DBUS_SESSION_BUS_ADDRESS` padrão do usuário e possui fallback direto para `pg_ctl`.
3. `scripts/run-mcp.sh` preserva `DATABASE_URL` caso seja sobrescrito em sessões de teste isoladas (`meu_financeiro_test`).

Confira a configuração com:

```bash
codex mcp get meu_financeiro
codex mcp list
```

> **Importante:** Se o Codex Desktop já estava aberto antes da atualização do script ou de `~/.codex/config.toml`, reinicie o aplicativo Codex Desktop (ou recarregue a sessão) para que o `connection_manager` refaça o handshake `initialize` e carregue o catálogo de 85 ferramentas.

## Sincronização com a Interface Web

A interface web (`frontend/src/App.tsx`) atualiza automaticamente os dados ao receber foco (`window.focus`), ao tornar a aba visível (`document.visibilitychange`) e periodicamente em segundo plano a cada 5 segundos enquanto visível, refletindo alterações feitas via MCP sem exigir recarregamento manual da página.

## Catálogo Completo de Ferramentas MCP (85 ferramentas)

| Domínio | Ferramentas de Leitura (`READ_ONLY`) | Ferramentas de Escrita (`IDEMPOTENT_WRITE` / `CORRECTION_WRITE`) |
| --- | --- | --- |
| **1. Visão geral e Contas** | `finance_get_overview`, `finance_get_balances`, `finance_list_accounts`, `finance_get_account` | `finance_create_account`, `finance_update_account`, `finance_archive_account`, `finance_restore_account` |
| **2. Categorias** | `finance_list_categories`, `finance_get_category`, `finance_preview_category_archive` | `finance_create_category`, `finance_update_category`, `finance_archive_category`, `finance_restore_category` |
| **3. Movimentações e Lixeira** | `finance_list_transactions`, `finance_get_transaction`, `finance_get_transaction_trash`, `finance_get_deletion_preview`, `finance_get_transaction_revisions`, `finance_get_transaction_lifecycle` | `finance_create_transaction`, `finance_update_transaction` (suporta atualização parcial), `finance_settle_transaction`, `finance_delete_transaction`, `finance_restore_transaction` |
| **4. Transferências** | `finance_list_transfers`, `finance_get_transfer` | `finance_create_transfer`, `finance_update_transfer` |
| **5. Orçamentos e Lazer** | `finance_get_budget_status`, `finance_get_category_budget`, `finance_preview_budget_cycle`, `finance_get_entertainment`, `finance_get_category_spending` | `finance_set_budget` |
| **6. Cartões, Compras, Parcelas e Faturas** | `finance_get_cards`, `finance_get_card`, `finance_list_card_purchases`, `finance_get_card_purchase`, `finance_get_invoices`, `finance_get_invoice`, `finance_list_installments` | `finance_create_card`, `finance_update_card`, `finance_archive_card`, `finance_restore_card`, `finance_create_card_purchase`, `finance_update_card_purchase`, `finance_delete_card_purchase`, `finance_restore_card_purchase`, `finance_pay_invoice` |
| **7. Contas a Pagar** | `finance_get_upcoming_bills`, `finance_list_bills`, `finance_get_bill` | `finance_create_bill`, `finance_update_bill`, `finance_pay_bill` |
| **8. Planos Recorrentes** | `finance_get_recurring_plans` | `finance_create_recurring_plan`, `finance_update_recurring_plan`, `finance_realize_recurring_plan`, `finance_deactivate_recurring_plan`, `finance_activate_recurring_plan` |
| **9. Investimentos e Patrimônio** | `finance_get_investments`, `finance_get_investment`, `finance_list_investment_events`, `finance_list_investment_valuations`, `finance_get_net_worth`, `finance_get_net_worth_history` | `finance_create_investment`, `finance_update_investment`, `finance_create_investment_event`, `finance_record_investment_valuation`, `finance_save_net_worth_snapshot` |
| **10. Metas Financeiras** | `finance_get_goals`, `finance_get_goal`, `finance_list_goal_contributions`, `finance_list_goal_allocations` | `finance_create_goal`, `finance_update_goal`, `finance_add_goal_contribution` |
| **11. Relatórios e Calendário** | `finance_get_monthly_comparison`, `finance_compare_periods`, `finance_get_calendar` | — |

## Regras de Segurança e Idempotência

- **Sem exclusão física:** Nenhuma ferramenta MCP apaga registros fisicamente do PostgreSQL. Movimentações e compras no cartão vão para a lixeira (`deleted_at`) preservando o mesmo UUID e podendo ser restauradas; categorias, contas e cartões são arquivados (`is_active = false`); planos recorrentes são desativados (`is_active = false`).
- **Idempotência:** Criação e correção de movimentações, transferências, compras no cartão, pagamentos de faturas/contas e eventos/avaliações de investimentos exigem `idempotency_key`. Repetir a mesma chamada com a mesma chave retorna o registro original sem duplicar; reutilizar a chave com parâmetros diferentes gera erro de conflito.
- **Controle de versão e confirmação:** Correções (`finance_update_transaction`, `finance_update_transfer`, `finance_update_card_purchase`) e exclusões lógicas (`finance_delete_transaction`, `finance_delete_card_purchase`) exigem `expected_version` atual para evitar condições de corrida.

## Diagnóstico e Testes Isolados

Todos os testes automatizados e provas MCP rodam **exclusivamente** no banco `meu_financeiro_test`, sem tocar no banco pessoal `meu_financeiro`:

```bash
./scripts/test.sh
./scripts/probe-mcp.sh
```
