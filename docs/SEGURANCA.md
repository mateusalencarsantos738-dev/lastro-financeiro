# Segurança e privacidade

O banco fica em um cluster PostgreSQL próprio do usuário, acessível por socket Unix em diretório `0700`. O usuário `finance_app` não é administrador. Senhas e DSN ficam em `~/.config/meu-financeiro/` com permissões restritas; não entram no Git. A API escuta só em `127.0.0.1:8765`, não habilita CORS aberto e recusa uma origem de navegador diferente da própria aplicação. O MCP usa STDIO e só expõe ferramentas financeiras tipadas, sem SQL, shell ou leitura genérica de arquivos.

Esses controles evitam exposição direta na rede e acesso casual de outros usuários locais. **Processos que já rodam sob a conta do proprietário continuam dentro da fronteira de confiança.** A API local não exige login e uma chamada sem cabeçalho `Origin` feita por um processo local pode alcançar suas rotas. A proteção contra uso indevido da própria conta depende da segurança do sistema e das permissões dessa sessão. O cliente de IA pode enviar ao fornecedor os dados retornados por ferramentas, conforme a configuração do cliente; o servidor financeiro não faz envio externo por conta própria.

Operações financeiras validam IDs, tipo, categoria, conta e centavos no backend. Transferência, compra parcelada, pagamento de fatura e correção usam transações do PostgreSQL. Chaves de idempotência evitam gravação duplicada nas rotas que as aceitam. Correções comuns exigem motivo, confirmação e versão atual, e são registradas em `transaction_revisions`. Não há ferramenta MCP para executar código, abrir portas ou exportar o banco inteiro.

Backups locais são dumps com permissão `0600`, **sem criptografia própria**. O diretório e o arquivo precisam ser protegidos também em qualquer cópia externa. Não há túnel, proxy público, integração bancária, ordem de investimento ou envio automático para a nuvem.

Para investigar falhas, use `journalctl --user -u meu-financeiro.service` e o serviço do PostgreSQL. Evite publicar logs junto com DSN, nomes de contas ou movimentações. Se houver suspeita de perda de dados, preserve os arquivos antes de restaurar; o procedimento padrão restaura sempre em outro banco.
