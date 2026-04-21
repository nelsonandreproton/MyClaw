---
name: self_skill
description: "Cria novas skills dinamicamente usando o LLM — o assistente aprende novas capacidades"
version: "1.0.0"
author: "user"
trigger: ["cria skill", "cria uma skill", "nova skill", "aprende a", "ensina-te a", "cria um script", "adiciona capacidade", "cria automação"]
requires: []
env:
  - SKILLS_PATH
---

## Objetivo

Usar o LLM para gerar uma nova skill `.md` a partir de uma descrição em linguagem natural.
O utilizador descreve o que quer e o assistente gera o ficheiro `.md` completo,
mostra um preview e aguarda confirmação antes de guardar.

## Fluxo

1. Utilizador descreve a skill ("cria uma skill que me diz o tempo em Lisboa")
2. LLM gera o ficheiro `.md` completo com frontmatter + código Python
3. Assistente mostra o preview e pede confirmação
4. Se confirmado, guarda em `SKILLS_PATH/user/` e regista na BD

## Input

Descrição em linguagem natural da skill desejada.
Exemplos:
- "cria uma skill que consulta o preço do Bitcoin"
- "aprende a fazer resumos de URLs"
- "cria um script que me mostra os processos do sistema"

## Output

Preview da skill gerada + pedido de confirmação em português europeu.
Após confirmação: confirmação de criação com triggers gerados.

## Código de Referência

```python
import os
import re

skills_path = os.getenv("SKILLS_PATH", "./skills")
user_skills_dir = os.path.join(skills_path, "user")
os.makedirs(user_skills_dir, exist_ok=True)

# Extrair descrição (remover o trigger)
descricao = re.sub(
    r"^(cria\s+(uma?\s+)?skill|nova skill|aprende a|ensina-te a|cria\s+(um\s+)?script|adiciona capacidade|cria automação)\s*",
    "",
    user_message,
    flags=re.IGNORECASE
).strip()

if not descricao:
    send_message(
        "🧠 Descreve o que queres que eu aprenda. Exemplos:\n\n"
        "• `cria uma skill que consulta o preço do Bitcoin`\n"
        "• `aprende a fazer resumos de URLs`\n"
        "• `cria um script que mostra os processos activos`"
    )
else:
    prompt = f"""Gera um ficheiro de skill para um assistente pessoal Python com o seguinte formato EXACTO:

---
name: <nome_sem_espacos_em_lowercase>
description: "<descrição curta em português>"
version: "1.0.0"
author: "user"
trigger: ["<palavra1>", "<palavra2>", "<palavra3>"]
requires: []
env: []
---

## Objetivo

<Descrição clara do objectivo>

## Código de Referência

```python
# Código Python que usa estas funções injectadas:
# - send_message(texto) — envia mensagem Telegram
# - user_message — string com a mensagem do utilizador
# - log(texto) — regista no log do sistema
# Não usar subprocess, socket, ou input()
# Importar apenas módulos da stdlib ou os listados em requires

<código aqui>
```

A skill deve fazer: {descricao}

Responde APENAS com o ficheiro .md completo, sem explicações adicionais."""

    # Chamar o LLM via contexto injectado
    resposta_llm = llm_chat([{{"role": "user", "content": prompt}}], temperature=0.3)

    # Extrair o bloco markdown
    md_content = resposta_llm.strip()
    if md_content.startswith("```"):
        md_content = re.sub(r"^```\w*\n?", "", md_content)
        md_content = re.sub(r"\n?```$", "", md_content)

    # Extrair nome da skill para o nome do ficheiro
    m = re.search(r"^name:\s*(\S+)", md_content, re.MULTILINE)
    skill_name = m.group(1) if m else "custom_skill"
    file_path = os.path.join(user_skills_dir, f"{skill_name}.md")

    # Preview truncado
    preview = md_content if len(md_content) <= 2000 else md_content[:1997] + "…"

    send_message(
        f"🧠 *Nova skill gerada: `{skill_name}`*\n\n"
        f"```\n{preview}\n```\n\n"
        f"Responde com *sim* para guardar em `skills/user/{skill_name}.md`, "
        f"ou *não* para cancelar."
    )

    # Guardar temporariamente para confirmar na próxima mensagem
    # (usar credentials store como estado temporário)
    import json
    save_credential("_pending_skill", {{"name": skill_name, "content": md_content, "path": file_path}})
```

## Notas

- A confirmação "sim"/"não" deve ser tratada por um skill separado ou pelo handler geral
- O LLM usa temperatura 0.3 para código mais determinístico
- Skills geradas ficam em `skills/user/` e são carregadas automaticamente ao reiniciar
- O utilizador pode editar o ficheiro `.md` manualmente antes de reiniciar
- `llm_chat` é injectado no contexto de execução da sandbox (via `skill_runner`)
- Nunca executar código gerado pelo LLM sem revisão — apenas guardar o ficheiro
