---
name: file_monitor
description: "Monitoriza ficheiros ou directorias e notifica quando há alterações"
version: "1.0.0"
author: "user"
trigger: ["monitoriza", "vigia", "watch", "avisa quando", "notifica quando", "alerta ficheiro", "ficheiro mudou", "pasta mudou"]
requires: []
env:
  - DB_PATH
---

## Objetivo

Gerir watchs de ficheiros e directorias: adicionar, listar e remover entradas
na tabela `file_watches`. O watchdog em background (WatchdogManager) usa estas
entradas para detetar alterações e enviar notificações via Telegram.

## Comandos Suportados

- `monitoriza /caminho/para/ficheiro` — adicionar watch
- `vigia /home/user/docs/*.log` — adicionar watch com glob
- `lista watches` / `que ficheiros estás a vigiar` — listar watches activos
- `remove watch 3` / `para de vigiar /caminho` — remover por id ou caminho

## Input

Mensagem em linguagem natural com o caminho do ficheiro/directoria a monitorizar,
ou pedido de listagem/remoção.

## Output

Confirmação da operação em português europeu com formatação Markdown para Telegram.

## Código de Referência

```python
import sqlite3
import os
import re

db_path = os.getenv("DB_PATH", "./data/assistant.db")
msg_lower = user_message.lower().strip()

def listar_watches(conn):
    rows = conn.execute(
        "SELECT id, path, pattern, active FROM file_watches ORDER BY id"
    ).fetchall()
    if not rows:
        send_message("👁️ Não há ficheiros a ser monitorizados de momento.")
        return
    linhas = ["👁️ *Ficheiros monitorizados:*\n"]
    for r in rows:
        estado = "✅" if r[3] else "⏸️"
        padrao = f" `{r[2]}`" if r[2] else ""
        linhas.append(f"{estado} `{r[0]}` — `{r[1]}`{padrao}")
    send_message("\n".join(linhas))

def adicionar_watch(conn, path, pattern=None):
    # Verificar se já existe
    exists = conn.execute(
        "SELECT id FROM file_watches WHERE path = ?", (path,)
    ).fetchone()
    if exists:
        send_message(f"👁️ Já estou a monitorizar `{path}` (id: {exists[0]}).")
        return
    conn.execute(
        "INSERT INTO file_watches (path, pattern, active) VALUES (?, ?, 1)",
        (path, pattern)
    )
    conn.commit()
    row = conn.execute(
        "SELECT id FROM file_watches WHERE path = ?", (path,)
    ).fetchone()
    send_message(
        f"✅ A monitorizar `{path}`.\n"
        f"ID: `{row[0]}` — serás notificado quando o ficheiro for alterado."
    )

def remover_watch(conn, ref):
    # ref pode ser id numérico ou caminho
    if ref.isdigit():
        row = conn.execute(
            "SELECT id, path FROM file_watches WHERE id = ?", (int(ref),)
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT id, path FROM file_watches WHERE path = ?", (ref,)
        ).fetchone()
    if not row:
        send_message(f"❌ Watch `{ref}` não encontrado.")
        return
    conn.execute("DELETE FROM file_watches WHERE id = ?", (row[0],))
    conn.commit()
    send_message(f"🗑️ Removido watch `{row[0]}` — `{row[1]}`.")

conn = sqlite3.connect(db_path)

try:
    # Listagem
    if any(k in msg_lower for k in ["lista", "listar", "mostrar", "que ficheiros", "estás a vigiar", "a monitorizar"]):
        listar_watches(conn)

    # Remoção
    elif any(k in msg_lower for k in ["remove", "apaga", "para de vigiar", "stop watch", "elimina watch"]):
        # Tentar extrair id ou caminho
        m = re.search(r"watch\s+(\d+)", msg_lower)
        if m:
            remover_watch(conn, m.group(1))
        else:
            m = re.search(r"(?:remove|apaga|para de vigiar|elimina watch)\s+(.+)", msg_lower)
            if m:
                remover_watch(conn, m.group(1).strip())
            else:
                send_message("❓ Especifica o id ou o caminho do watch a remover.\nEx: `remove watch 3` ou `para de vigiar /tmp/log.txt`")

    # Adição
    else:
        # Extrair caminho da mensagem (primeiro token que começa por / ou ~)
        m = re.search(r"([~/][^\s]+)", user_message)
        if m:
            path = m.group(1).strip()
            # Verificar se tem glob
            pattern = None
            if "*" in path or "?" in path:
                import os.path
                pattern = os.path.basename(path)
                path = os.path.dirname(path)
            adicionar_watch(conn, path, pattern)
        else:
            send_message(
                "👁️ Para monitorizar um ficheiro ou directoria, indica o caminho completo.\n\n"
                "Exemplos:\n"
                "• `monitoriza /var/log/syslog`\n"
                "• `vigia /home/user/documentos/`\n"
                "• `lista watches`\n"
                "• `remove watch 2`"
            )
finally:
    conn.close()
```

## Notas

- A tabela `file_watches` é criada pelas migrations e gerida pelo WatchdogManager
- Este skill apenas gere as entradas na BD; a deteção de alterações é feita em background
- Caminhos relativos são aceites mas recomenda-se sempre caminhos absolutos
- O WatchdogManager verifica a tabela ao arrancar e após cada alteração via este skill
