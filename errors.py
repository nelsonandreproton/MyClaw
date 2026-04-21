class AssistantError(Exception):
    pass


class LLMError(AssistantError):
    pass


class SkillError(AssistantError):
    pass


class CredentialError(AssistantError):
    pass


class SchedulerError(AssistantError):
    pass
