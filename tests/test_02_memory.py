"""
test_02_memory.py
=================
Tests for eli.memory — the full memory subsystem.
"""
import pytest
import importlib
import sqlite3
import os


def test_memory_package_init():
    mod = importlib.import_module("eli.memory")
    assert mod is not None


def test_memory_main_module_has_class():
    mod = importlib.import_module("eli.memory.memory")
    symbols = dir(mod)
    memory_symbols = [s for s in symbols if "Memory" in s or "memory" in s.lower()]
    assert memory_symbols, f"eli.memory.memory has no Memory-like symbol: {symbols}"


def test_memory_vector_store_has_class():
    mod = importlib.import_module("eli.memory.vector_store")
    symbols = dir(mod)
    store_syms = [s for s in symbols if "Vector" in s or "Store" in s or "store" in s.lower()]
    assert store_syms, f"eli.memory.vector_store: no store symbols found: {symbols}"


def test_memory_knowledge_graph_has_class():
    mod = importlib.import_module("eli.memory.knowledge_graph")
    symbols = dir(mod)
    kg_syms = [s for s in symbols if "Graph" in s or "graph" in s.lower() or "Knowledge" in s]
    assert kg_syms, f"eli.memory.knowledge_graph: no graph symbols: {symbols}"


def test_memory_working_memory_loadable():
    mod = importlib.import_module("eli.memory.working_memory")
    assert mod is not None


def test_memory_sqlite_memory_loadable():
    mod = importlib.import_module("eli.memory.sqlite_memory")
    assert mod is not None


def test_memory_system_index_loadable():
    mod = importlib.import_module("eli.memory.system_index")
    assert mod is not None


def test_memory_habits_db_loadable():
    mod = importlib.import_module("eli.memory.habits_memory_db")
    assert mod is not None


def test_memory_habits_service_loadable():
    mod = importlib.import_module("eli.memory.habits_memory_service")
    assert mod is not None


def test_memory_memory_adapter_loadable():
    mod = importlib.import_module("eli.memory.memory_adapter")
    assert mod is not None


def test_memory_memory_service_loadable():
    mod = importlib.import_module("eli.memory.memory_service")
    assert mod is not None


def test_memory_stores_loadable():
    mod = importlib.import_module("eli.memory.stores")
    assert mod is not None


def test_memory_db_paths_exists():
    mod = importlib.import_module("eli.memory.db_paths")
    syms = dir(mod)
    assert any("path" in s.lower() or "db" in s.lower() for s in syms), \
        f"eli.memory.db_paths looks empty: {syms}"


def test_memory_populate_loadable():
    mod = importlib.import_module("eli.memory.populate_memories")
    assert mod is not None


def test_memory_no_cross_import_crash():
    """Memory adapter + service should be importable together."""
    adapter = importlib.import_module("eli.memory.memory_adapter")
    service = importlib.import_module("eli.memory.memory_service")
    assert adapter and service
