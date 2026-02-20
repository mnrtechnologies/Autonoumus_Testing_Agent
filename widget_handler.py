"""
widget_handler.py
─────────────────
Handles composite widgets that cannot be interacted with
via simple fill/click actions.

Supported widgets:
  - calendar (Angular Material date range picker)
"""

import asyncio
from typing import Dict, Optional
from playwright.async_api import Page


class WidgetHandler:

    def __init__(self, page: Page):
        self.page = page

    async def handle(self, widget_type: str, value: Dict) -> bool:
        """
        Main entry point.
        Returns True if handled successfully, False otherwise.
        """
        if widget_type == "calendar":
            return await self._handle_date_range(value)
        return False

    async def _handle_date_range(self, value: Dict) -> bool:
        """
        Handles Angular Material date range picker.
        value = {"start": "01/01/2025", "end": "17/02/2026"}
        """
        try:
            start_str = value.get("start", "01/01/2025")
            end_str   = value.get("end",   "17/02/2026")

            if "/" not in start_str or "/" not in end_str:
                print(f"    ⚠️  Invalid date format: {start_str} / {end_str} — using defaults")
                start_str = "01/01/2025"
                end_str   = "17/02/2026"

            # Parse DD/MM/YYYY
            start_day, start_month, start_year = start_str.split("/")
            end_day,   end_month,   end_year   = end_str.split("/")

            print(f"    📅 Handling date range: {start_str} → {end_str}")

            # Navigate to start month/year
            await self._navigate_to_month(int(start_month), int(start_year))

            # Click start date
            await self._click_day(int(start_day))
            print(f"    ✅ Start date clicked: {start_str}")
            await asyncio.sleep(0.5)

            # Navigate to end month/year if different
            if start_month != end_month or start_year != end_year:
                await self._navigate_to_month(int(end_month), int(end_year))

            # Click end date
            await self._click_day(int(end_day))
            print(f"    ✅ End date clicked: {end_str}")
            await asyncio.sleep(0.5)

            # Click Apply/Terapkan
            await self._click_apply()
            print(f"    ✅ Date range applied")
            await asyncio.sleep(1)

            return True

        except Exception as e:
            print(f"    ❌ Date range handler failed: {e}")
            # Close calendar gracefully
            try:
                await self.page.keyboard.press("Escape")
            except Exception:
                pass
            return False

    async def _navigate_to_month(self, target_month: int, target_year: int):
        """Navigate calendar to the correct month/year."""
        max_clicks = 24
        clicks = 0

        while clicks < max_clicks:
            # Read current month/year from calendar header
            current = await self._get_current_month_year()
            if not current:
                break

            cur_month, cur_year = current

            if cur_month == target_month and cur_year == target_year:
                break

            # Decide direction
            if (target_year, target_month) > (cur_year, cur_month):
                # Click next month
                btn = self.page.locator('[aria-label="Next month"]').first
                if await btn.count() == 0:
                    btn = self.page.get_by_role("button", name="Next month")
                await btn.click()
            else:
                # Click previous month
                btn = self.page.locator('[aria-label="Previous month"]').first
                if await btn.count() == 0:
                    btn = self.page.get_by_role("button", name="Previous month")
                await btn.click()

            await asyncio.sleep(0.3)
            clicks += 1

    async def _get_current_month_year(self) -> Optional[tuple]:
        """Read current month and year from calendar header."""
        MONTHS = {
            "jan": 1, "feb": 2, "mar": 3, "apr": 4,
            "may": 5, "jun": 6, "jul": 7, "aug": 8,
            "sep": 9, "oct": 10, "nov": 11, "dec": 12,
            # Indonesian
            "agu": 8, "okt": 10, "des": 12, "mei": 5
        }
        try:
            # Try Angular Material calendar header button
            header = self.page.locator(
                "mat-calendar .mat-calendar-period-button, "
                "mat-calendar button.mat-calendar-period-button, "
                "[class*='calendar-period']"
            ).first

            if await header.count() == 0:
                # Fallback: find any button with month name pattern
                header = self.page.locator(
                    "[role='dialog'] button"
                ).filter(has_text="2026").or_(
                    self.page.locator("[role='dialog'] button").filter(has_text="2025")
                ).first

            text = (await header.inner_text()).strip().lower()
            # text like "feb 2026" or "februari 2026"
            parts = text.split()
            if len(parts) >= 2:
                month_str = parts[0][:3]
                year = int(parts[1])
                month = MONTHS.get(month_str)
                if month:
                    return month, year
        except Exception:
            pass
        return None

    async def _click_day(self, day: int):
        """Click a specific day number in the calendar."""
        # Try aria-label first (most reliable)
        selectors = [
            f'[aria-label*=" {day},"]',
            f'[aria-label*="{day},"]',
            f'mat-calendar td[aria-label*="{day}"]',
        ]
        for sel in selectors:
            try:
                loc = self.page.locator(sel).first
                if await loc.count() > 0:
                    await loc.click()
                    return
            except Exception:
                pass

        # Fallback: find button with exact day number text
        try:
            buttons = self.page.locator("[role='dialog'] .mat-calendar-body-cell-content")
            count = await buttons.count()
            for i in range(count):
                btn = buttons.nth(i)
                text = (await btn.inner_text()).strip()
                if text == str(day):
                    await btn.click()
                    return
        except Exception:
            pass

        raise Exception(f"Could not find day {day} in calendar")

    async def _click_apply(self):
        """Click the Apply/Terapkan button to confirm the date range."""
        apply_texts = ["Terapkan", "Apply", "OK", "Confirm", "Done"]
        for text in apply_texts:
            try:
                btn = self.page.get_by_role("button", name=text, exact=True)
                if await btn.count() > 0:
                    await btn.click()
                    return
            except Exception:
                pass

        # Fallback
        try:
            btn = self.page.locator("[role='dialog'] button").filter(
                has_text="Terapkan"
            ).or_(
                self.page.locator("[role='dialog'] button").filter(has_text="Apply")
            ).first
            await btn.click()
        except Exception:
            raise Exception("Could not find Apply/Terapkan button")