"""
test_10_tools.py
================
Tests for eli.tools — image engine, news, and capability registry.
"""
import importlib
import pytest


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


