"""
test_10_tools.py
================
Tests for eli.tools — image engine, news, and capability registry.
"""
import importlib
import pytest


def test_tools_package_init():
    assert importlib.import_module("eli.tools") is not None


def test_tools_image_engine_loadable():
    assert importlib.import_module("eli.tools.image_engine") is not None


def test_tools_news_fetcher_loadable():
    assert importlib.import_module("eli.tools.news.news_fetcher") is not None


def test_tools_registry_capabilities_loadable():
    mod = importlib.import_module("eli.tools.registry.capabilities")
    assert mod is not None


def test_tools_registry_capability_registry_loadable():
    assert importlib.import_module("eli.tools.registry.capability_registry") is not None


def test_tools_registry_capability_updater_loadable():
    assert importlib.import_module("eli.tools.registry.capability_updater") is not None


def test_tools_capabilities_has_registry_symbols():
    mod = importlib.import_module("eli.tools.registry.capabilities")
    syms = dir(mod)
    matches = [s for s in syms if "capabilit" in s.lower() or "Capabilit" in s]
    assert matches, f"No capability symbols: {syms}"


def test_tools_utils_platform_compat_loadable():
    assert importlib.import_module("eli.utils.platform_compat") is not None


def test_platform_compat_os_aliases():
    mod = importlib.import_module("eli.utils.platform_compat")
    assert mod.normalize_platform("win32") == "windows"
    assert mod.normalize_platform("osx") == "macos"
    assert mod.normalize_platform("termux") == "android"
    assert mod.normalize_platform("freebsd") == "bsd"


def test_platform_compat_app_aliases_include_android():
    mod = importlib.import_module("eli.utils.platform_compat")
    assert mod.app_aliases("android")["terminal"] == "com.termux"
    assert mod.normalize_app_name("vs code", "windows")
    assert "macos" in mod.platform_aliases("darwin")


def test_tools_integrations_ollama_client_loadable():
    assert importlib.import_module("eli.integrations.ollama.client") is not None


def test_tools_integrations_local_gguf_loadable():
    assert importlib.import_module("eli.integrations.local_gguf") is not None


def test_tools_integrations_mpris_loadable():
    assert importlib.import_module("eli.integrations.mpris.playerctl_backend") is not None
