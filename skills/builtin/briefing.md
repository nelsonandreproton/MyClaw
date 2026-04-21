---
name: briefing
description: "Briefing diário matinal com resumo de conversas recentes e o dia atual"
version: "1.0.0"
author: "user"
cron: "0 8 * * 1-5"
trigger: ["briefing", "resumo do dia", "bom dia", "morning"]
requires: []
env:
  - DB_PATH
---

## Objetivo

Gera um briefing matinal enviado automaticamente nos dias úteis às 8h00.
Inclui a data de hoje, um resumo das últimas conversas e uma saudação motivacional.

## Contexto

Este código corre no arranque do dia. Deve ser conciso, informativo e positivo.
O utilizador quer saber em 30 segundos o que aconteceu e o que tem pela frente.

## Input

Nenhum input do utilizador — é executado pelo cron scheduler.
Quando ativado manualmente por mensagem, pode receber um pedido específico
(ex: "briefing de hoje", "resumo de ontem").

## Output

Mensagem formatada para Telegram com Markdown, com:
- Saudação com data e dia da semana em português europeu
- Resumo das últimas 5 interações com o assistente
- Encerramento motivacional curto

## Código de Referência

```python
import sqlite3
import os
from datetime import date, datetime

# Abrir a base de dados diretamente (leitura)
db_path = os.getenv("DB_PATH", "./data/assistant.db")
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row

# Data de hoje em português europeu
dias = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira",
        "sexta-feira", "sábado", "domingo"]
hoje = date.today()
dia_semana = dias[hoje.weekday()]
data_str = hoje.strftime("%d/%m/%Y")

# Últimas 5 mensagens do utilizador (não sistema)
cursor = conn.execute(
    "SELECT role, content, created_at FROM messages "
    "WHERE role IN ('user', 'assistant') ORDER BY id DESC LIMIT 10"
)
msgs = list(reversed(cursor.fetchall()))
conn.close()

linhas = [f"🌅 *Bom dia! — {dia_semana}, {data_str}*\n"]

if msgs:
    linhas.append("*Resumo recente:*")
    # Mostrar apenas as últimas 3 trocas
    for m in msgs[-6:]:
        prefixo = "👤" if m["role"] == "user" else "🤖"
        texto = m["content"]
        if len(texto) > 120:
            texto = texto[:117] + "…"
        linhas.append(f"{prefixo} {texto}")
else:
    linhas.append("_Sem conversas recentes._")

linhas.append("\n💪 Que tenhas um excelente dia!")

send_message("\n".join(linhas))
```

## Notas

- Executar de segunda a sexta às 8h00 (`0 8 * * 1-5`)
- Se correr ao fim de semana por trigger manual, adaptar a saudação
- Nunca mostrar conteúdo sensível (credenciais, dados de saúde) no briefing
- Manter mensagem curta — máximo 2000 caracteres
