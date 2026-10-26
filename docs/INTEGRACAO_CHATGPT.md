# ChatGPT web: viabilidade separada

**Estado em 26/10/2026:** não foi criada conexão do ChatGPT web com estes dados. O servidor atual funciona por STDIO local; uma aba do navegador não inicia esse processo diretamente. Não foi aberto túnel, porta pública nem integração que envie dados financeiros para serviços externos.

A documentação oficial da OpenAI agora oferece **Secure MCP Tunnel** para um servidor privado, inclusive um comando STDIO local. O cliente do túnel faz conexão HTTPS de saída com a OpenAI e encaminha chamadas para o processo MCP local. O ChatGPT web permite cadastrar um servidor personalizado com conexão **Tunnel**, sujeito a permissões do workspace e da organização Platform. Isso torna a integração tecnicamente possível quando o acesso e as permissões necessários existirem; a disponibilidade nesta conta não foi verificada.

Antes de configurar, será preciso decidir explicitamente quais ferramentas e dados financeiros poderão sair do computador, preparar credenciais com acesso restrito, associar o túnel ao workspace correto e verificar a autenticação e as aprovações de escrita. O cliente do túnel precisa permanecer ativo. Nenhum desses passos foi executado, pois o funcionamento local com Codex já atende à prioridade definida e a transmissão de dados privados requer uma decisão própria.

Fontes oficiais consultadas em 26/10/2026: [adicionar MCP personalizado ao ChatGPT](https://developers.openai.com/api/docs/guides/custom-mcp-server), [Secure MCP Tunnel](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels), [MCP na API](https://developers.openai.com/api/docs/guides/tools-connectors-mcp).
