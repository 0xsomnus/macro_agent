"""One shared private-model admission allowance across current research roles.

Callers protect owner/thesis, then this anchor, before sampling admission time.
Capture has no dependency on this analytical allowance. Charges remain unknown
unless reported; a call/token limit is not a guaranteed dollar ceiling.
"""

from datetime import timedelta

from .models import CompilationAttempt, CompilationBudget


def lock_model_budget():
    CompilationBudget.objects.get_or_create(pk=1)
    return CompilationBudget.objects.select_for_update().get(pk=1)


def capacity_available(owner_id, at, configuration):
    from macro_agent.monitoring.models import NewsAnalysisAttempt
    groups = [model.objects.filter(created_at__gt=at - timedelta(days=1))
              for model in (CompilationAttempt, NewsAnalysisAttempt)]
    return (sum(rows.count() for rows in groups) < configuration["aggregate_attempts_per_day"]
            and sum(rows.filter(owner_id=owner_id).count() for rows in groups) < configuration["owner_attempts_per_day"]
            and not any(rows.filter(owner_id=owner_id, result__isnull=True, deadline_at__gt=at).exists()
                        for rows in groups))
