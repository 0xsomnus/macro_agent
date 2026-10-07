from django.conf import settings
from django.core.exceptions import PermissionDenied


def require_local_proof(*, synthetic=False):
    name = settings.DATABASES["default"]["NAME"]
    if (settings.SETTINGS_MODULE != "macro_agent.web.local_settings"
            or not getattr(settings, "MACRO_ENABLE_MONITORING_PROOF", False)
            or not (name.endswith("_dev") or name.startswith("test_"))):
        raise PermissionDenied("Monitoring proof requires local settings, a development/test database and MACRO_ENABLE_MONITORING_PROOF=1")
    if synthetic and not settings.MACRO_ALLOW_SYNTHETIC_SETUP:
        raise PermissionDenied("Fictional feed requires MACRO_ALLOW_SYNTHETIC_SETUP=1")
