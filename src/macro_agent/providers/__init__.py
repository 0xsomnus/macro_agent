"""Replaceable model transports, independent of Django and domain authority."""

from .nanogpt import NanoGPT, ProviderError, is_explicit_model_id
from .compatible import OpenRouter, CheaperInference

PROVIDERS = {"nanogpt": NanoGPT, "openrouter": OpenRouter, "cheaperinference": CheaperInference}
PROVIDER_IDS = tuple(PROVIDERS)


def create_provider(provider_id, api_key, **configuration):
    if type(provider_id) is not str or provider_id not in PROVIDERS:
        raise ProviderError("invalid_configuration")
    return PROVIDERS[provider_id](api_key, **configuration)


__all__ = ["NanoGPT", "OpenRouter", "CheaperInference", "ProviderError",
           "is_explicit_model_id", "create_provider", "PROVIDER_IDS"]
