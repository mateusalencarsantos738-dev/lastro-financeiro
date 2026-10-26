# Claude Desktop

**Estado nesta máquina:** Claude Desktop e Claude Code não estavam instalados em 26/10/2026. O servidor MCP foi testado com o cliente oficial Python, mas não há teste ponta a ponta no Claude. Nenhuma configuração do Claude foi alterada.

A documentação atual da Anthropic oferece Claude Desktop para Ubuntu 22.04+ em beta e explica como inspecionar servidores MCP locais em **Settings → Desktop app → Manage → Local MCP servers**. A integração local usa o processo STDIO; um conector remoto do Claude é outro mecanismo e sai da infraestrutura da Anthropic, não do computador.

Depois de instalar e abrir o Claude Desktop uma vez, configure um servidor local apontando para o comando absoluto abaixo, preservando as outras entradas do arquivo de configuração do cliente:

```json
{
  "mcpServers": {
    "meu-financeiro": {
      "command": "/home/teus/Documents/ChatGPT/lastro-financeiro/scripts/run-mcp.sh"
    }
  }
}
```

A localização do arquivo de configuração em Linux e o suporte dessa versão específica devem ser confirmados no cliente instalado antes de editar. Não copie o objeto acima por cima de um JSON existente. Reinicie o Claude Desktop, confira a lista de ferramentas e faça primeiro uma consulta como `finance_get_balances`. Uma gravação só deve ser testada com dados sintéticos e uma conexão temporária ao banco de teste.

Fontes oficiais consultadas em 26/10/2026: [instalar Claude Desktop](https://support.claude.com/en/articles/10065433-install-claude-desktop), [servidores MCP locais](https://support.claude.com/en/articles/10949351-getting-started-with-local-mcp-servers-on-claude-desktop), [diferença para conectores remotos](https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp).
