"""Explicit positive PostgreSQL wait limits for every application connection."""

from django.core.exceptions import ImproperlyConfigured


def postgres_options(environment):
    values = []
    for name, default in (("MACRO_DB_LOCK_TIMEOUT_MS", "5000"),
                          ("MACRO_DB_STATEMENT_TIMEOUT_MS", "15000")):
        raw = environment.get(name, default)
        if (type(raw) is not str or not raw.isascii() or not raw.isdecimal()
                or len(raw) > 6 or not 1 <= int(raw) <= 300_000):
            raise ImproperlyConfigured(f"{name} must be an integer from 1 to 300000 milliseconds")
        values.append(int(raw))
    lock, statement = values
    if lock >= statement:
        raise ImproperlyConfigured("Database lock timeout must be shorter than statement timeout")
    return {"connect_timeout": 5,
            "options": f"-c lock_timeout={lock}ms -c statement_timeout={statement}ms"}
