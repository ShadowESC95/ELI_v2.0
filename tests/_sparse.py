"""Files the size of a model that use no disk.

Several tests need a file whose size is a real model's (gigabytes) while nothing reads its
contents. Linux and macOS leave a hole when the length is set past what was written. Windows
writes out every zero unless the file is marked sparse first: a few of these at their real size
filled the CI runner's disk. Every such file goes through here.
"""
from __future__ import annotations

import os


def mark_sparse(f) -> None:
    if os.name != "nt":
        return
    import ctypes
    import msvcrt
    from ctypes import wintypes
    handle = wintypes.HANDLE(msvcrt.get_osfhandle(f.fileno()))
    returned = wintypes.DWORD()
    fsctl_set_sparse = 0x000900C4
    ctypes.windll.kernel32.DeviceIoControl(handle, fsctl_set_sparse, None, 0, None, 0,
                                           ctypes.byref(returned), None)


def sparse_file(path, size: int, head: bytes = b"") -> str:
    """`path` is `size` bytes long, starts with `head`, and the rest takes no space."""
    with open(path, "wb") as f:
        f.write(head)
        mark_sparse(f)
        if size > len(head):
            f.seek(size - 1)
            f.write(b"\0")
    return str(path)
