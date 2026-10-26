# Backup e restauração

Execute `./scripts/backup.sh` na pasta do projeto. O comando cria um dump PostgreSQL em `~/.local/share/meu-financeiro/backups/`, com permissão `0600`, e imprime o caminho completo. O nome inclui data e hora. O script verifica a estrutura do dump com `pg_restore --list`.

Para testar ou recuperar um arquivo:

```bash
./scripts/restore.sh /caminho/completo/backup.dump
```

A restauração **sempre cria outro banco**, chamado `meu_financeiro_restore_<data>_<pid>`. Ela não substitui `meu_financeiro`. O script interrompe ao primeiro erro e remove o banco novo se a restauração falhar. Depois, confira tabelas e registros no banco restaurado antes de decidir qualquer substituição manual. Essa troca não é automatizada porque apagaria dados mais recentes.

O teste em 26/10/2026 criou um dump, restaurou em banco separado, leu as contagens e a versão do esquema e removeu só o banco temporário. O dump verificado permaneceu no diretório de backups. O arquivo está no mesmo disco que o banco: copie-o periodicamente para um meio externo protegido se quiser proteção contra falha do disco. Não há envio automático à nuvem nem criptografia do dump. Quem tiver acesso ao arquivo poderá ler os dados financeiros; mantenha as permissões e proteja a cópia externa.
