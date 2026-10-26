"""Define aprovação automática só para leituras; escritas continuam pedindo aprovação."""

import os
import shutil
import sys
import tomllib
from datetime import datetime
from pathlib import Path

config = Path.home() / ".codex/config.toml"
text = config.read_text()
marker = '[mcp_servers.meu_financeiro]\n'
if text.count(marker) != 1:
    raise SystemExit("Configuração MCP não encontrada exatamente uma vez; arquivo preservado")
section = text.split(marker, 1)[1].split("\n[", 1)[0]
if "default_tools_approval_mode" in section:
    raise SystemExit("Política MCP já configurada; arquivo preservado")
backup = config.with_name(config.name + ".backup-approvals-" + datetime.now().strftime("%Y%m%d_%H%M%S"))
shutil.copy2(config, backup)
os.chmod(backup, 0o600)
new_text = text.replace(marker, marker + 'default_tools_approval_mode = "writes"\n', 1)
tomllib.loads(new_text)
temp = config.with_suffix(".toml.tmp-meu-financeiro")
temp.write_text(new_text)
os.chmod(temp, 0o600)
os.replace(temp, config)
print(f"Política writes configurada para meu_financeiro; backup: {backup}")
