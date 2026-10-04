from django.apps import AppConfig


class PersistenceConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "macro_agent.persistence"
    label = "macro_persistence"
    verbose_name = "Macro Agent publication records"
