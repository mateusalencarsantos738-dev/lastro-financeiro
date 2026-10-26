# Modelo de dados implementado

O esquema está versionado em `migrations/versions/0001_initial.py` até `0008_goal_tracking_category_icon.py`. As migrações posteriores acrescentam planos recorrentes, detalhes de investimentos e metas, ordem de reservas, lixeira reversível, acompanhamento de contas e ícones. Todas as tabelas financeiras usam chaves UUID; contas, categorias e lançamentos relacionados usam chaves estrangeiras restritivas.

| Tabela | Papel |
| --- | --- |
| `accounts`, `categories` | Contas monetárias, cartões e categorias editáveis; categorias têm ícone estável opcional e podem ser marcadas como entretenimento. |
| `transactions` | Receitas, despesas, reembolsos, duas pernas de transferências e saídas para aporte. Guarda data, competência, situação, vínculo, chave de idempotência e versão. |
| `budgets`, `idempotency_records` | Limite por categoria/mês e prevenção de repetição de operações. |
| `credit_cards`, `credit_purchases`, `invoices`, `installments` | Compra integral reconhecida no consumo, cronograma de parcelas e pagamento de fatura sem nova despesa. |
| `bills` | Obrigação conhecida, vencimento e ligação com a transação que a quitou. |
| `recurring_plans`, `recurring_occurrences` | Previsões mensais e realização vinculada à transação confirmada. |
| `investments`, `investment_events`, `investment_valuations` | Valor contábil, aporte/resgate/rendimento/taxa e avaliações manuais datadas. |
| `goals`, `goal_allocations`, `goal_contributions`, `goal_tracking_accounts` | Objetivos, reservas explícitas, contribuições registradas e seleção de contas acompanhadas. |
| `net_worth_snapshots` | Fotografias patrimoniais datadas. |
| `transaction_revisions` | Valor anterior e novo, versão, motivo e data da correção. |
| `transaction_lifecycle_events` | Auditoria de exclusão reversível e restauração. |

`NUMERIC(18,2)` guarda valores em reais; não há armazenamento monetário em `float`. Índices cobrem datas de transação/competência, vínculos de conta e categoria, vencimentos e trilha de revisão. O banco veta valor não positivo em lançamentos, parcelas e contas a pagar. As validações de domínio rejeitam categoria incompatível, conta inexistente, cartão usado fora do fluxo de compra e chave de idempotência reaproveitada com conteúdo diferente.

Saldos, gasto por categoria, orçamento e patrimônio são calculados dos registros originais. O saldo não é gravado como número independente. `net_worth_snapshots` guarda apenas uma fotografia do cálculo de cada dia em que o usuário solicita o registro; um dia sem fotografia não é interpolado. Metas reservam parte do caixa existente e não criam ativo novo.

Correção só alcança receita, despesa ou reembolso realizado comum, com versão esperada, confirmação e motivo. O sistema impede alterar por essa rota compra no cartão, pagamento vinculado ou despesa com reembolso vinculado. A revisão preserva antes/depois. A lixeira usa `transactions.deleted_at`: registros excluídos deixam os totais ativos e podem ser restaurados pelo mesmo UUID; não há exclusão física pela interface ou MCP.

Limites atuais: não há série automática de avaliações antigas nem dados de mercado. Planos recorrentes geram previsões mensais e só afetam o caixa quando o usuário confirma a realização. O valor de investimento entre avaliações é ajustado pelos eventos cadastrados e deve ser revisto manualmente quando necessário. Preferências do perfil e foto ficam no armazenamento local do navegador, fora das tabelas financeiras.
