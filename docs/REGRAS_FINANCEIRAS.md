# Regras financeiras da aplicação

## Datas e valores

Cada movimentação tem data da transação e data de competência. A API usa o primeiro dia do mês da transação como competência padrão. Contas e parcelas têm vencimento; pagamentos guardam a data de liquidação. O banco armazena reais em `NUMERIC(18,2)`, e o domínio rejeita valores sem centavos exatos, zero ou negativos para lançamentos. As saídas são representadas pelo tipo de operação, não por um valor negativo digitado.

## O que entra em cada cálculo

- **Caixa:** saldo inicial das contas monetárias mais entradas realizadas menos saídas realizadas. Cartões são excluídos do caixa.
- **Consumo do mês:** despesas realizadas pela competência menos reembolsos. Transferências, aportes e pagamentos de fatura ficam fora desse total.
- **Orçamento restante:** limite do ciclo vigente da categoria menos despesas realizadas e mais reembolsos realizados no intervalo. Valor negativo mostra excesso; o sistema continua aceitando um gasto real.
- **Caixa após compromissos:** caixa menos contas a pagar, parcelas abertas e reservas de metas. É uma estimativa conservadora, não uma garantia de dinheiro livre; receitas futuras não são antecipadas.
- **Patrimônio líquido:** caixa mais último valor registrado dos investimentos menos dívida de cartão e contas a pagar cadastradas. Metas não aumentam nem diminuem o patrimônio.

Uma transferência própria gera saída e entrada atômicas de mesmo valor. A soma do caixa e o patrimônio não mudam. Uma compra no cartão registra o total como consumo na data da compra, baixa o saldo do cartão e cria parcelas com vencimentos e centavos exatos. O pagamento de fatura transfere dinheiro da conta para o cartão, marca parcelas como pagas e **não cria outra despesa de consumo**.

A conta a pagar representa uma obrigação já conhecida. Ela reduz o patrimônio e o disponível estimado desde o cadastro; quando é paga, surge a despesa de consumo e a obrigação deixa de ser passivo. Essa convenção não deve ser usada para uma simples ideia de gasto ainda não assumida. Planos recorrentes servem para previsões, sem afetar o caixa até a realização confirmada.

Aporte reduz o caixa e aumenta o valor contábil do investimento. Resgate faz o inverso. Rendimento reinvestido aumenta o valor do ativo sem criar renda no caixa; taxa debitada do ativo o reduz. Avaliação manual substitui o valor atual e preserva o histórico de avaliações. Não há cálculo de rentabilidade percentual, preço de mercado ou correção pela inflação, porque faltariam fluxos e séries comparáveis.

Reembolso usa categoria de despesa e pode apontar ao lançamento original; ele diminui o consumo em vez de aumentar a receita. Correção de receita, despesa ou reembolso comum exige confirmação, motivo e versão atual. O valor anterior e o novo ficam em `transaction_revisions`. Compras no cartão usam uma rota própria com versão atual, sem motivo textual obrigatório; valor, descrição, categoria, data, cartão e parcelamento podem ser corrigidos. Cartão, ciclo ou quantidade de parcelas já pagos não podem ser movidos, pois isso remapearia um pagamento histórico para outra fatura. Pagamentos vinculados e despesas já reembolsadas não são corrigidos pela rota genérica. Não há exclusão física de movimentações.

## Ciclos dos limites por categoria

Antes da migração 0009, um limite era uma linha em `budgets` para um mês civil específico. O cálculo somava gastos daquele mês; não havia renovação automática nem campo de periodicidade. Essas linhas permanecem intactas e são usadas nas consultas históricas anteriores às novas regras. Um limite registrado para o mês da migração, sem outro limite futuro para a mesma categoria, ganhou uma regra de renovação mensal a partir do primeiro dia do mês seguinte. Assim, o mês já registrado conserva seu valor e intervalo.

Regras novas ficam em `budget_rules`, com valor, data de início da vigência, tipo de período, intervalo e, quando aplicável, dia mensal de renovação. A migração 0010 identifica as regras iniciais criadas para renovar limites legados; ao escolher um ciclo novo antes da renovação, essa regra inicial é retirada para não sobrescrever a escolha. A edição de categoria ou de limite cria uma nova vigência na data escolhida; alterações comuns pela interface usam o dia atual quando a data fica em branco. Regras futuras não afetam o orçamento atual até sua data de início. Uma nova vigência dentro de um ciclo encerra esse ciclo na data da mudança. O histórico anterior permanece ligado à regra anterior. Uma alteração enviada explicitamente com data passada pode recalcular um orçamento histórico; a interface não preenche automaticamente datas passadas em edições de regras vigentes.

Os ciclos disponíveis são: mês civil; dia fixo do mês; N dias; N semanas; N meses. Dia fixo mensal e intervalo de dias têm cálculos diferentes. Para meses curtos, dias 29 a 31 caem no último dia disponível. Intervalos de meses sempre partem da data de referência original, evitando que fevereiro desloque permanentemente a renovação. O fim do ciclo é exclusivo: uma despesa exatamente na data de renovação entra no novo ciclo. Na opção de dia fixo, se a vigência começar no meio do mês, o primeiro ciclo vai da data de início até a próxima ocorrência do dia escolhido. A renovação não apaga nem zera transações e não transporta excedentes.

Para orçamentos e relatórios por data, a data financeira de uma movimentação realizada é `settled_date` quando presente, ou `transaction_date`. O dashboard mostra o orçamento vigente hoje quando o mês selecionado é o atual; para outros meses, consulta o primeiro dia do mês. A API `/api/budgets` e o MCP aceitam uma data específica para consultar o ciclo que a contém. O retorno informa início, último dia, próxima renovação, estado, gasto, restante e percentual. Gastos e comparações de mês civil permanecem disponíveis separadamente; podem divergir dos gastos do ciclo de orçamento.

## Lixeira e metas

Excluir uma movimentação marca sua data de exclusão e retira seus efeitos dos saldos, orçamentos e relatórios ativos. Restaurar reativa o mesmo registro e não duplica valores. Transferências próprias entram e saem da lixeira em par. Uma compra de cartão excluída retira todo o seu parcelamento ativo. Se a fatura estava paga, o pagamento manual pareado é recalculado para o total remanescente; quando não resta compra, as duas pontas do pagamento vão à lixeira com a compra. A restauração recompõe os mesmos registros e valores. Assim, a correção de um pagamento manual pode alterar o saldo registrado da conta de origem; uma compra ainda não paga não altera caixa. Pagamentos de fatura e eventos de investimento não aceitam exclusão isolada. Uma despesa com reembolsos ativos só pode ser excluída depois de retirar os reembolsos da visão ativa. Excluir pagamento de conta a pagar reabre a obrigação; restaurar o pagamento a quita novamente se não houver novo pagamento.

Uma meta pode existir com caixa zero ou negativo. Valor desejado, contribuição acumulada e reserva são independentes. Contribuição é um registro manual de progresso e não movimenta conta ou cria receita; pode ser corrigida com lançamento negativo limitado ao acumulado. Reserva é uma parcela lógica do caixa declarada pelo usuário. Aumentos de reserva exigem caixa livre global suficiente; criar ou editar nome, prazo, valor desejado e contas acompanhadas não depende do saldo. O progresso usa contribuição acumulada; o que falta é `máximo(0, objetivo − contribuição)`.

O acompanhamento usa contas ativas que não são cartões. No modo *todas*, cada conta entra uma vez e saldos negativos também entram. No modo *selecionadas*, entram só as contas escolhidas. Obrigações e reservas não estão vinculadas a uma conta específica: quando há contas acompanhadas, a disponibilidade estimada subtrai delas o total global de contas abertas, parcelas abertas e reservas de todas as metas. É uma estimativa conservadora; disponibilidades exibidas em metas diferentes não devem ser somadas. A soma das reservas é contabilizada uma vez no caixa global.

## Calendário

O calendário usa a data efetiva de liquidação para entradas e saídas realizadas, ou a data prevista para movimentações pendentes. Receita menos despesa líquida de reembolsos forma o resultado de cada dia; transferências e aportes não são consumo nem receita. Contas a pagar e faturas aparecem como compromissos separados, sem entrar no resultado realizado. Vermelho indica resultado negativo, verde positivo e amarelo indica movimento sem resultado líquido ou compromisso pendente. Um dia sem dados fica neutro. O resumo mensal do calendário agrega dias do mês selecionado, sem contar dias vizinhos da grade.

Entretenimento é a soma das categorias marcadas pelo proprietário. A média só aparece quando existem pelo menos dois meses completos com registros. A projeção linear do mês exige dia 7 ou posterior e despesas em três dias distintos; quando aparece, é identificada como estimativa. Ausência de registros não prova ausência de gastos.

Essas regras aplicam escolhas de modelagem para este aplicativo. Os fundamentos de orçamento consultados no Banco Central e os limites de análise de investimentos da CVM estão em [Pesquisa](PESQUISA_FINANCAS_PESSOAIS.md).
