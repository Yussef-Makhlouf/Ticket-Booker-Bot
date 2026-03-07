"""
Intelligent price tier selection based on availability, preferences, and value.
"""
import logging
from typing import List, Optional
from data.models import PriceTier, UserPrefs

logger = logging.getLogger("booking")


class PriceOptimizer:
    """Score and select optimal price tiers for booking."""

    async def select_optimal_tier(
        self,
        tiers: List[PriceTier],
        preferences: UserPrefs,
    ) -> Optional[PriceTier]:
        """
        Choose the best price tier based on user preferences and availability.

        Scoring factors:
        - Lower price → higher score (if budget_conscious)
        - More available seats → higher score
        - Matching preferred section → bonus
        - Less popular tiers → bonus (more time to decide)
        """
        if not tiers:
            return None

        # Filter to available tiers
        available = [t for t in tiers if t.available_seats > 0]
        if not available:
            return None

        scored: List[tuple] = []
        for tier in available:
            score = 0.0

            # Factor 1: Price (lower = better for budget-conscious)
            if preferences.budget_conscious and tier.price > 0:
                max_price = max(t.price for t in available) or 1
                score += (1 - tier.price / max_price) * 40

            # Factor 2: Availability (more seats = better)
            score += min(tier.available_seats * 2, 30)

            # Factor 3: Section preference match
            if preferences.preferred_section:
                if tier.section.upper() == preferences.preferred_section.upper():
                    score += 25

            # Factor 4: Price cap
            if preferences.preferred_price_max > 0:
                if tier.price <= preferences.preferred_price_max:
                    score += 15
                else:
                    score -= 20  # Penalty for over-budget

            # Factor 5: Popularity (less popular = more relaxed booking)
            if tier.popularity_score < 0.3:
                score += 10

            scored.append((tier, score))

        # Sort by score descending
        scored.sort(key=lambda x: x[1], reverse=True)
        best = scored[0][0]

        logger.info(
            "Selected tier '%s' (section=%s, price=%d, score=%.1f)",
            best.name, best.section, best.price, scored[0][1],
        )
        return best

    def format_tiers_message(self, tiers: List[PriceTier]) -> str:
        """Format price tiers as an Arabic message for the user."""
        if not tiers:
            return "ℹ️ لم يتم العثور على فئات أسعار."

        lines = ["💰 <b>فئات الأسعار المتاحة:</b>\n"]
        for i, tier in enumerate(tiers, 1):
            avail = f"({tier.available_seats} مقعد)" if tier.available_seats > 0 else "(غير متاح)"
            lines.append(
                f"  {i}. <b>{tier.name or tier.section}</b> — "
                f"{tier.price} ريال {avail}"
            )
        return "\n".join(lines)


# Global instance
price_optimizer = PriceOptimizer()
