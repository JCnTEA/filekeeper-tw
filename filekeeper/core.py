"""檔案管家（FileKeeper TW）核心邏輯。

本模組只負責「掃描資料夾內容」與「刪除檔案」兩件事，完全不含介面程式碼，
方便日後替換前端、撰寫測試，或改寫成命令列版本。
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from .trash import move_to_trash

_SIZE_UNITS: tuple[str, ...] = ("B", "KB", "MB", "GB", "TB", "PB")

ALL_TYPES_LABEL = "全部類型"

# 檔案類型分類表（副檔名一律小寫，且包含開頭的點）
TYPE_GROUPS: dict[str, tuple[str, ...]] = {
    "圖片": (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".svg", ".heic", ".tif", ".tiff", ".ico"),
    "文件": (".txt", ".md", ".doc", ".docx", ".pdf", ".odt", ".rtf", ".xls", ".xlsx", ".csv", ".ppt", ".pptx"),
    "音訊": (".mp3", ".wav", ".flac", ".m4a", ".ogg", ".aac", ".wma"),
    "影片": (".mp4", ".mov", ".mkv", ".avi", ".webm", ".wmv", ".flv"),
    "壓縮檔": (".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz"),
    "程式碼": (
        ".py", ".js", ".ts", ".html", ".css", ".json", ".xml", ".yml", ".yaml",
        ".java", ".c", ".cpp", ".h", ".cs", ".go", ".rs", ".sh", ".ps1", ".bat",
    ),
    "執行檔": (".exe", ".msi", ".dll", ".apk", ".app", ".deb", ".rpm"),
}

# 系統保護目錄：位於這些環境變數所指路徑底下的檔案一律不刪
_PROTECTED_ENV_VARS: tuple[str, ...] = (
    "SystemRoot",
    "windir",
    "ProgramFiles",
    "ProgramFiles(x86)",
    "ProgramData",
    "SystemDrive",
)


def human_size(size: int) -> str:
    """把位元組數轉換成人看得懂的單位（以 1024 進位）。"""
    value = float(max(size, 0))
    for unit in _SIZE_UNITS:
        if value < 1024 or unit == _SIZE_UNITS[-1]:
            return f"{int(value)} B" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} PB"


def type_group_of(path: Path) -> str:
    """回傳檔案所屬的類型名稱，找不到分類時回傳「其他（副檔名）」。"""
    suffix = path.suffix.lower()
    if not suffix:
        return "無副檔名"
    for group, suffixes in TYPE_GROUPS.items():
        if suffix in suffixes:
            return group
    return f"其他（{suffix}）"


@dataclass(frozen=True)
class FileItem:
    """一筆檔案的摘要資訊（不含檔案內容）。"""

    path: Path
    size: int
    mtime: float

    @property
    def name(self) -> str:
        """檔名（含副檔名）。"""
        return self.path.name

    @property
    def kind_text(self) -> str:
        """顯示用的檔案類型。"""
        return type_group_of(self.path)

    @property
    def size_text(self) -> str:
        """顯示用的大小文字。"""
        return human_size(self.size)

    @property
    def mtime_text(self) -> str:
        """顯示用的修改時間。"""
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(self.mtime))


def scan_folder(
    folder: Path,
    keyword: str = "",
    type_group: str = "",
    *,
    limit: int = 20000,
) -> list[FileItem]:
    """掃描資料夾內的「檔案」（不含子資料夾，避免誤刪整個目錄）。

    參數：
        folder：要掃描的資料夾。
        keyword：檔名關鍵字，比對時不分大小寫；空字串代表不過濾。
        type_group：類型名稱（例如「圖片」）；空字串或 ``ALL_TYPES_LABEL`` 代表不過濾。
        limit：最多回傳幾筆，避免超大資料夾卡住介面。

    回傳：
        依檔名排序的檔案清單；資料夾無法讀取時回傳空清單。
    """
    base = Path(folder)
    keywords = keyword.strip().casefold()
    suffixes: tuple[str, ...] | None = None
    if type_group and type_group != ALL_TYPES_LABEL:
        suffixes = TYPE_GROUPS.get(type_group)

    results: list[FileItem] = []
    try:
        iterator = os.scandir(base)
    except OSError:
        return results

    with iterator as entries:
        for entry in entries:
            if len(results) >= limit:
                break
            try:
                # 只收一般檔案；符號連結與資料夾一律略過
                if not entry.is_file(follow_symlinks=False):
                    continue
                stat = entry.stat(follow_symlinks=False)
            except OSError:
                continue

            item = FileItem(path=Path(entry.path), size=stat.st_size, mtime=stat.st_mtime)
            if keywords and keywords not in item.name.casefold():
                continue
            if suffixes is not None and item.path.suffix.lower() not in suffixes:
                continue
            results.append(item)

    results.sort(key=lambda item: item.name.casefold())
    return results


def _normalized(path: Path) -> str:
    """統一路徑的大小寫與分隔符，方便比對。"""
    return os.path.normcase(os.path.abspath(str(path)))


def protected_reason(path: Path) -> str | None:
    """回傳「不可刪除」的原因；可以刪除時回傳 ``None``。

    保護規則刻意保守：系統目錄、程式安裝目錄，以及磁碟根目錄下的檔案一律不刪。
    """
    target = Path(path)
    try:
        target = target.resolve()
    except OSError:
        return "無法解析路徑"

    try:
        if not target.is_file():
            return "不是一般檔案"
    except OSError:
        return "無法讀取檔案資訊"

    normalized = _normalized(target)
    for variable in _PROTECTED_ENV_VARS:
        raw = os.environ.get(variable)
        if not raw:
            continue
        base = _normalized(Path(raw)).rstrip(os.sep)
        if normalized == base or normalized.startswith(base + os.sep):
            return f"位於系統保護目錄（{raw}）"

    if target.anchor and Path(target.anchor) == target.parent:
        return "位於磁碟根目錄"
    return None


@dataclass
class DeleteOutcome:
    """一次刪除操作的結果統計。"""

    deleted: list[Path] = field(default_factory=list)
    failed: list[tuple[Path, str]] = field(default_factory=list)
    skipped: list[tuple[Path, str]] = field(default_factory=list)
    freed_bytes: int = 0

    @property
    def message(self) -> str:
        """組出適合顯示在狀態列的一句話。"""
        parts = [f"已刪除 {len(self.deleted)} 個檔案，釋放 {human_size(self.freed_bytes)}"]
        if self.skipped:
            parts.append(f"略過 {len(self.skipped)} 個（受保護或已不存在）")
        if self.failed:
            parts.append(f"失敗 {len(self.failed)} 個")
        return "，".join(parts)

    @property
    def has_problem(self) -> bool:
        """是否有需要提醒使用者的失敗或略過項目。"""
        return bool(self.failed or self.skipped)


def _explain_error(error: OSError) -> str:
    """把系統錯誤轉成看得懂的中文說明。"""
    if isinstance(error, PermissionError):
        return "沒有權限，檔案可能正被其他程式開啟"
    if isinstance(error, FileNotFoundError):
        return "檔案已不存在"
    return str(error)


def delete_files(items: Sequence[FileItem], *, permanent: bool = False) -> DeleteOutcome:
    """刪除指定的檔案。

    參數：
        items：要刪除的檔案清單。
        permanent：``True`` 代表永久刪除（不進回收筒，無法復原）；
                   ``False`` 代表移到資源回收筒（預設，可還原）。

    回傳：
        ``DeleteOutcome``，內含成功、失敗、略過三種結果。
    """
    outcome = DeleteOutcome()
    for item in items:
        path = item.path
        if not path.exists():
            outcome.skipped.append((path, "檔案已不存在"))
            continue

        reason = protected_reason(path)
        if reason:
            outcome.skipped.append((path, reason))
            continue

        try:
            if permanent:
                path.unlink()
            else:
                move_to_trash([path])
        except OSError as error:
            outcome.failed.append((path, _explain_error(error)))
            continue

        outcome.deleted.append(path)
        outcome.freed_bytes += item.size

    return outcome
