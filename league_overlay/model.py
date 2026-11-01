"""Shared records for champions and items."""

from __future__ import annotations

import re
from dataclasses import dataclass


def norm_name(value: str) -> str:
    """Compare 'Kai'Sa', 'Kaisa', and 'kai sa' as the same champion."""
    return re.sub(r"[^a-z0-9]", "", value.casefold())


@dataclass(frozen=True)
class Champion:
    key: int
    id: str
    name: str
    tags: tuple[str, ...]
    attack: int
    magic: int
    defense: int


@dataclass(frozen=True)
class Item:
    id: int
    name: str
    total: int
    base: int
    purchasable: bool
    summoners_rift: bool
    in_store: bool
    tags: tuple[str, ...]
    from_ids: tuple[int, ...]
    required_champion: str

    def shop_price(self) -> int:
        """Gold to pay for this step: combine cost if it has a recipe, else full cost."""
        if self.from_ids:
            return self.base
        return self.total
