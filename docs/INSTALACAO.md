# Instalação e operação local

Este procedimento foi validado em Ubuntu 26.04.1, GNOME/Wayland, Python 3.14.4, Node 24.18 e PostgreSQL 18.6. O projeto já está instalado nesta máquina. Para reinstalar dependências ou atualizar o esquema, entre na pasta do projeto e execute `./scripts/install.sh`. O instalador preserva o cluster privado existente e não substitui um lançador ou serviço de outro aplicativo.

## O que foi instalado

- Ambiente Python: `.venv/` dentro do projeto; frontend compilado em `frontend/dist/`.
- Banco privado: `~/.local/share/meu-financeiro/postgres/data`. O socket fica em `postgres/socket`, porta interna 55432, sem escuta TCP.
- Segredos: `~/.config/meu-financeiro/.env`, `admin-password` e `app-password`, com acesso restrito ao usuário.
- Serviços da sessão: `~/.config/systemd/user/meu-financeiro-postgres.service` e `meu-financeiro.service`.
- Lançador: `~/.local/share/applications/meu-financeiro.desktop`; ícone do projeto em `assets/icons/meu-financeiro.svg`. O favicon compilado em `frontend/dist/favicon.svg` usa o mesmo desenho.

Ao abrir pelo menu, o serviço de banco inicia primeiro, a API é iniciada em `http://127.0.0.1:8765` e o navegador abre a interface. Reabrir o ícone reutiliza o processo existente. O servidor MCP inicia o banco por conta própria quando necessário, mesmo com a interface fechada.

## Comandos úteis

```bash
systemctl --user status meu-financeiro.service meu-financeiro-postgres.service
./scripts/open-app.sh
./scripts/stop-app.sh
journalctl --user -u meu-financeiro.service -n 80 --no-pager
journalctl --user -u meu-financeiro-postgres.service -n 80 --no-pager
```

`stop-app.sh` encerra só a API; o banco privado pode continuar para atender ao MCP. Se a interface não abrir, confira os dois serviços e teste `curl http://127.0.0.1:8765/api/overview`. Falha de migração exige executar `./scripts/install.sh`; a abertura comum não aplica migrações automaticamente. Se a senha local for perdida, recupere os arquivos de configuração protegidos junto com o banco; não recrie um segredo novo sobre o mesmo cluster.

## Desenvolvimento e testes

`./scripts/test.sh` usa exclusivamente `meu_financeiro_test` e recusa o banco pessoal. `npm --prefix frontend run build` compila a interface. `./scripts/probe-mcp.sh` executa chamadas reais por STDIO no banco de teste e deixa registros sintéticos identificados ali. O teste visual também pode usar uma instância temporária na porta 8766 com `DATABASE_URL` apontando ao banco de teste.

O banco do sistema em `/var/lib/postgresql/18/main` não foi usado nem alterado. O cluster do aplicativo pertence ao usuário local e não depende de Docker.

Nome, e-mail opcional, foto e aparência ficam no armazenamento local do navegador usado para abrir `127.0.0.1:8765`. Limpar os dados desse navegador remove essas preferências, sem alterar transações e contas do PostgreSQL. A foto aceita PNG, JPEG ou WebP de até 10 MB e fica no IndexedDB do navegador, sem envio a serviços externos.
