"""把檔案移到「資源回收筒」的跨平台封裝。

Windows 走 Shell 的 SHFileOperationW，效果等同在檔案總管按 Delete（可再還原）；
macOS／Linux 沒有統一的回收筒 API，因此改用家目錄下的 ``.filekeeper-trash`` 資料夾
當作本程式自己的垃圾桶，檔案一樣可以事後手動救回。
"""

from __future__ import annotations

import ctypes
import shutil
import sys
import time
from pathlib import Path
from typing import Sequence

FO_DELETE = 3

FOF_SILENT = 0x0004
FOF_NOCONFIRMATION = 0x0010
FOF_ALLOWUNDO = 0x0040
FOF_NOERRORUI = 0x0400

# 安靜刪除：不跳系統確認框、不跳錯誤框，畫面交給本程式控制
FOF_NO_UI = FOF_SILENT | FOF_NOCONFIRMATION | FOF_NOERRORUI


class _SHFILEOPSTRUCTW(ctypes.Structure):
    """對應 Windows Shell 的 SHFILEOPSTRUCTW 結構定義。"""

    _fields_ = (
        ("hwnd", ctypes.c_void_p),
        ("wFunc", ctypes.c_uint),
        ("pFrom", ctypes.c_void_p),
        ("pTo", ctypes.c_void_p),
        ("fFlags", ctypes.c_ushort),
        ("fAnyOperationsAborted", ctypes.c_int),
        ("hNameMappings", ctypes.c_void_p),
        ("lpszProgressTitle", ctypes.c_wchar_p),
    )


def _windows_move_to_trash(paths: Sequence[Path]) -> None:
    """呼叫 Windows Shell 把檔案丟進資源回收筒，失敗時丟出 OSError。"""
    # pFrom 是以「兩個結束字元」收尾的路徑清單，多個路徑之間用單一結束字元分隔
    joined = "\0".join(str(Path(p).resolve()) for p in paths) + "\0\0"
    # 一定要用 ctypes 緩衝區帶入；直接指定 c_wchar_p 在部分 Python 版本會擋下內含結束字元的路徑
    buffer = ctypes.create_unicode_buffer(joined)

    operation = _SHFILEOPSTRUCTW()
    operation.hwnd = None
    operation.wFunc = FO_DELETE
    operation.pFrom = ctypes.cast(buffer, ctypes.c_void_p)
    operation.pTo = None
    operation.fFlags = FOF_ALLOWUNDO | FOF_NO_UI

    result = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(operation))
    if result != 0:
        raise OSError(f"移到資源回收筒失敗（Shell 錯誤碼 0x{result:X}）")
    if operation.fAnyOperationsAborted:
        raise OSError("操作被中途取消")


def local_trash_dir() -> Path:
    """回傳本程式在非 Windows 平台使用的垃圾桶資料夾。"""
    return Path.home() / ".filekeeper-trash"


def _unique_target(target: Path) -> Path:
    """避免垃圾桶內同名檔案互相覆蓋，必要時在檔名後加上時間戳。"""
    if not target.exists():
        return target
    stem, suffix = target.stem, target.suffix
    return target.with_name(f"{stem}-{int(time.time() * 1000)}{suffix}")


def _fallback_move_to_trash(paths: Sequence[Path]) -> None:
    """非 Windows 平台：把檔案搬進家目錄下的垃圾桶資料夾。"""
    trash_dir = local_trash_dir()
    trash_dir.mkdir(parents=True, exist_ok=True)
    for path in paths:
        source = Path(path)
        shutil.move(str(source), str(_unique_target(trash_dir / source.name)))


def move_to_trash(paths: Sequence[Path]) -> None:
    """把指定的檔案移到資源回收筒。

    參數：
        paths：要刪除的檔案路徑序列。

    例外：
        OSError：任何一個檔案無法移到回收筒時丟出，訊息可直接顯示給使用者。
    """
    targets = [Path(p) for p in paths]
    if not targets:
        return
    if sys.platform.startswith("win"):
        _windows_move_to_trash(targets)
    else:
        _fallback_move_to_trash(targets)


def supports_system_recycle_bin() -> bool:
    """是否支援作業系統內建的資源回收筒。"""
    return sys.platform.startswith("win")
