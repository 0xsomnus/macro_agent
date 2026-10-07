from django.apps import AppConfig


class MonitoringConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "macro_agent.monitoring"
    label = "macro_monitoring"
    verbose_name = "Macro Agent capture proof"
