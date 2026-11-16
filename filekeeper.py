"""檔案管家（FileKeeper TW）程式入口。

用法：
    python filekeeper.py

或直接雙擊資料夾中的「啟動.bat」（Windows）。
"""

from __future__ import annotations


def _fatal(message: str) -> None:
    """在完全沒有圖形介面可用時，改用系統對話框顯示錯誤訊息。"""
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, message, "檔案管家 FileKeeper TW", 0x10)
    except Exception:
        print(message)


def _check_tkinter() -> str | None:
    """先確認 tkinter 真的能建立視窗；可用時回傳 ``None``，否則回傳錯誤說明。"""
    try:
        import tkinter as tk

        probe = tk.Tk()
        probe.destroy()
    except Exception as error:  # 匯入失敗或缺 Tcl 執行環境都會走到這裡
        return f"{type(error).__name__}：{error}"
    return None


def main() -> None:
    """啟動圖形介面。"""
    problem = _check_tkinter()
    if problem is not None:
        _fatal(
            "無法啟動圖形介面：目前使用的 Python 沒有可用的 tkinter。\n\n"
            "請改安裝官方版 Python（https://www.python.org/downloads/），\n"
            "安裝時保留「tcl/tk and IDLE」選項，或改用專案內的「啟動.bat」。\n\n"
            f"詳細資訊：{problem}"
        )
        return

    from filekeeper.ui import main as run_app

    run_app()


if __name__ == "__main__":
    main()
