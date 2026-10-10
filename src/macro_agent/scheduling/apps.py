from django.apps import AppConfig


class SchedulingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "macro_agent.scheduling"
    label = "macro_scheduling"
    verbose_name = "Macro Agent internal scheduling"
