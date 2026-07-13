"""Alan bazlı güvenlik kataloglarının tek kayıt noktası."""

from cleaning_safety_catalog import CLEANING_ALIASES, CLEANING_SUBSTANCES
from cosmetic_safety_catalog import COSMETIC_ALIASES, COSMETIC_INGREDIENTS
from food_safety_catalog import FOOD_ADDITIVES, FOOD_ALIASES

SAFETY_CATALOGS = {
    "food": FOOD_ADDITIVES,
    "cleaning": CLEANING_SUBSTANCES,
    "cosmetic": COSMETIC_INGREDIENTS,
}

SAFETY_ALIASES_BY_DOMAIN = {
    "food": FOOD_ALIASES,
    "cleaning": CLEANING_ALIASES,
    "cosmetic": COSMETIC_ALIASES,
}


def combined_catalog() -> dict:
    combined = {}
    for domain, catalog in SAFETY_CATALOGS.items():
        for key, value in catalog.items():
            combined[key] = {"domain": domain, **value}
    return combined


def combined_aliases() -> dict:
    combined = {}
    for aliases in SAFETY_ALIASES_BY_DOMAIN.values():
        combined.update(aliases)
    return combined


SAFETY_ITEMS = combined_catalog()
SAFETY_ALIASES = combined_aliases()
