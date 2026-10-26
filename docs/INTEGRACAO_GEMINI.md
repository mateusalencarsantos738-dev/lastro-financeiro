# Gemini CLI

**Estado nesta máquina:** o comando `gemini` não estava instalado em 26/10/2026. A integração abaixo segue a documentação oficial, mas ainda não foi executada no cliente Gemini.

O Gemini CLI aceita servidores MCP STDIO por `mcpServers` no seu `settings.json`. Preserve o restante do arquivo e acrescente uma entrada como esta:

```json
{
  "mcpServers": {
    "meu-financeiro": {
      "command": "/home/teus/Documents/ChatGPT/lastro-financeiro/scripts/run-mcp.sh",
      "trust": false
    }
  }
}
```

Use hífen no nome do servidor. A documentação alerta que sublinhados podem atrapalhar regras de permissão baseadas no nome. Deixe `trust` como `false` para revisar as chamadas de ferramentas. Depois de instalar o cliente, use uma pasta confiável e execute `gemini mcp list`; o CLI só testa e mostra servidores STDIO como conectados em pastas confiáveis. Confira as ferramentas com `/mcp list` e faça uma leitura antes de qualquer escrita. Para gravações de ensaio, use apenas o banco `meu_financeiro_test`.

Fonte oficial consultada em 26/10/2026: [MCP servers with Gemini CLI](https://geminicli.com/docs/tools/mcp-server/).
