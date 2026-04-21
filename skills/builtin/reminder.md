---
name: reminder
description: "Define lembretes pontuais e recorrentes enviados via Telegram"
version: "1.0.0"
author: "user"
trigger: ["lembra", "lembrete", "avisa", "avisa-me", "remind", "daqui a", "às ", "amanhã às", "todos os dias", "toda a semana", "agendar", "agenda para"]
requires: []
env:
  - DB_PATH
---

## Objetivo

Criar e gerir lembretes que serão enviados como mensagens Telegram na hora certa.
Usa a tabela `cron_jobs` com uma cron expression gerada a partir da hora indicada.

## Comandos Suportados

- `lembra-me às 9h de beber água` — lembrete diário às 09:00
- `avisa-me amanhã às 15:30 da reunião` — lembrete único
- `lembra-me todos os dias às 8h de tomar medicação`
- `lista lembretes` — mostrar lembretes activos
- `remove lembrete 5` — remover por id

## Regras de Parsing Temporal

- "às HH:MM" ou "às Hh" → hora exacta do dia
- "daqui a X minutos" → agora + X min
- "amanhã às HH:MM" → só corre uma vez amanhã
- "todos os dias às HH" → `0 HH * * *`
- "toda a semana à segunda às 9h" → `0 9 * * 1`
- Sem hora explícita → pedir clarificação

## Output

Confirmação com a cron expression gerada e hora de próxima execução,
em português europeu com formatação Markdown.

## Código de Referência

```python
import sqlite3
import os
import re
from datetime import date, datetime, timedelta

db_path = os.getenv("DB_PATH", "./data/assistant.db")
msg_lower = user_message.lower().strip()

DIAS_SEMANA = {
    "segunda": 1, "terça": 2, "terca": 2, "quarta": 3,
    "quinta": 4, "sexta": 5, "sábado": 6, "sabado": 6, "domingo": 0,
}

def parse_hora(texto):
    """Extrai (hora, minuto) de texto como '9h', '9:30', '14h30', '14:30'."""
    m = re.search(r"(\d{1,2})h(\d{2})?", texto)
    if m:
        return int(m.group(1)), int(m.group(2) or 0)
    m = re.search(r"(\d{1,2}):(\d{2})", texto)
    if m:
        return int(m.group(1)), int(m.group(2))
    return None, None

def extrair_mensagem(texto):
    """Remove tokens de hora/data para obter o texto do lembrete."""
    texto = re.sub(r"\b(lembra-me|lembra|avisa-me|avisa|remind)\b", "", texto, flags=re.IGNORECASE)
    texto = re.sub(r"\b(amanhã|todos os dias|toda a semana|daqui a \d+ minutos?)\b", "", texto, flags=re.IGNORECASE)
    texto = re.sub(r"\bàs?\s+\d{1,2}[h:]\d{0,2}\b", "", texto, flags=re.IGNORECASE)
    texto = re.sub(r"\bde\b|\bda\b|\bdo\b|\bpara\b", "", texto, flags=re.IGNORECASE)
    return texto.strip(" -–")

conn = sqlite3.connect(db_path)

try:
    # Listagem
    if any(k in msg_lower for k in ["lista lembrete", "mostrar lembrete", "que lembretes", "listar lembrete"]):
        rows = conn.execute(
            "SELECT id, skill_name, cron_expr, next_run, enabled "
            "FROM cron_jobs WHERE skill_name LIKE 'reminder_%' ORDER BY id"
        ).fetchall()
        if not rows:
            send_message("📭 Não tens lembretes configurados.")
        else:
            linhas = ["⏰ *Os teus lembretes:*\n"]
            for r in rows:
                estado = "✅" if r[4] else "⏸️"
                nr = r[3][:16] if r[3] else "n/d"
                nome = r[1].replace("reminder_", "").replace("_", " ")
                linhas.append(f"{estado} `{r[0]}` — {nome} (`{r[2]}`)\n   Próximo: {nr}")
            send_message("\n".join(linhas))

    # Remoção
    elif any(k in msg_lower for k in ["remove lembrete", "apaga lembrete", "cancela lembrete", "elimina lembrete"]):
        m = re.search(r"lembrete\s+(\d+)", msg_lower)
        if m:
            job_id = int(m.group(1))
            row = conn.execute("SELECT skill_name FROM cron_jobs WHERE id = ?", (job_id,)).fetchone()
            if row:
                conn.execute("DELETE FROM cron_jobs WHERE id = ?", (job_id,))
                conn.commit()
                send_message(f"🗑️ Lembrete `{job_id}` removido.")
            else:
                send_message(f"❌ Lembrete `{job_id}` não encontrado.")
        else:
            send_message("❓ Indica o id do lembrete a remover. Ex: `remove lembrete 3`")

    # Criação
    else:
        hora, minuto = parse_hora(msg_lower)

        if hora is None:
            # Tentar "daqui a X minutos"
            m = re.search(r"daqui a (\d+) minuto", msg_lower)
            if m:
                delta = timedelta(minutes=int(m.group(1)))
                target = datetime.now() + delta
                hora, minuto = target.hour, target.minute
            else:
                send_message(
                    "⏰ Não percebi a hora do lembrete. Exemplos:\n\n"
                    "• `lembra-me às 9h de beber água`\n"
                    "• `avisa-me amanhã às 15:30 da reunião`\n"
                    "• `lembra-me todos os dias às 8h de tomar medicação`\n"
                    "• `daqui a 30 minutos avisa-me do forno`"
                )
                conn.close()
                raise SystemExit

        # Determinar recorrência
        if "todos os dias" in msg_lower or "diariamente" in msg_lower:
            cron_expr = f"{minuto} {hora} * * *"
            recorrencia = "diariamente"
        elif "toda a semana" in msg_lower or "semanalmente" in msg_lower:
            dia_num = 1  # default segunda
            for nome, num in DIAS_SEMANA.items():
                if nome in msg_lower:
                    dia_num = num
                    break
            cron_expr = f"{minuto} {hora} * * {dia_num}"
            recorrencia = "semanalmente"
        elif "amanhã" in msg_lower:
            amanha = date.today() + timedelta(days=1)
            cron_expr = f"{minuto} {hora} {amanha.day} {amanha.month} *"
            recorrencia = f"uma vez, em {amanha.strftime('%d/%m/%Y')}"
        else:
            # Default: diário
            cron_expr = f"{minuto} {hora} * * *"
            recorrencia = "diariamente"

        texto_lembrete = extrair_mensagem(user_message) or "Lembrete"
        # Nome único baseado em timestamp
        import time
        skill_name = f"reminder_{int(time.time())}"

        # Garantir que a skill existe na tabela skills (FK)
        conn.execute(
            "INSERT OR IGNORE INTO skills (name, description, version, author, md_path) "
            "VALUES (?, ?, '1.0.0', 'user', '')",
            (skill_name, texto_lembrete[:200])
        )
        conn.execute(
            "INSERT INTO cron_jobs (skill_name, cron_expr, enabled) VALUES (?, ?, 1)",
            (skill_name, cron_expr)
        )
        conn.commit()

        hora_fmt = f"{hora:02d}:{minuto:02d}"
        send_message(
            f"⏰ Lembrete criado!\n\n"
            f"📝 *{texto_lembrete}*\n"
            f"🕐 Hora: *{hora_fmt}*\n"
            f"🔄 Recorrência: {recorrencia}\n"
            f"⚙️ Cron: `{cron_expr}`"
        )

finally:
    conn.close()
```

## Notas

- Os lembretes são guardados como entradas `cron_jobs` com `skill_name = 'reminder_<ts>'`
- O SchedulerManager carrega automaticamente os jobs ao arrancar
- Para lembretes únicos (amanhã), a cron expression limita o dia/mês — corre só uma vez
- O texto do lembrete é guardado como `description` na tabela `skills`
- Lembretes "daqui a X minutos" podem ter desvio de até 1 minuto (resolução de cron)
