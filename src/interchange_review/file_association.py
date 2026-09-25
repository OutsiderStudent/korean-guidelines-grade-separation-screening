"""Windows용 .igr3 프로젝트 파일 연결과 시작 인수 처리."""

from __future__ import annotations

import ctypes
import os
import sys
from pathlib import Path
from typing import Iterable


PROJECT_EXTENSION = ".igr3"
PROJECT_PROG_ID = "K-GSS.Project"
PROJECT_TYPE_NAME = "K-GSS 입체화검토 프로젝트"


def startup_project_path(arguments: Iterable[str]) -> Path | None:
    """명령행에서 처음 발견한 .igr3 프로젝트 경로를 반환한다."""
    for argument in arguments:
        raw = str(argument).strip().strip('"')
        if not raw or raw.startswith("-"):
            continue
        path = Path(raw).expanduser()
        if path.suffix.lower() == PROJECT_EXTENSION:
            return path
    return None


def open_command(executable: str | Path) -> str:
    """공백·한글 경로에서도 안전한 Windows 열기 명령을 만든다."""
    return f'"{Path(executable).resolve()}" "%1"'


def register_file_association(executable: str | Path | None = None) -> bool:
    """현재 사용자 범위에 .igr3 → 현재 K-GSS EXE 연결을 등록한다."""
    if os.name != "nt":
        return False
    if executable is None:
        if not getattr(sys, "frozen", False):
            return False
        executable = sys.executable

    import winreg

    exe = Path(executable).resolve()
    classes = r"Software\Classes"
    values = {
        fr"{classes}\{PROJECT_EXTENSION}": {
            None: PROJECT_PROG_ID,
            "Content Type": "application/json",
        },
        fr"{classes}\{PROJECT_PROG_ID}": {None: PROJECT_TYPE_NAME},
        fr"{classes}\{PROJECT_PROG_ID}\DefaultIcon": {None: f'"{exe}",0'},
        fr"{classes}\{PROJECT_PROG_ID}\shell\open\command": {None: open_command(exe)},
    }
    try:
        for key_path, entries in values.items():
            with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
                for name, value in entries.items():
                    winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
        # 탐색기가 새 연결과 아이콘을 즉시 다시 읽도록 알린다.
        ctypes.windll.shell32.SHChangeNotify(0x08000000, 0x0000, None, None)
        return True
    except (OSError, AttributeError):
        return False
