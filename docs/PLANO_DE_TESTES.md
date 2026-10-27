# Testes executados e limites

Os testes financeiros usam `meu_financeiro_test`. `./scripts/test.sh` recusa outro nome de banco, aplica migrações apenas nesse banco e executa as fixtures com rollback. O teste MCP e a verificação visual deixam registros identificados como sintéticos somente no banco de teste. O banco pessoal recebeu apenas migrações aditivas e não foi usado para criar dados de teste.

## Resultado em 26/10/2026

| Verificação | Resultado observado |
| --- | --- |
| `./scripts/test.sh` | 40 testes passaram. Os novos casos cobriram mês civil, dias fixos 5/10/31, intervalos de 7/10/13 dias, 2 semanas, 2/6 meses, ano comum/bissexto, virada de ano, limites nas fronteiras, edição de regra, vigência futura, HTTP e histórico. Uma advertência de depreciação do Starlette não impediu a execução. |
| `npm --prefix frontend run build` | TypeScript e Vite concluídos. Vite avisou que o bundle principal supera 500 kB. |
| `./scripts/probe-mcp.sh` | 35 ferramentas descobertas por cliente MCP STDIO real; configuração renovável de 7 dias gravada e leitura de gasto/restante conferida com o domínio no PostgreSQL de teste. Os fluxos de compra manual, exclusão, restauração e persistência também passaram. |
| Interface no navegador com banco de teste | A lista de gastos e as faturas pagas exibiram Editar, Detalhes e Excluir. Uma compra sintética de R$ 100,00 foi editada para R$ 101,00 sem campo de motivo; as duas faturas passaram de R$ 94,95 para R$ 95,45. A exclusão reduziu cada fatura para R$ 44,95, e Desfazer recuperou R$ 95,45. |
| Perfil e tema no navegador de teste | O botão superior alterou claro/escuro imediatamente na tela de cartões sem abrir o perfil. O perfil refletiu a escolha, a opção do perfil alterou o tema, e o tema claro persistiu após recarga. A opção de seguir o sistema permaneceu disponível. |
| Serviço local | Após migração 0008 e reinício, a API de calendário respondeu HTTP 200. O favicon SVG compilado é idêntico ao ícone do lançador e foi servido com HTTP 200 e `image/svg+xml`. |
| Migração 0009 | Aplicada primeiro no banco de teste e depois no banco local após backup verificado. As linhas antigas de `budgets` e as movimentações permanecem; a nova tabela `budget_rules` versiona vigência e periodicidade. |
| Migração 0010 | Aplicada no banco de teste e no banco local após segundo backup. As seis regras iniciais do banco local foram marcadas como originadas da migração; uma regra nova antes da primeira renovação pode substituí-las. |
| Migração 0011 | Aplicada no banco de teste e no banco local após backup para renovar também limites mensais futuros após o último mês registrado. A primeira tentativa no banco de teste encontrou o limite de 32 caracteres do identificador Alembic e foi revertida; o identificador corrigido migrou e os 40 testes passaram. |
| Interface de orçamento | No banco local, a página exibiu início, fim e renovação de cada categoria. A edição de categoria existente carregou R$ 50,00 e a prévia para renovação no dia 10 mostrou primeiro ciclo de 26/10 a 09/11 e próxima renovação em 10/11. O formulário foi fechado sem salvar. |
| Consulta de ciclo na interface | A data 10/11 mostrou ciclo de 01/11 a 30/11 e gasto R$ 0,00 nas categorias do banco local; ao voltar para 26/10, os valores e o ciclo de outubro reapareceram. Nenhum limite pessoal foi alterado. |
| Backup/restauração | Backup antes da migração e backup final foram criados. O backup final foi restaurado em banco separado: versão Alembic e contagens de contas, categorias, movimentações e metas coincidiram com a origem. Os bancos temporários de restauração verificados foram removidos; os dumps permaneceram. |

## Limites da verificação

Não houve reinicialização física do computador nem teste de integração real com Claude, Gemini ou ChatGPT web. Nem todas as combinações de datas, faturas e planos recorrentes foram percorridas visualmente. Não houve restauração de backup sobre o banco pessoal nem exclusão física de dados financeiros.

As regras esperadas estão em [Regras financeiras](REGRAS_FINANCEIRAS.md). Execute `./scripts/test.sh` antes de uma nova atualização do banco pessoal.

## Verificação do ciclo de vida de categorias (26/10/2026)

`backend/tests/test_category_lifecycle.py` usa somente `meu_financeiro_test` e verifica: arquivamento de categoria vazia; restauração com o mesmo UUID, ícone e cor; despesa no ciclo de 10 dias; permanência no orçamento até o último dia e ausência no seguinte; gasto histórico intacto na categoria original, sem redistribuição; bloqueio de lançamento direto pelo domínio e pela API; retomada do orçamento e de novos lançamentos após restaurar; prazo padrão do mês civil sem orçamento; categoria com apenas gasto antigo; duas categorias com o mesmo ícone e cores automáticas diferentes; validação de cor manual; e rollback quando o banco falha durante arquivamento ou restauração. Asserções registram os valores esperados, como R$ 120,00 e R$ 40,00 separados, limite de R$ 300,00 e UUIDs preservados.

`scripts/probe_category_mcp.py` testa o protocolo MCP STDIO real em banco sintético: descoberta das ferramentas, prévia, confirmação exigida, arquivamento, recusa de novo lançamento, consulta do histórico e restauração. A migração 0012 foi exercida primeiro em banco vazio e depois sobre categorias e transação sintéticas já existentes. A suíte completa terminou com **47 testes aprovados**, e `npm run build` compilou a interface e o TypeScript.

No navegador, a cópia temporária do app em `127.0.0.1:8767` usou exclusivamente `meu_financeiro_test`: uma despesa sintética de R$ 120,00 continuou visível no orçamento, no gráfico de pizza e no histórico após arquivar. O seletor de novos lançamentos deixou de oferecer a categoria. A consulta do orçamento em 05/11 não a exibiu após o prazo de 04/11; a restauração trouxe de volta a mesma categoria e o limite de R$ 300,00, sem recriar o gasto. O servidor e o banco temporários foram encerrados. No app pessoal, só foram abertas e canceladas a prévia de arquivamento e a edição de cor, sem alterar categorias; o tema foi alternado e sua preferência original “Seguir o sistema” foi restaurada. Os ícones de lua e sol acompanharam os temas respectivos.
