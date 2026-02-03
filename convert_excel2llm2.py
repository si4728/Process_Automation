#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
convert_excel2llm.py (개선 버전)
- Excel(.xlsx/.xlsm)을 시트별로 CSV / JSON / TXT로 변환
- TXT: 탭으로 구분된 텍스트 형식 (Excel의 '텍스트로 저장'과 동일)
  * 수식은 저장하지 않음 (계산된 값만 저장)
  * 계산된 값을 얻으려면 --data-only 옵션 사용 권장
- CSV: 쉼표로 구분된 값
- JSON: records(딕셔너리 배열) 또는 matrix(2차원 배열) 형식
- 병합셀(fill-merged) 지원
- 수식/계산값 출력 선택 가능
- 개선사항:
  1. 외부 모듈 의존성 안전 처리
  2. 포괄적 에러 핸들링
  3. Python 3.7+ 호환 타입 힌트
  4. 출력 파일 목록 명확화

Usage examples:
  python convert_excel2llm.py input.xlsx --formats txt --data-only
  python convert_excel2llm.py input.xlsx --formats csv,json --json-mode records
  python convert_excel2llm.py input.xlsx --formats txt,csv,json --data-only
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import re
import sys
from datetime import date, datetime, time
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from openpyxl import load_workbook
except ImportError:
    print("ERROR: openpyxl is required. Install with: pip install openpyxl")
    sys.exit(1)
# Windows 콘솔 UTF-8 출력 설정
if sys.platform == 'win32':
    try:
        # stdout, stderr를 UTF-8로 재설정
        import codecs
        sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
        sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')
    except Exception:
        pass  # 실패해도 계속 진행

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# -----------------------------
# Helpers
# -----------------------------
def safe_filename(name: str) -> str:
    """시트명을 파일명으로 쓸 수 있게 정리"""
    name = name.strip()
    name = re.sub(r'[\\/:*?"<>|]+', "_", name)
    name = re.sub(r"\s+", " ", name)
    return name or "sheet"


def json_default(obj: Any) -> Any:
    """JSON 직렬화 불가 타입 처리"""
    if isinstance(obj, (datetime, date, time)):
        return obj.isoformat()
    return str(obj)


def coerce_cell_for_text(v: Any) -> str:
    """CSV 출력용 문자열 변환"""
    if v is None:
        return ""
    if isinstance(v, (datetime, date, time)):
        return v.isoformat()
    return str(v)


def normalize_headers(headers: List[Any]) -> List[str]:
    """헤더 None/빈값/중복 처리"""
    out: List[str] = []
    seen: Dict[str, int] = {}
    for i, h in enumerate(headers, start=1):
        key = str(h).strip() if h is not None else f"col_{i}"
        key = key if key else f"col_{i}"
        base = key
        if base in seen:
            seen[base] += 1
            key = f"{base}_{seen[base]}"
        else:
            seen[base] = 1
        out.append(key)
    return out


# -----------------------------
# Merged cell handling
# -----------------------------
def build_merged_cell_map(ws) -> Dict[str, str]:
    """
    병합셀 내 각 좌표 -> 좌상단 셀 좌표로 매핑.
    export 단계에서만 이 맵을 참조하여 병합셀 값 채우기.
    """
    merged_map: Dict[str, str] = {}
    try:
        for merged_range in ws.merged_cells.ranges:
            tl = ws.cell(merged_range.min_row, merged_range.min_col).coordinate
            for r in range(merged_range.min_row, merged_range.max_row + 1):
                for c in range(merged_range.min_col, merged_range.max_col + 1):
                    coord = ws.cell(r, c).coordinate
                    if coord != tl:
                        merged_map[coord] = tl
    except Exception as e:
        logger.warning(f"병합셀 처리 중 경고: {e}")
    return merged_map


def iter_rows_values(
    ws,
    min_row: int = 1,
    max_row: Optional[int] = None,
    min_col: int = 1,
    max_col: Optional[int] = None,
    merged_map: Optional[Dict[str, str]] = None,
):
    """
    병합셀 좌표는 좌상단 값으로 치환해서 yield
    """
    for row in ws.iter_rows(
        min_row=min_row,
        max_row=max_row,
        min_col=min_col,
        max_col=max_col,
        values_only=False,
    ):
        out = []
        for cell in row:
            if merged_map and cell.coordinate in merged_map:
                tl = merged_map[cell.coordinate]
                out.append(ws[tl].value)
            else:
                out.append(cell.value)
        yield out


# -----------------------------
# Writers
# -----------------------------
def write_csv(
    ws,
    out_path: Path,
    min_row: int,
    max_row: Optional[int],
    min_col: int,
    max_col: Optional[int],
    merged_map: Optional[Dict[str, str]],
) -> None:
    """CSV 파일 작성"""
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f, quoting=csv.QUOTE_MINIMAL)
            for row in iter_rows_values(
                ws,
                min_row=min_row,
                max_row=max_row,
                min_col=min_col,
                max_col=max_col,
                merged_map=merged_map,
            ):
                w.writerow([coerce_cell_for_text(v) for v in row])
        logger.info(f"생성됨: {out_path}")
    except Exception as e:
        logger.error(f"CSV 작성 실패 ({out_path}): {e}")


def sheet_to_records(
    ws,
    header_row: int,
    data_start_row: Optional[int],
    min_col: int,
    max_col: Optional[int],
    max_row: Optional[int],
    drop_empty_rows: bool,
    merged_map: Optional[Dict[str, str]],
) -> List[Dict[str, Any]]:
    """
    header_row를 컬럼명으로 사용하여 records 생성
    """
    if data_start_row is None:
        data_start_row = header_row + 1

    try:
        header_values = next(
            iter_rows_values(
                ws,
                min_row=header_row,
                max_row=header_row,
                min_col=min_col,
                max_col=max_col,
                merged_map=merged_map,
            ),
            None,
        )
        if header_values is None:
            return []

        headers = normalize_headers(list(header_values))

        records: List[Dict[str, Any]] = []
        for row in iter_rows_values(
            ws,
            min_row=data_start_row,
            max_row=max_row,
            min_col=min_col,
            max_col=max_col,
            merged_map=merged_map,
        ):
            if drop_empty_rows and all(v is None for v in row):
                continue
            rec = {headers[i]: (row[i] if i < len(row) else None) for i in range(len(headers))}
            records.append(rec)
        return records
    except Exception as e:
        logger.error(f"레코드 변환 실패: {e}")
        return []


def write_json(
    ws,
    out_path: Path,
    mode: str,
    header_row: int,
    min_row: int,
    max_row: Optional[int],
    min_col: int,
    max_col: Optional[int],
    drop_empty_rows: bool,
    merged_map: Optional[Dict[str, str]],
) -> None:
    """JSON 파일 작성"""
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)

        if mode == "records":
            records = sheet_to_records(
                ws,
                header_row=header_row,
                data_start_row=max(min_row, header_row + 1),
                min_col=min_col,
                max_col=max_col,
                max_row=max_row,
                drop_empty_rows=drop_empty_rows,
                merged_map=merged_map,
            )
            with out_path.open("w", encoding="utf-8") as f:
                json.dump(records, f, ensure_ascii=False, indent=2, default=json_default)

        elif mode == "matrix":
            matrix: List[List[Any]] = []
            for row in iter_rows_values(
                ws,
                min_row=min_row,
                max_row=max_row,
                min_col=min_col,
                max_col=max_col,
                merged_map=merged_map,
            ):
                if drop_empty_rows and all(v is None for v in row):
                    continue
                matrix.append(list(row))
            with out_path.open("w", encoding="utf-8") as f:
                json.dump(matrix, f, ensure_ascii=False, indent=2, default=json_default)
        else:
            raise ValueError(f"지원하지 않는 JSON 모드: {mode}")
        
        logger.info(f"생성됨: {out_path}")
    except Exception as e:
        logger.error(f"JSON 작성 실패 ({out_path}): {e}")


def write_txt(
    ws,
    out_path: Path,
    min_row: int,
    max_row: Optional[int],
    min_col: int,
    max_col: Optional[int],
    merged_map: Optional[Dict[str, str]],
) -> None:
    """
    TXT 파일 작성: 탭으로 구분된 텍스트 (Excel의 '텍스트로 저장'과 동일)
    수식은 저장하지 않고 계산된 결과값만 저장
    """
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w", encoding="utf-8") as f:
            for row_cells in ws.iter_rows(
                min_row=min_row,
                max_row=max_row,
                min_col=min_col,
                max_col=max_col,
                values_only=False,
            ):
                row_values = []
                for cell in row_cells:
                    # 병합셀 처리
                    if merged_map and cell.coordinate in merged_map:
                        tl = merged_map[cell.coordinate]
                        tl_cell = ws[tl]
                        # 수식이 있는 경우 계산된 값 사용 (data_type이 'f'이고 수식 문자열인 경우)
                        if tl_cell.data_type == 'f' and isinstance(tl_cell.value, str) and tl_cell.value.startswith('='):
                            # 수식은 제외하고 빈 값으로 처리 (계산된 값이 캐시되지 않은 경우)
                            # 실제로는 openpyxl의 data_only=True로 로드해야 계산된 값을 얻을 수 있음
                            value = ""
                            logger.warning(f"수식이 발견됨 ({tl_cell.coordinate}): {tl_cell.value}. 계산된 값을 얻으려면 --data-only 옵션을 사용하세요.")
                        else:
                            value = tl_cell.value
                    else:
                        # 수식이 있는 경우 경고
                        if cell.data_type == 'f' and isinstance(cell.value, str) and cell.value.startswith('='):
                            value = ""
                            logger.warning(f"수식이 발견됨 ({cell.coordinate}): {cell.value}. 계산된 값을 얻으려면 --data-only 옵션을 사용하세요.")
                        else:
                            value = cell.value
                    
                    row_values.append(value)
                
                # 탭으로 구분된 텍스트 생성
                line = "\t".join([coerce_cell_for_text(v) for v in row_values])
                f.write(line + "\n")
        
        logger.info(f"생성됨: {out_path}")
    except Exception as e:
        logger.error(f"TXT 작성 실패 ({out_path}): {e}")


# -----------------------------
# LLM Config (선택적)
# -----------------------------
def create_llm_config(output_file: Path, out_dir: Path) -> None:
    """
    llm_config 모듈이 있으면 설정 파일 생성
    """
    try:
        import llm_config
        
        llm_config_file = llm_config.get_llm_config_filename()
        llm_config.write_gemini_settings_ini(
            llm_config_file,
            model="gemini-2.5-flash",
            file_path=str(output_file),
            prompt="이 문서는 업체별 매출실적을 집계한 내용이다. 내용을 보고서로 재 요약해줘.",
            chunk_chars=65000,
            output_file_path=".\\logs\\mail_ready\\llm_analysis.docx"
        )
        logger.info(f">>>>LLM 설정 파일 생성됨: {llm_config_file}")
    except ImportError:
        logger.info("llm_config 모듈이 없어 설정 파일을 생성하지 않습니다.")
    except Exception as e:
        logger.warning(f"LLM 설정 파일 생성 실패: {e}")


# -----------------------------
# Main
# -----------------------------
def main() -> None:
    ap = argparse.ArgumentParser(
        description="Convert Excel to CSV/JSON/TXT per sheet (LLM-friendly).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s input.xlsx --formats txt --data-only
  %(prog)s input.xlsx --formats csv,json --json-mode records
  %(prog)s input.xlsx --formats txt,csv,json --data-only --fill-merged

Output formats:
  - CSV: 쉼표로 구분된 값 (UTF-8 BOM)
  - JSON: records 또는 matrix 형식
  - TXT: 탭으로 구분된 텍스트 (Excel '텍스트로 저장'과 동일)
    * 수식이 아닌 계산된 값만 저장 (--data-only 권장)
        """
    )
    ap.add_argument("excel", help="Input Excel file path (.xlsx/.xlsm)")
    ap.add_argument("--outdir", default="excel_export", help="Output directory (default: excel_export)")

    ap.add_argument(
        "--formats",
        default="csv,json",
        help="Comma-separated: csv,json,txt (default: csv,json)",
    )
    ap.add_argument(
        "--json-mode",
        choices=["records", "matrix"],
        default="records",
        help="JSON mode (default: records). CSV/TXT는 이 옵션과 무관",
    )

    ap.add_argument("--header-row", type=int, default=1, help="Header row for records/jsonl (default: 1)")
    ap.add_argument("--min-row", type=int, default=1, help="Start row to export (default: 1)")
    ap.add_argument("--max-row", type=int, default=None, help="End row to export (default: None=all)")

    ap.add_argument("--min-col", type=int, default=1, help="Start column to export (default: 1)")
    ap.add_argument("--max-col", type=int, default=None, help="End column to export (default: None=all)")

    ap.add_argument(
        "--data-only",
        action="store_true",
        help="Export calculated values (openpyxl data_only=True)",
    )
    ap.add_argument(
        "--keep-formulas",
        action="store_true",
        help="Export formulas as strings (overrides --data-only)",
    )

    ap.add_argument("--fill-merged", action="store_true", help="Fill merged-cell values")
    ap.add_argument("--include-hidden", action="store_true", help="Include hidden sheets")
    ap.add_argument("--drop-empty-rows", action="store_true", help="Drop fully empty rows")

    args = ap.parse_args()

    # 입력 파일 확인
    in_path = Path(args.excel).expanduser().resolve()
    if not in_path.exists():
        logger.error(f"입력 파일을 찾을 수 없음: {in_path}")
        sys.exit(1)

    # 출력 디렉토리 생성
    out_dir = Path(args.outdir).expanduser().resolve()
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        logger.error(f"출력 디렉토리 생성 실패: {e}")
        sys.exit(1)

    # 출력 형식 파싱
    formats = [x.strip().lower() for x in args.formats.split(",") if x.strip()]
    if not formats:
        logger.error("출력 형식이 지정되지 않음 (--formats csv,json,txt)")
        sys.exit(1)

    # 형식 검증
    valid_formats = {"csv", "json", "txt"}
    invalid = set(formats) - valid_formats
    if invalid:
        logger.error(f"지원하지 않는 형식: {invalid}. 사용 가능: {valid_formats}")
        sys.exit(1)

    # keep_formulas가 있으면 data_only False
    data_only = bool(args.data_only) and not bool(args.keep_formulas)

    # Excel 파일 로드
    try:
        logger.info(f"Excel 파일 로드 중: {in_path}")
        wb = load_workbook(filename=in_path, data_only=data_only, read_only=False)
    except Exception as e:
        logger.error(f"Excel 파일 로드 실패: {e}")
        sys.exit(1)

    # 각 시트 처리
    output_files: List[Path] = []
    processed_sheets = 0

    for ws in wb.worksheets:
        # 숨겨진 시트 처리
        if (not args.include_hidden) and (ws.sheet_state != "visible"):
            logger.debug(f"시트 건너뜀 (숨김): {ws.title}")
            continue

        sheet_name = safe_filename(ws.title)
        base = out_dir / sheet_name

        # 병합셀 맵 생성
        merged_map = build_merged_cell_map(ws) if args.fill_merged else None

        logger.info(f"시트 처리 중: {ws.title}")

        # CSV
        if "csv" in formats:
            out_file = base.with_suffix(".csv")
            write_csv(
                ws,
                out_file,
                min_row=args.min_row,
                max_row=args.max_row,
                min_col=args.min_col,
                max_col=args.max_col,
                merged_map=merged_map,
            )
            output_files.append(out_file)

        # JSON
        if "json" in formats:
            out_file = base.with_suffix(".json")
            write_json(
                ws,
                out_file,
                mode=args.json_mode,
                header_row=args.header_row,
                min_row=args.min_row,
                max_row=args.max_row,
                min_col=args.min_col,
                max_col=args.max_col,
                drop_empty_rows=args.drop_empty_rows,
                merged_map=merged_map,
            )
            output_files.append(out_file)

        # TXT (탭 구분 텍스트)
        if "txt" in formats:
            out_file = base.with_suffix(".txt")
            write_txt(
                ws,
                out_file,
                min_row=args.min_row,
                max_row=args.max_row,
                min_col=args.min_col,
                max_col=args.max_col,
                merged_map=merged_map,
            )
            output_files.append(out_file)

        processed_sheets += 1

    # 완료 메시지
    logger.info(f"\n{'='*60}")
    logger.info(f"변환 완료!")
    logger.info(f"처리된 시트: {processed_sheets}개")
    logger.info(f"출력 디렉토리: {out_dir}")
    logger.info(f"생성된 파일: {len(output_files)}개")
    
    if output_files:
        logger.info("\n생성된 파일 목록:")
        for f in output_files:
            logger.info(f" {f.relative_to(out_dir.parent)}")
        
        # LLM 설정 파일 생성 
        if output_files:
            create_llm_config(output_files[-1], out_dir)
    
    logger.info(f"{'='*60}")


if __name__ == "__main__":
    main()
