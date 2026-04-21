---
name: garmin_stats
description: "Obtém dados de saúde e atividade do Garmin Connect (sono, passos, FC, stress)"
version: "1.0.0"
author: "user"
trigger: ["garmin", "corrida", "sono", "passos", "frequencia cardiaca", "stress", "body battery", "atividade", "treino", "distancia", "saude"]
requires:
  - garminconnect
env: []
---

## Objetivo

Integrar com a API do Garmin Connect para obter dados de saúde do utilizador:
atividades recentes, sono, passos diários, frequência cardíaca e stress.

## Autenticação

As credenciais (email + password) são guardadas encriptadas na base de dados.
Usar `get_credential("garmin")` para as obter.
Se não existirem, pedir ao utilizador e guardar com `save_credential("garmin", data)`.

**Nunca expor as credenciais em mensagens ou logs.**

## Dados Disponíveis

- Atividades recentes (corridas, caminhadas, ciclismo) — `get_activities(0, 10)`
- Dados de sono (duração, fases, score) — `get_sleep_data(date)`
- Passos diários e distância — `get_steps_data(date)`
- Frequência cardíaca (repouso, média, máx) — `get_heart_rates(date)`
- Score de stress diário — `get_stress_data(date)`
- Body Battery — incluído nos dados de stress

## Input

Mensagem do utilizador em linguagem natural. Exemplos:
- "como dormi esta semana?"
- "quantos passos dei hoje?"
- "mostra o meu treino de ontem"
- "qual é o meu body battery?"

O código deve interpretar o pedido e mostrar os dados relevantes.

## Output

Resposta em português europeu formatada para Telegram (Markdown).
Incluir emojis relevantes. Ser conciso mas informativo.
Formato sugerido para dados numéricos: negrito para o valor, emoji temático.

## Código de Referência

```python
from garminconnect import Garmin
from datetime import date, timedelta

# 1. Obter credenciais
creds = get_credential("garmin")
if not creds:
    send_message(
        "🔐 Ainda não configuraste as credenciais do Garmin.\n\n"
        "Responde com:\n`garmin login email@exemplo.com A_tua_password`"
    )
else:
    email = creds["email"]
    password = creds["password"]

    try:
        client = Garmin(email, password)
        client.login()

        today = date.today()
        today_str = today.isoformat()

        # Dados de sono
        sleep = client.get_sleep_data(today_str)
        sleep_dto = sleep.get("dailySleepDTO", {})
        sleep_secs = sleep_dto.get("sleepTimeSeconds", 0)
        sleep_h = sleep_secs // 3600
        sleep_m = (sleep_secs % 3600) // 60
        sleep_score = sleep_dto.get("sleepScores", {}).get("overall", {}).get("value", "n/d")

        # Passos
        steps_data = client.get_steps_data(today_str)
        total_steps = steps_data[-1].get("steps", 0) if steps_data else 0

        # Frequência cardíaca
        hr_data = client.get_heart_rates(today_str)
        resting_hr = hr_data.get("restingHeartRate", "n/d")

        # Stress e Body Battery
        stress_data = client.get_stress_data(today_str)
        avg_stress = stress_data.get("avgStressLevel", "n/d")

        resposta = (
            f"📊 *Dados Garmin — {today.strftime('%d/%m/%Y')}*\n\n"
            f"😴 Sono: *{sleep_h}h {sleep_m}m* (score: {sleep_score})\n"
            f"👟 Passos: *{total_steps:,}*\n"
            f"❤️ FC repouso: *{resting_hr} bpm*\n"
            f"🧘 Stress médio: *{avg_stress}*"
        )
        send_message(resposta)

    except Exception as e:
        log(f"Garmin error: {e}")
        if "401" in str(e) or "login" in str(e).lower():
            send_message(
                "🔐 Sessão Garmin expirada. Volta a fazer login:\n"
                "`garmin login email@exemplo.com password`"
            )
        else:
            send_message(f"❌ Erro ao aceder ao Garmin Connect: {e}")
```

## Notas

- Re-autenticar automaticamente se a sessão expirar (erro 401)
- Tratar erros de rede com mensagem amigável (sem stack trace)
- Os dados do dia atual podem estar incompletos se for cedo (sync pendente)
- Para dados históricos, ajustar a data: `today - timedelta(days=1)` para ontem
- Formato de passos com separador de milhar: `f"{total_steps:,}"`
