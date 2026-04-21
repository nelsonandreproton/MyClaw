from datetime import datetime


def build_system_prompt(assistant_name: str, skills_list: list[str]) -> str:
    skills_str = (
        ", ".join(skills_list) if skills_list else "nenhuma skill carregada"
    )
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    return (
        f"És um assistente pessoal local chamado {assistant_name}.\n"
        "Corres no portátil do utilizador e tens acesso a ferramentas e skills.\n"
        "Responde sempre em português europeu, de forma concisa e direta.\n"
        "Quando precisas de executar código, gera código Python limpo e funcional.\n"
        "Nunca inventes dados — se não tens acesso a algo, diz claramente.\n"
        f"Data e hora atual: {now}\n"
        f"Skills disponíveis: {skills_str}"
    )


def build_skill_prompt(
    skill_md_content: str,
    user_request: str,
    history: list[dict[str, str]],
) -> list[dict[str, str]]:
    system = (
        "És um assistente que gera código Python funcional para executar skills.\n"
        "Gera APENAS o bloco de código Python entre ```python e ```. Sem explicações extra.\n"
        "O código deve ser completo e executável. Usa as funções injetadas disponíveis:\n"
        "  - send_message(text): envia mensagem para o utilizador via Telegram\n"
        "  - get_credential(service): obtém credencial encriptada do serviço\n"
        "  - save_credential(service, data): guarda credencial encriptada\n"
        "  - log(message): regista no log sem expor no Telegram\n\n"
        f"Contexto da skill:\n{skill_md_content}"
    )
    messages = [{"role": "system", "content": system}]
    messages.extend(history)
    messages.append({"role": "user", "content": user_request})
    return messages


def build_error_retry_prompt(
    original_messages: list[dict[str, str]],
    error: str,
    attempt: int,
) -> list[dict[str, str]]:
    retry_note = (
        f"O código gerado anteriormente falhou (tentativa {attempt}).\n"
        f"Erro: {error}\n\n"
        "Corrige o código e gera APENAS o bloco ```python ... ``` corrigido."
    )
    messages = list(original_messages)
    messages.append({"role": "user", "content": retry_note})
    return messages


def build_compression_prompt(conversation_text: str) -> str:
    return (
        "Resume a seguinte conversa em no máximo 3 frases em português europeu, "
        "preservando os factos e decisões mais importantes:\n\n"
        f"{conversation_text}"
    )
