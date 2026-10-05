from django.apps import AppConfig


class PositionsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "macro_agent.positions"
    label = "macro_positions"
    verbose_name = "Macro Agent paper positions"
