"""
Self-healing selector engine that adapts to website changes.
Tracks success/failure rates and prioritizes working selectors.
"""
import logging
import yaml
import os
from typing import Optional, Dict, List
from playwright.async_api import Page
from config.settings import settings

logger = logging.getLogger("automation")


class AdaptiveSelectorEngine:
    """
    Fallback-chain selector system with priority learning.
    Loads initial selectors from YAML, then adapts based on success/failure.
    """

    def __init__(self):
        self._registry: Dict[str, List[str]] = {}
        self._success_count: Dict[str, Dict[str, int]] = {}
        self._failure_count: Dict[str, Dict[str, int]] = {}
        self._load_selectors()

    def _load_selectors(self):
        """Load selectors from YAML config."""
        yaml_path = os.path.join(settings.BASE_DIR, "config", "selectors.yaml")
        try:
            with open(yaml_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)

            # Flatten nested structure: login.email_field → login__email_field
            for category, targets in data.items():
                if isinstance(targets, dict):
                    for target, selectors in targets.items():
                        key = f"{category}__{target}"
                        self._registry[key] = selectors if isinstance(selectors, list) else [selectors]

            logger.info("Loaded %d selector targets from YAML", len(self._registry))
        except Exception as e:
            logger.warning("Could not load selectors YAML: %s", e)

    async def find_element(self, page: Page, target: str, context: Optional[dict] = None) -> Optional[str]:
        """
        Try selector chain until one works.
        Returns the working selector or None.
        """
        selectors = self._registry.get(target, [])

        for selector in selectors:
            try:
                element = await page.query_selector(selector)
                if element:
                    # Verify element is actionable
                    is_visible = await element.is_visible()
                    if is_visible:
                        self._log_success(target, selector)
                        return selector
            except Exception:
                self._log_failure(target, selector)
                continue

        # All failed: try auto-discovery
        if context:
            discovered = await self._auto_discover(page, context)
            if discovered:
                # Add discovered selector to registry for future use
                if target not in self._registry:
                    self._registry[target] = []
                self._registry[target].insert(0, discovered)
                return discovered

        return None

    async def _auto_discover(self, page: Page, context: dict) -> Optional[str]:
        """Try to find element using context hints."""
        # Strategy 1: Text-based search
        if "text" in context:
            text = context["text"]
            for prefix in ["button", "a", "[role='button']", "div"]:
                selector = f'{prefix}:has-text("{text}")'
                try:
                    el = await page.query_selector(selector)
                    if el and await el.is_visible():
                        return selector
                except Exception:
                    continue

        # Strategy 2: Attribute-based search
        for attr in ["data-testid", "data-action", "role", "aria-label"]:
            if attr in context:
                selector = f'[{attr}="{context[attr]}"]'
                try:
                    el = await page.query_selector(selector)
                    if el:
                        return selector
                except Exception:
                    continue

        # Strategy 3: XPath with fuzzy text matching
        if "text" in context:
            xpath = f'//button[contains(text(), "{context["text"]}")]'
            try:
                el = await page.query_selector(f"xpath={xpath}")
                if el:
                    return f"xpath={xpath}"
            except Exception:
                pass

        return None

    def _log_success(self, target: str, selector: str):
        """Track successful selector usage."""
        self._success_count.setdefault(target, {})
        self._success_count[target][selector] = (
            self._success_count[target].get(selector, 0) + 1
        )

        # Re-sort registry by success rate
        if target in self._registry:
            self._registry[target].sort(
                key=lambda s: self._success_count.get(target, {}).get(s, 0),
                reverse=True,
            )

    def _log_failure(self, target: str, selector: str):
        """Track failed selector usage."""
        self._failure_count.setdefault(target, {})
        self._failure_count[target][selector] = (
            self._failure_count[target].get(selector, 0) + 1
        )

    def report_failure(self, target: str, selector: str):
        """External failure report (from error handling)."""
        self._log_failure(target, selector)
        logger.warning("Selector failure reported: %s → %s", target, selector)

    def get_best_selector(self, target: str) -> Optional[str]:
        """Return the highest-priority selector for a target."""
        selectors = self._registry.get(target, [])
        return selectors[0] if selectors else None

    @property
    def stats(self) -> dict:
        """Get selector engine statistics."""
        return {
            "total_targets": len(self._registry),
            "successes": sum(
                sum(v.values()) for v in self._success_count.values()
            ),
            "failures": sum(
                sum(v.values()) for v in self._failure_count.values()
            ),
        }


# Global instance
selector_engine = AdaptiveSelectorEngine()
