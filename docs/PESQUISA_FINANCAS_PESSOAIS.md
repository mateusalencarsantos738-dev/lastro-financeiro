# Pesquisa: finanças pessoais

**Consulta:** 26/10/2026. **Escopo:** decisões de modelagem para uso pessoal no Brasil; este material é educacional e não constitui recomendação de investimento.

## Síntese

O aplicativo precisa transformar registros em um orçamento que possa ser comparado com o realizado. O Banco Central recomenda registrar receitas e despesas, agrupá-las, projetar o que ainda será gasto e avaliar o resultado; a estimativa pode melhorar conforme o histórico se forma. Por isso, o sistema deve preservar os lançamentos originais e explicitar quando um número é realizado, pendente ou estimado.

O orçamento não é um limite que impede registrar a realidade. É um instrumento de planejamento: compara o limite definido pelo proprietário com o consumo reconhecido. Receitas esperadas ajudam a planejar, mas não aumentam o saldo de dinheiro recebido.

## Conceitos e decisões práticas

| Conceito | Interpretação no produto |
| --- | --- |
| Receita recorrente ou extraordinária | Entrada de recursos própria, reconhecida na data da transação; recorrência é um atributo opcional, não uma nova entrada automática. |
| Despesa fixa ou variável, essencial ou discricionária | Atributos de classificação independentes da categoria. A categoria diz onde ocorreu; esses atributos ajudam a analisar comportamento. |
| Fluxo de caixa | Entradas e saídas de dinheiro por conta e período. Transferências internas são neutras no total consolidado. |
| Saldo disponível | Saldo em contas líquidas, com obrigações vencidas/futuras apresentadas à parte. Investimentos e reservas não são automaticamente dinheiro livre. |
| Orçamento mensal | Limite por categoria e período, comparado ao consumo reconhecido no período. Saldo restante = limite − despesas líquidas de estornos/reembolsos vinculados. |
| Planejado, realizado e pendente | Estados distintos. Projeções não entram em totais realizados; compromissos futuros não são despesas já pagas. |
| Parcelamento e cartão | Compra é consumo na data da compra; parcelas são obrigações programadas. Pagamento da fatura liquida obrigação e não repete o consumo. |
| Reembolso/estorno | Evento vinculado à origem que reduz o valor líquido da despesa; não é renda. Correções preservam trilha de auditoria. |
| Aporte/resgate | Troca de dinheiro por ativo (ou o inverso), sem criar despesa ou receita de consumo. Taxas são despesas; rendimentos recebidos e variação do preço são eventos distintos. |
| Patrimônio bruto/líquido | Ativos menos passivos em uma data. Transferências internas não mudam patrimônio. O valor atual manual tem data e origem declaradas; sem avaliação não se inventa cotação. |
| Meta/reserva | Afeta a parcela livre para outros fins, mas não subtrai ativos do patrimônio. Uma unidade monetária não pode ser contada em mais de uma reserva. |
| Inflação e poder de compra | Exigem série externa e período comparável. Não fazem parte do saldo nominal e não serão estimados sem fonte, data e índice explícitos. |
| Qualidade do dado | Origem, datas, status, vínculo com lançamento original e completude definem confiança. Lacunas devem aparecer em vez de gerar falsa precisão. |

## Erros de modelagem que a pesquisa evita

1. Somar transferências próprias como receita e despesa distorce renda, consumo e patrimônio.
2. Lançar a compra no cartão e o pagamento da fatura como consumo duplica a despesa.
3. Contabilizar valor total e parcelas futuras em relatórios de consumo duplica a compra. O produto exibirá impacto do consumo e cronograma de obrigações em visões separadas.
4. Tratar aporte como despesa reduz artificialmente o patrimônio; tratar resgate como renda o aumenta.
5. Misturar previsão, conta pendente e dinheiro liquidado faz o saldo parecer maior ou menor do que realmente é.
6. Projetar o mês linearmente com poucos dias ou um mês atípico pode induzir a erro; projeções exigem amostra mínima e rótulo de estimativa.
7. Rentabilidade não pode ser calculada corretamente sem fluxos, datas e avaliações consistentes. Valor atual manual será identificado como estimativa informada pelo usuário.
8. Valores monetários binários de ponto flutuante acumulam erros. Persistência e domínio usam decimais; apresentação usa formatação brasileira.

## Regras de projeção propostas

- Exibir projeção mensal somente após pelo menos 7 dias corridos com dados e 3 dias distintos com despesas na categoria/período; a fórmula inicial é `gasto acumulado / dias decorridos × dias do mês`.
- Marcar o resultado como estimativa e mostrar a base temporal. O usuário pode desativar a projeção.
- Comparações históricas usam meses completos e o mesmo critério de competência. Se houver menos de dois períodos comparáveis, informar amostra insuficiente.
- Não inferir inflação, cotação ou rentabilidade futura.

## Fontes consultadas

- Banco Central, [Caderno de Educação Financeira — Gestão de Finanças Pessoais](https://www.bcb.gov.br/pre/pef/port/caderno_cidadania_financeira.pdf), consultado em 26/10/2026. Base de orçamento, registro, planejamento e avaliação.
- Banco Central, [Orçamento Pessoal](https://www.bcb.gov.br/pre/pef/port/folder_serie_II_orcamento_pessoal.pdf), consultado em 26/10/2026. Orienta registrar e agrupar receitas e despesas e usar o orçamento para planejar.
- Banco Central, [FAQ — Educação Financeira](https://www.bcb.gov.br/meubc/faqs/s/educacao-financeira-sub), consultado em 26/10/2026. Define orçamento pessoal e a utilidade de projetar gastos.
- CVM/Portal do Investidor, [Risco e relação risco-retorno](https://www.gov.br/investidor/pt-br/investir/antes-de-investir/entenda-as-caracteristicas-dos-investimentos/risco-e-a-relacao-risco-x-retorno), consultado em 26/10/2026. Rentabilidade é expectativa e risco não desaparece.
- CVM/Portal do Investidor, [Evitando problemas](https://www.gov.br/investidor/pt-br/investir/cuidados-ao-investir/evitando-problemas), consultado em 26/10/2026. Riscos de mercado, crédito e liquidez e limites da diversificação.

## Limitações

Não há sincronização bancária nem cotações nesta primeira versão. A pessoa mantém dados manualmente. Conceitos de orçamento são recomendações gerais de educação financeira, não obrigações legais nem regras universais.
