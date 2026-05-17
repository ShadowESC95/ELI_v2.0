"""Web Automation plugin for ELI – lazy Playwright import, safe under broken installs."""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

from eli.plugins.base import Plugin
try:
    from eli.core import config
except Exception:
    class _Cfg:
        @staticmethod
        def get(key, default=None):
            return default
    config = _Cfg()  # type: ignore

_playwright = None
_browser = None
_page = None
_import_error: Optional[str] = None


def _load_sync_playwright():
    global _import_error
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
        return sync_playwright
    except Exception as e:  # broken install should not crash import-time tests
        _import_error = str(e)
        return None


def ensure_browser(headless: bool = True):
    global _playwright, _browser, _page
    if _page is not None and _browser is not None:
        return _page
    sync_playwright = _load_sync_playwright()
    if sync_playwright is None:
        raise RuntimeError(_import_error or 'Playwright unavailable')
    _playwright = sync_playwright().start()
    _browser = _playwright.chromium.launch(headless=headless)
    _page = _browser.new_page()
    _page.set_default_timeout(10000)
    return _page


class WebAutomationPlugin(Plugin):
    name = 'web_automation'
    description = 'Control web browsers – navigate, search, click, fill, screenshot, extract.'

    def navigate(self, args: Dict[str, Any]) -> Dict[str, Any]:
        url = args.get('url', '')
        if not url:
            return {'ok': False, 'error': 'No URL provided.'}
        if not url.startswith('http'):
            url = 'https://' + url
        try:
            page = ensure_browser(headless=config.get('web_headless', True))
            page.goto(url)
            title = page.title()
            return {'ok': True, 'url': url, 'title': title, 'content': f'Navigated to {url} (title: {title})'}
        except Exception as e:
            return {'ok': False, 'error': str(e)}

    def search(self, args: Dict[str, Any]) -> Dict[str, Any]:
        q = args.get('query', '')
        if not q:
            return {'ok': False, 'error': 'No search query provided.'}
        return self.navigate({'url': 'https://www.google.com/search?q=' + q.replace(' ', '+')})

    def screenshot(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Take a screenshot of the current page and save to a file."""
        path = args.get('path', 'screenshot.png')
        try:
            page = ensure_browser(headless=config.get('web_headless', True))
            page.screenshot(path=path)
            return {'ok': True, 'path': path, 'content': f'Screenshot saved to {path}'}
        except Exception as e:
            return {'ok': False, 'error': str(e)}

    def close(self, args: Dict[str, Any]) -> Dict[str, Any]:
        global _playwright, _browser, _page
        try:
            if _page is not None:
                _page.close(); _page = None
            if _browser is not None:
                _browser.close(); _browser = None
            if _playwright is not None:
                _playwright.stop(); _playwright = None
            return {'ok': True, 'content': 'Browser closed.'}
        except Exception as e:
            return {'ok': False, 'error': str(e)}
