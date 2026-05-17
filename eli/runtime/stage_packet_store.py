from __future__ import annotations

import threading
from typing import List

from eli.runtime.stage_packets import StagePacket, PacketSnapshot

_tls = threading.local()
_LAST_SNAPSHOT = PacketSnapshot()


def begin_stage_packet_cycle() -> None:
    _tls.packets = []


def append_stage_packet(packet: StagePacket) -> StagePacket:
    packet = StagePacket.from_any(packet)
    if not hasattr(_tls, "packets"):
        _tls.packets = []
    _tls.packets.append(packet)
    return packet


def current_stage_packets() -> List[StagePacket]:
    return list(getattr(_tls, "packets", []) or [])


def end_stage_packet_cycle() -> PacketSnapshot:
    global _LAST_SNAPSHOT
    snap = PacketSnapshot(packets=current_stage_packets())
    _LAST_SNAPSHOT = snap
    try:
        delattr(_tls, "packets")
    except Exception:
        pass
    return snap


def last_stage_packet_snapshot() -> PacketSnapshot:
    return _LAST_SNAPSHOT
