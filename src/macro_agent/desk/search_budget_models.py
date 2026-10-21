"""Append-only search accounting, separate from inference and subscriptions.

No pricing contract is seeded, and these records do not enable a provider.
Unknown charges are represented by an unsettled full reservation, never zero.
"""

from django.conf import settings
from django.db import models
from django.db.models import Q


class SearchBudgetRoot(models.Model):
    id = models.PositiveSmallIntegerField(primary_key=True, default=1)

    class Meta:
        constraints = [models.CheckConstraint(condition=Q(id=1), name="desk_search_budget_singleton")]


class SearchPriceContract(models.Model):
    digest = models.CharField(primary_key=True, max_length=64)
    provider_id = models.CharField(max_length=32)
    maximum_charge_microusd = models.PositiveIntegerField()
    document = models.JSONField()
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    reviewed_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(digest__regex=r"^[0-9a-f]{64}$"),
                                   name="desk_search_price_digest"),
            models.CheckConstraint(condition=Q(maximum_charge_microusd__gte=1,
                maximum_charge_microusd__lte=100_000), name="desk_search_price_bound"),
        ]


class SearchReservation(models.Model):
    # An exact per-request identity is global, including across providers/months.
    id = models.UUIDField(primary_key=True, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    run = models.ForeignKey("macro_desk.ResearchRun", on_delete=models.PROTECT,
                           related_name="search_reservations")
    price_contract = models.ForeignKey(SearchPriceContract, on_delete=models.PROTECT)
    maximum_charge_microusd = models.PositiveIntegerField()
    month_start = models.DateField()
    created_at = models.DateTimeField()

    class Meta:
        constraints = [models.CheckConstraint(condition=Q(maximum_charge_microusd__gte=1,
            maximum_charge_microusd__lte=100_000), name="desk_search_reservation_bound")]


class SearchSettlement(models.Model):
    reservation = models.OneToOneField(SearchReservation, primary_key=True,
        on_delete=models.PROTECT, related_name="settlement")
    actual_charge_microusd = models.PositiveIntegerField()
    operator = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    provenance = models.JSONField()
    recorded_at = models.DateTimeField()

    class Meta:
        constraints = [models.CheckConstraint(condition=Q(actual_charge_microusd__lte=100_000),
            name="desk_search_settlement_bound")]
