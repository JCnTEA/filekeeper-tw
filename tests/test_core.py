"""檔案管家核心邏輯的單元測試。

執行方式：
    python -m unittest discover -s tests -v
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

# 讓測試能直接匯入上層的 filekeeper 套件
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from filekeeper.core import (  # noqa: E402
    FileItem,
    delete_files,
    human_size,
    protected_reason,
    scan_folder,
    type_group_of,
)


class HumanSizeTest(unittest.TestCase):
    """大小單位轉換。"""

    def test_bytes(self) -> None:
        self.assertEqual(human_size(0), "0 B")
        self.assertEqual(human_size(1023), "1023 B")

    def test_kilobytes(self) -> None:
        self.assertEqual(human_size(1024), "1.0 KB")

    def test_megabytes(self) -> None:
        self.assertEqual(human_size(1024 * 1024 * 3), "3.0 MB")

    def test_negative_is_clamped(self) -> None:
        self.assertEqual(human_size(-5), "0 B")


class TypeGroupTest(unittest.TestCase):
    """檔案類型分類。"""

    def test_image(self) -> None:
        self.assertEqual(type_group_of(Path("照片.JPG")), "圖片")

    def test_code(self) -> None:
        self.assertEqual(type_group_of(Path("main.py")), "程式碼")

    def test_unknown_suffix(self) -> None:
        self.assertEqual(type_group_of(Path("資料.xyz")), "其他（.xyz）")

    def test_no_suffix(self) -> None:
        self.assertEqual(type_group_of(Path("README")), "無副檔名")


class ScanFolderTest(unittest.TestCase):
    """資料夾掃描與篩選。"""

    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.root = Path(self._temp.name)
        (self.root / "筆記.txt").write_text("內容", encoding="utf-8")
        (self.root / "照片.jpg").write_bytes(b"\x00" * 10)
        (self.root / "程式.py").write_text("print(1)", encoding="utf-8")
        (self.root / "子資料夾").mkdir()

    def tearDown(self) -> None:
        self._temp.cleanup()

    def test_only_files(self) -> None:
        items = scan_folder(self.root)
        # 只比較內容，不比較排序（中文檔名的排序依 Unicode 碼位而定）
        self.assertEqual({item.name for item in items}, {"程式.py", "照片.jpg", "筆記.txt"})

    def test_keyword_filter(self) -> None:
        items = scan_folder(self.root, keyword="筆")
        self.assertEqual([item.name for item in items], ["筆記.txt"])

    def test_keyword_is_case_insensitive(self) -> None:
        (self.root / "Report.MD").write_text("x", encoding="utf-8")
        items = scan_folder(self.root, keyword="report")
        self.assertEqual([item.name for item in items], ["Report.MD"])

    def test_type_filter(self) -> None:
        items = scan_folder(self.root, type_group="圖片")
        self.assertEqual([item.name for item in items], ["照片.jpg"])

    def test_missing_folder_returns_empty(self) -> None:
        self.assertEqual(scan_folder(self.root / "不存在"), [])


class ProtectedReasonTest(unittest.TestCase):
    """系統路徑保護。"""

    def test_temp_file_is_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "可刪除.txt"
            path.write_text("x", encoding="utf-8")
            self.assertIsNone(protected_reason(path))

    def test_folder_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            self.assertEqual(protected_reason(Path(temp)), "不是一般檔案")


class DeleteFilesTest(unittest.TestCase):
    """刪除行為。"""

    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.root = Path(self._temp.name)

    def tearDown(self) -> None:
        self._temp.cleanup()

    def _item(self, name: str, content: bytes = b"12345") -> FileItem:
        path = self.root / name
        path.write_bytes(content)
        stat = path.stat()
        return FileItem(path=path, size=stat.st_size, mtime=stat.st_mtime)

    def test_permanent_delete(self) -> None:
        item = self._item("要刪掉.txt")
        outcome = delete_files([item], permanent=True)
        self.assertEqual(outcome.deleted, [item.path])
        self.assertEqual(outcome.freed_bytes, 5)
        self.assertFalse(item.path.exists())
        self.assertFalse(outcome.has_problem)

    def test_missing_file_is_skipped(self) -> None:
        item = self._item("先刪掉.txt")
        item.path.unlink()
        outcome = delete_files([item], permanent=True)
        self.assertEqual(outcome.deleted, [])
        self.assertEqual(outcome.skipped[0][1], "檔案已不存在")
        self.assertTrue(outcome.has_problem)

    @unittest.skipUnless(sys.platform.startswith("win"), "資源回收筒機制僅在 Windows 驗證")
    def test_recycle_bin(self) -> None:
        item = self._item("進回收筒.txt")
        outcome = delete_files([item], permanent=False)
        self.assertEqual(outcome.deleted, [item.path])
        self.assertFalse(item.path.exists())
        self.assertFalse(outcome.has_problem)


if __name__ == "__main__":
    unittest.main()
