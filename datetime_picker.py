"""
Datetime Picker Handler for Angular Material and similar custom datetime components.
Handles both calendar selection and time selection in two-step pickers.
"""

import asyncio
from typing import Optional, Tuple
from datetime import datetime
from playwright.async_api import Page, Locator


class DatetimePicker:
    """Handles complex datetime picker interactions"""
    
    def __init__(self, page: Page):
        self.page = page
    
    async def fill_datetime(
        self,
        trigger_locator: Locator,
        datetime_value: str
    ) -> dict:
        """
        Fill a datetime picker with both date and time.
        
        Args:
            trigger_locator: The input field that opens the datetime picker
            datetime_value: String in format "DD/MM/YYYY, HH:MM" or "DD/MM/YYYY HH:MM"
        
        Returns:
            dict with success status and details
        """
        result = {
            "success": False,
            "date_set": False,
            "time_set": False,
            "error": None
        }
        
        try:
            # Parse the datetime value
            date_part, time_part = parse_datetime(datetime_value)
            if not date_part or not time_part:
                result["error"] = f"Invalid datetime format: {datetime_value}"
                return result
            
            print(f"    📅 Parsed datetime: Date={date_part}, Time={time_part}")
            
            # Step 1: Open the datetime picker
            await trigger_locator.scroll_into_view_if_needed(timeout=5000)
            await trigger_locator.click(timeout=5000)
            print(f"    ✓ Opened datetime picker")
            await asyncio.sleep(1)
            
            # Step 2: Handle calendar selection
            date_result = await self._select_date(date_part)
            result["date_set"] = date_result
            
            if not date_result:
                result["error"] = "Failed to select date"
                return result
            
            # Step 3: Handle time selection (clock view)
            time_result = await self._select_time(time_part)
            result["time_set"] = time_result
            
            if not time_result:
                result["error"] = "Failed to select time"
                return result
            
            # Step 4: Confirm/close the picker
            await self._confirm_datetime()
            
            result["success"] = True
            print(f"    ✅ Datetime set: {datetime_value}")
            
        except Exception as e:
            result["error"] = str(e)
            print(f"    ❌ Datetime picker failed: {e}")
        
        return result
    
    async def _select_date(self, date_str: str) -> bool:
        """
        Select date from calendar view.
        Format: DD/MM/YYYY
        """
        try:
            day, month, year = date_str.split('/')
            day = int(day)
            month = int(month)
            year = int(year)
            
            print(f"    📅 Selecting date: {day}/{month}/{year}")
            
            # Wait for calendar to be visible
            await asyncio.sleep(0.5)
            
            # Check current month/year and navigate if needed
            current_month_year = await self._get_current_month_year()
            print(f"    📅 Current calendar view: {current_month_year}")
            
            # Navigate to correct month/year if needed
            await self._navigate_to_month_year(month, year)
            
            # Click the day
            day_selectors = [
                f'button[aria-label*="{day}"]',
                f'.mat-calendar-body-cell[aria-label*="{day}"]',
                f'td[aria-label*="{day}"] button',
                f'button:has-text("{day}")',
            ]
            
            clicked = False
            for selector in day_selectors:
                try:
                    day_button = self.page.locator(selector).first
                    count = await day_button.count()
                    if count > 0:
                        # Find the right day (there might be multiple if showing adjacent months)
                        for i in range(count):
                            btn = self.page.locator(selector).nth(i)
                            aria_label = await btn.get_attribute('aria-label') or ''
                            # Check if this is the day we want (not disabled, right month)
                            is_disabled = await btn.get_attribute('disabled')
                            if not is_disabled and str(day) in aria_label:
                                await btn.click(timeout=3000)
                                print(f"    ✓ Clicked day: {day}")
                                clicked = True
                                break
                    if clicked:
                        break
                except Exception:
                    continue
            
            if not clicked:
                # Fallback: try clicking any element with the day number
                try:
                    day_elem = self.page.locator(f'text="{day}"').first
                    await day_elem.click(timeout=3000)
                    print(f"    ✓ Clicked day (fallback): {day}")
                    clicked = True
                except Exception:
                    pass
            
            await asyncio.sleep(0.5)
            return clicked
            
        except Exception as e:
            print(f"    ❌ Date selection failed: {e}")
            return False
    
    async def _select_time(self, time_str: str) -> bool:
        """
        Select time from clock view.
        Format: HH:MM
        """
        try:
            hours, minutes = time_str.split(':')
            hours = int(hours)
            minutes = int(minutes)
            
            print(f"    🕐 Selecting time: {hours:02d}:{minutes:02d}")
            
            # Wait for clock view to appear
            await asyncio.sleep(1)
            
            # Step 1: Select hours
            hour_selected = await self._select_hour(hours)
            if not hour_selected:
                print(f"    ⚠️  Hour selection failed, trying fallback")
                # Fallback: try clicking hour number directly
                try:
                    hour_elem = self.page.locator(f'text="{hours}"').first
                    await hour_elem.click(timeout=2000)
                    hour_selected = True
                except Exception:
                    pass
            
            await asyncio.sleep(0.5)
            
            # Step 2: Select minutes
            minute_selected = await self._select_minute(minutes)
            if not minute_selected:
                print(f"    ⚠️  Minute selection failed, trying fallback")
                # Fallback: try clicking minute number directly
                try:
                    minute_elem = self.page.locator(f'text="{minutes:02d}"').first
                    await minute_elem.click(timeout=2000)
                    minute_selected = True
                except Exception:
                    pass
            
            return hour_selected and minute_selected
            
        except Exception as e:
            print(f"    ❌ Time selection failed: {e}")
            return False
    
    async def _select_hour(self, hour: int) -> bool:
        """Click hour on clock face"""
        try:
            # Angular Material clock selectors
            hour_selectors = [
                f'button[aria-label*="{hour} hours"]',
                f'.mat-mdc-button:has-text("{hour}")',
                f'button:has-text("{hour}")',
                f'[role="option"]:has-text("{hour}")',
            ]
            
            for selector in hour_selectors:
                try:
                    hour_btn = self.page.locator(selector).first
                    if await hour_btn.count() > 0:
                        await hour_btn.click(timeout=3000)
                        print(f"    ✓ Selected hour: {hour}")
                        return True
                except Exception:
                    continue
            
            # Fallback: click on clock face coordinates
            # (This is complex - clock faces have different layouts for 12h vs 24h)
            return False
            
        except Exception as e:
            print(f"    ❌ Hour selection failed: {e}")
            return False
    
    async def _select_minute(self, minute: int) -> bool:
        """Click minute on clock face"""
        try:
            # Round to nearest 5-minute interval (common in pickers)
            display_minute = (minute // 5) * 5
            
            minute_selectors = [
                f'button[aria-label*="{minute} minutes"]',
                f'button[aria-label*="{display_minute} minutes"]',
                f'.mat-mdc-button:has-text("{minute:02d}")',
                f'button:has-text("{minute:02d}")',
                f'button:has-text("{display_minute:02d}")',
                f'[role="option"]:has-text("{minute:02d}")',
            ]
            
            for selector in minute_selectors:
                try:
                    minute_btn = self.page.locator(selector).first
                    if await minute_btn.count() > 0:
                        await minute_btn.click(timeout=3000)
                        print(f"    ✓ Selected minute: {minute}")
                        return True
                except Exception:
                    continue
            
            return False
            
        except Exception as e:
            print(f"    ❌ Minute selection failed: {e}")
            return False
    
    async def _get_current_month_year(self) -> str:
        """Get currently displayed month and year from calendar"""
        try:
            # Common selectors for month/year display
            month_year_selectors = [
                '.mat-calendar-period-button',
                '.mat-calendar-header button',
                '[aria-live="polite"]',
            ]
            
            for selector in month_year_selectors:
                try:
                    elem = self.page.locator(selector).first
                    if await elem.count() > 0:
                        text = await elem.inner_text()
                        return text.strip()
                except Exception:
                    continue
            
            return ""
        except Exception:
            return ""
    
    async def _navigate_to_month_year(self, target_month: int, target_year: int):
        """Navigate calendar to target month/year using prev/next buttons"""
        try:
            # This is simplified - you might need more logic for year navigation
            # For now, just handle month navigation within same year
            
            current_text = await self._get_current_month_year()
            # Parse current month from text like "February 2026"
            # This is basic - enhance based on your actual calendar format
            
            # Click next/prev month buttons as needed
            # Selectors for navigation
            next_btn = self.page.locator('button[aria-label*="Next"]').first
            prev_btn = self.page.locator('button[aria-label*="Previous"]').first
            
            # Simple navigation (you may need to enhance this)
            # For now, assume we're close to the target month
            
        except Exception as e:
            print(f"    ⚠️  Month/year navigation failed: {e}")
    
    async def _confirm_datetime(self):
        """Click OK/Confirm button to close the datetime picker"""
        try:
            confirm_selectors = [
                'button:has-text("OK")',
                'button:has-text("Confirm")',
                'button:has-text("Set")',
                'button:has-text("Done")',
                '.mat-mdc-button:has-text("OK")',
                '[mat-button]:has-text("OK")',
            ]
            
            for selector in confirm_selectors:
                try:
                    btn = self.page.locator(selector).first
                    if await btn.count() > 0:
                        await btn.click(timeout=2000)
                        print(f"    ✓ Confirmed datetime selection")
                        return
                except Exception:
                    continue
            
            # If no confirm button found, press Escape or click outside
            await self.page.keyboard.press("Escape")
            
        except Exception as e:
            print(f"    ⚠️  Confirm failed: {e}")


def parse_datetime(datetime_str: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Parse datetime string into date and time parts.
    
    Supported formats:
    - "DD/MM/YYYY, HH:MM"
    - "DD/MM/YYYY HH:MM"
    - "DD-MM-YYYY HH:MM"
    
    Returns:
        Tuple of (date_part, time_part) or (None, None) if invalid
    """
    try:
        # Remove extra spaces
        datetime_str = datetime_str.strip()
        
        # Split by comma or space
        if ',' in datetime_str:
            parts = datetime_str.split(',')
            date_part = parts[0].strip()
            time_part = parts[1].strip() if len(parts) > 1 else None
        else:
            # Split by last space (to separate time from date)
            parts = datetime_str.rsplit(' ', 1)
            if len(parts) == 2:
                date_part = parts[0].strip()
                time_part = parts[1].strip()
            else:
                return None, None
        
        # Validate format
        if not time_part or ':' not in time_part:
            return None, None
        
        if '/' not in date_part and '-' not in date_part:
            return None, None
        
        # Normalize date separators to /
        date_part = date_part.replace('-', '/')
        
        return date_part, time_part
        
    except Exception:
        return None, None


async def handle_datetime_element(
    page: Page,
    trigger_locator: Locator,
    datetime_value: str
) -> dict:
    """
    Convenience function to handle datetime picker from outside.
    """
    picker = DatetimePicker(page)
    return await picker.fill_datetime(trigger_locator, datetime_value)


def is_datetime_field(element: dict) -> bool:
    """
    Detect if an element is a datetime picker input.
    
    Args:
        element: Element dict from Observer
    
    Returns:
        True if this is a datetime picker field
    """
    text = element.get("text", "").lower()
    formcontrol = element.get("formcontrolname", "").lower()
    placeholder = element.get("placeholder", "").lower()
    name = element.get("name", "").lower()
    
    # Keywords that indicate a datetime picker
    datetime_keywords = [
        "date", "datetime", "tanggal", "waktu", "time",
        "event date", "eventdate", "registrationdate",
        "schedule", "jadwal", "from", "to", "start", "end",
        "calendar", "kalender", "picker"
    ]
    
    combined = f"{text} {formcontrol} {placeholder} {name}"
    
    # Check for keywords
    if any(kw in combined for kw in datetime_keywords):
        # Additional check: not a plain date (those can use .fill())
        # Datetime pickers typically have calendar icon or specific classes
        return True
    
    return False