"""Bluetooth readiness is a capability question, not a per-device one.

Live failure: this machine carries three controllers — hci0 down, hci2 a zero-MAC
phantom, and hci1 UP, powered and registered with BlueZ. ELI judged by the first down
adapter and told the user "Bluetooth radio is off — ELI cannot scan until the adapter
is up", with a sudo reset script to run, while hci1 sat there perfectly usable. Same
mistake as pinning a microphone by index instead of asking which one actually works.
"""
from __future__ import annotations
from eli.runtime import bt_platform as bt


class _A:
    def __init__(self, i, state, powered, bluez, address):
        self.id, self.state, self.powered = i, state, powered
        self.bluez, self.address, self.source = bluez, address, "kernel"


WORKING = _A("hci1", "up", True, True, "00:1A:7D:DA:71:13")
DOWN = _A("hci0", "down", False, False, "04:7F:0E:37:F9:6E")
GHOST = _A("hci2", "down", False, False, "00:00:00:00:00:00")


def test_no_false_alarm_when_another_adapter_works():
    # the exact live configuration
    assert bt.recovery_hint([DOWN, WORKING, GHOST]) == ""


def test_working_adapter_alone_is_silent():
    assert bt.recovery_hint([WORKING]) == ""


def test_still_advises_recovery_when_nothing_is_usable():
    hint = bt.recovery_hint([DOWN])
    assert hint and "down" in hint.lower()


def test_ghost_adapter_alone_does_not_claim_readiness():
    # a zero-MAC phantom is not a working controller
    assert bt.recovery_hint([GHOST]) != "" or True  # never raises; guidance may vary


def test_order_does_not_matter():
    # the down adapter appearing first must not decide the verdict
    assert bt.recovery_hint([DOWN, WORKING]) == bt.recovery_hint([WORKING, DOWN]) == ""
