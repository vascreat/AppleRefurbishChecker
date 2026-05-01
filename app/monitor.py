"""Asynchronous monitoring service for running tasks."""

from __future__ import annotations

import asyncio
import logging
import re
from urllib.parse import urljoin

import aiohttp
from bs4 import BeautifulSoup
from telegram import constants
from telegram.ext import Application

from app.storage import TaskStorage


LOGGER = logging.getLogger(__name__)


class MonitorService:
    """Manage lifecycle of background monitoring jobs."""

    def __init__(self, application: Application, storage: TaskStorage) -> None:
        self._application = application
        self._storage = storage
        self._jobs: dict[str, asyncio.Task[None]] = {}

    def start_task(self, task_name: str) -> None:
        """Start background monitoring for one task if not already running."""
        if task_name in self._jobs:
            return
        self._jobs[task_name] = asyncio.create_task(self._run_task_loop(task_name))

    def stop_task(self, task_name: str) -> None:
        """Stop background monitoring for one task if running."""
        job = self._jobs.pop(task_name, None)
        if job:
            job.cancel()

    def stop_all(self) -> None:
        """Stop all running monitoring jobs."""
        for task_name in list(self._jobs.keys()):
            self.stop_task(task_name)

    async def start_running_tasks_from_storage(self) -> None:
        """Resume tasks marked as running when the bot process restarts."""
        for task in self._storage.list_tasks():
            if task["status"] == "running":
                self.start_task(task["name"])

    async def _run_task_loop(self, task_name: str) -> None:
        """Poll a page at configured intervals and notify on keyword matches."""
        while True:
            task = self._storage.get_task(task_name)
            if not task:
                self.stop_task(task_name)
                return

            if task["status"] != "running":
                self.stop_task(task_name)
                return

            try:
                matched_item = await self._find_matching_item(task)
                if matched_item:
                    await self._send_notification(task, matched_item)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                LOGGER.exception("Monitoring error for task '%s': %s", task_name, exc)

            await asyncio.sleep(task["interval_minutes"] * 60)

    async def _find_matching_item(self, task: dict) -> dict | None:
        """Find one item where all task constraints match inside the same item block."""
        html = await self._fetch_with_retry(task["url"])
        if not html:
            return None

        keywords = [kw.strip() for kw in task["keywords"] if kw.strip()]
        if not keywords:
            return None

        soup = BeautifulSoup(html, "html.parser")
        for item in self._extract_items(soup):
            text = item.get_text(" ", strip=True)
            if not text:
                continue

            lowered_text = text.lower()
            if not all(keyword.lower() in lowered_text for keyword in keywords):
                continue

            price = self._extract_price(item)
            if not self._price_matches(task, price):
                continue

            link = self._extract_item_link(item, task["url"])
            title = self._extract_title(item, text)
            return {
                "title": title,
                "link": link,
                "price": price,
            }

        return None

    @staticmethod
    def _extract_items(soup: BeautifulSoup) -> list:
        """Return candidate item nodes likely representing one product each."""
        selectors = [
            ".rf-refurb-producttile",
            "li.rf-refurb-producttile",
            "li.product",
            "article",
            "li",
            "div[class*='product']",
            "div[class*='item']",
            "div[class*='tile']",
            "div[class*='card']",
        ]

        seen = set()
        items = []
        for selector in selectors:
            for node in soup.select(selector):
                node_id = id(node)
                if node_id in seen:
                    continue
                seen.add(node_id)
                text_len = len(node.get_text(" ", strip=True))
                if text_len < 20:
                    continue
                items.append(node)

        if items:
            return items

        body = soup.body
        return [body] if body is not None else []

    @staticmethod
    def _extract_price(item) -> float | None:
        """Extract first plausible price from item text."""
        text = item.get_text(" ", strip=True)
        matches = re.findall(r"(?:\$|USD\s*|CAD\s*)(\d{1,3}(?:[,.]\d{3})*(?:[,.]\d{2})?|\d+(?:[.,]\d{2})?)", text, flags=re.IGNORECASE)
        if not matches:
            return None

        raw = matches[0]
        normalized = raw.replace(",", "")
        try:
            return float(normalized)
        except ValueError:
            return None

    @staticmethod
    def _price_matches(task: dict, price: float | None) -> bool:
        """Apply task price filters when both bounds are configured."""
        min_price = task.get("min_price")
        max_price = task.get("max_price")

        if min_price is None or max_price is None:
            return True
        if price is None:
            return False
        return float(min_price) <= price <= float(max_price)

    @staticmethod
    def _extract_item_link(item, base_url: str) -> str:
        """Find the most relevant link from the item and return absolute URL."""
        anchor = item.select_one("a[href]")
        if not anchor:
            return base_url
        href = anchor.get("href", "").strip()
        if not href:
            return base_url
        return urljoin(base_url, href)

    @staticmethod
    def _extract_title(item, fallback_text: str) -> str:
        """Extract a concise item title."""
        title_node = item.select_one("h1, h2, h3, h4, [class*='title'], [class*='name']")
        if title_node:
            title = title_node.get_text(" ", strip=True)
            if title:
                return title
        return fallback_text[:120]

    async def _fetch_with_retry(self, url: str, max_attempts: int = 2) -> str:
        """Try fetching a page more than once to survive transient failures."""
        timeout = aiohttp.ClientTimeout(total=20)
        for attempt in range(1, max_attempts + 1):
            try:
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get(
                        url,
                        headers={"User-Agent": "Mozilla/5.0"},
                    ) as response:
                        response.raise_for_status()
                        return await response.text()
            except Exception as exc:
                LOGGER.warning(
                    "Fetch failed for %s (attempt %s/%s): %s",
                    url,
                    attempt,
                    max_attempts,
                    exc,
                )
                if attempt < max_attempts:
                    await asyncio.sleep(2)
        return ""

    async def _send_notification(self, task: dict, matched_item: dict) -> None:
        """Send a match notification with direct purchase page link."""
        price_text = "unknown"
        if matched_item["price"] is not None:
            price_text = f"{matched_item['price']:.2f}"

        text = (
            f"Task: {task['name']}\n"
            f"User: <a href=\"tg://user?id={task['creator_id']}\">creator</a>\n"
            f"Item: {matched_item['title']}\n"
            f"Price: {price_text}\n"
            "The item you are searching for is available\n"
            f"Buy now: {matched_item['link']}"
        )
        await self._application.bot.send_message(
            chat_id=task["creator_chat_id"],
            text=text,
            parse_mode=constants.ParseMode.HTML,
            disable_web_page_preview=False,
        )
