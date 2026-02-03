from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

def write_gemini_settings_ini(
    ini_path: str | Path,
    model: str = "gemini-2.5-flash",
    file_path: str = "scheduler_engine.txt",
    prompt: str = "이 문서 핵심 내용을 10줄로 요약해줘.",
    chunk_chars: int = 12000,
    output_file_path: str = "llm_analysis.docx",
) -> Path:
    """
    chat_with_gemini.py에서 사용하는 설정(INI) 파일을 생성한다.
    - 사용자가 제시한 포맷(주석/공백)을 최대한 그대로 맞춘다.
    """
    ini_path = Path(ini_path)

    content = (
        "[GEMINI_SETTINGS]\n"
        "# 사용할 모델명 (예: gemini-2.5-flash, gemini-3-flash-preview)\n"
        f"model = {model}\n\n"
        "# 분석할 파일 경로\n"
        f"file_path = {file_path}\n\n"
        "# Gemini에게 시킬 명령\n"
        f"prompt = {prompt}\n\n"
        "# 기타 설정\n"
        f"chunk_chars = {chunk_chars}\n\n"
        "#결과 출력파일\n"
        f"output_file_path = {output_file_path}\n"
    )

    ini_path.parent.mkdir(parents=True, exist_ok=True)
    ini_path.write_text(content, encoding="utf-8")
    return ini_path


def get_llm_config_filename(
    folder: str | Path = r".\llm",
    prefix: str = "gemini_settings",
    digits: int = 5,   # ✅ 5자리
) -> Path:
    """
    folder 내에서 gemini_settings_00001.ini 형태의 파일을 검색하여
    가장 큰 번호 + 1 파일 경로를 반환한다.
    """
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)

    pat = re.compile(rf"^{re.escape(prefix)}_(\d+)\.ini$", re.IGNORECASE)

    max_n = 0
    for p in folder.glob(f"{prefix}_*.ini"):
        m = pat.match(p.name)
        if not m:
            continue
        n = int(m.group(1))
        if n > max_n:
            max_n = n

    next_n = max_n + 1

    while True:
        out = folder / f"{prefix}_{next_n:0{digits}d}.ini"
        if not out.exists():
            return out
        next_n += 1


def get_last_gemini_settings_ini(
    folder: str | Path = r".\llm",
    prefix: str = "gemini_settings",
) -> Optional[Path]:
    """
    folder 내 gemini_settings_*.ini 중 번호가 가장 큰(마지막) 파일 Path를 반환.
    없으면 None.
    """
    folder = Path(folder)

    pat = re.compile(rf"^{re.escape(prefix)}_(\d+)\.ini$", re.IGNORECASE)

    last_path: Optional[Path] = None
    last_n = -1

    for p in folder.glob(f"{prefix}_*.ini"):
        m = pat.match(p.name)
        if not m:
            continue
        n = int(m.group(1))
        if n > last_n:
            last_n = n
            last_path = p

    return last_path



if __name__ == "__main__":

    llm_config_filename = get_llm_config_filename()
    out = write_gemini_settings_ini(
        llm_config_filename,
        model="gemini-2.5-flash",
        file_path="scheduler_engine.txt",
        prompt="이 문서는 업체별 매출실적을 집계한 내용이다. 내용을 보고서로 재 요약해줘.",
        chunk_chars=12000,
        output_file_path=".\logs\mail_ready\llm_analysis.docx",
    )
    print(f"INI created: {out.resolve()}")
    last = get_last_gemini_settings_ini(r".\llm")
    print(last)


