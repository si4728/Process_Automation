# flow_runner_v3.py
# - Robust 'on' parsing (dict or str)
# - Basic YAML validation
# - Per-step combined output file, main log prints tail
import sys
import time
import argparse
import subprocess
from pathlib import Path
from datetime import datetime
import yaml  # pip install pyyaml


def _configure_stdio_utf8():
    """Windows 콘솔(cp949)에서 print()가 UnicodeEncodeError로 죽지 않도록 표준출력을 안전 설정."""
    for s in (sys.stdout, sys.stderr):
        try:
            # Python 3.7+ : TextIOWrapper.reconfigure
            s.reconfigure(encoding="utf-8", errors="backslashreplace")
        except Exception:
            pass



def load_yaml(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def fmt_tokens(obj, tokens: dict):
    if isinstance(obj, str):
        out = obj
        for k, v in tokens.items():
            out = out.replace("{" + k + "}", str(v))
        return out
    if isinstance(obj, list):
        return [fmt_tokens(x, tokens) for x in obj]
    if isinstance(obj, dict):
        return {k: fmt_tokens(v, tokens) for k, v in obj.items()}
    return obj


def tail_file(path: Path, nbytes: int = 12000) -> str:
    if not path.exists():
        return ""
    with path.open("rb") as f:
        try:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - nbytes), 0)
        except Exception:
            f.seek(0)
        data = f.read()

    # 중요: errors="replace"를 먼저 쓰면(특히 utf-8) 실패가 '예외'로 나오지 않아
    # cp949(또는 euc-kr)로 재시도를 못하고 '����'가 섞인 채로 반환됩니다.
    # 따라서 "strict → 실패 시 다음 인코딩" 순서로 시도합니다.
    for enc in ("utf-8", "utf-8-sig"):
        try:
            return data.decode(enc, errors="strict")
        except UnicodeDecodeError:
            pass

    for enc in ("cp949", "euc-kr"):
        try:
            return data.decode(enc, errors="strict")
        except UnicodeDecodeError:
            pass

    # 마지막 수단: 최대한 보존(못 읽는 바이트는 \x.. 또는 \u..로 표시)
    try:
        return data.decode("utf-8", errors="backslashreplace")
    except Exception:
        return data.decode("cp949", errors="backslashreplace")


class TeeLogger:
    def __init__(self, log_path: Path | None):
        self.log_path = log_path
        self.f = None
        if log_path is not None:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            self.f = log_path.open("a", encoding="utf-8", errors="replace")

    def close(self):
        try:
            if self.f:
                self.f.flush()
                self.f.close()
        except Exception:
            pass

    def _write(self, level: str, msg: str):
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"{ts} | {level:<5} | {msg}"

        # 콘솔 인코딩(cp949 등) 때문에 출력이 실패하더라도 실행이 중단되지 않게 처리
        try:
            print(line)
        except UnicodeEncodeError:
            enc = getattr(sys.stdout, "encoding", None) or "utf-8"
            try:
                sys.stdout.buffer.write((line + "").encode(enc, errors="backslashreplace"))
                sys.stdout.flush()
            except Exception:
                # 최후 수단: 아예 ASCII 안전 문자열로 변환 후 출력
                print((line + "").encode("ascii", errors="backslashreplace").decode("ascii", errors="ignore"), end="")

        if self.f:
            self.f.write(line + "\n")
            self.f.flush()

    def info(self, msg: str): self._write("INFO", msg)
    def warn(self, msg: str): self._write("WARN", msg)
    def error(self, msg: str): self._write("ERROR", msg)


# def normalize_on(step: dict):
#     """
#     지원 형태:
#       on: {success: a2, fail: a3, always: a4}
#       on: "a2"   # rc와 무관하게 다음 step
#       또는 (레거시/실수 방지) success/fail 키가 step 최상위에 있을 경우 병합
#     """
#     on = step.get("on", None)

#     # 레거시 형태: step 최상위에 success/fail이 있으면 on dict로 흡수
#     top_success = step.get("success", None)
#     top_fail = step.get("fail", None)
#     if top_success is not None or top_fail is not None:
#         if on is None:
#             on = {}
#         if isinstance(on, dict):
#             if top_success is not None:
#                 on.setdefault("success", top_success)
#             if top_fail is not None:
#                 on.setdefault("fail", top_fail)

#     return on

def normalize_on(step: dict):
    """
    지원 형태:
      on: {success: a2, fail: a3, always: a4, next: a5}
      on: "a2"   # rc와 무관하게 다음 step

    + 추가 지원(최상위 키):
      next: a2   -> success로 간주
      fail: a3   -> fail로 간주
      success: a2, always: a4 도 동일
    """
    on = step.get("on", None)

    # 최상위 전이 키들(레거시/편의)
    top_next = step.get("next", None)
    top_success = step.get("success", None)
    top_fail = step.get("fail", None)
    top_always = step.get("always", None)

    # on이 없고 최상위 키가 있으면 dict로 생성
    if on is None and (top_next is not None or top_success is not None or top_fail is not None or top_always is not None):
        on = {}

    # on이 dict일 때만 병합
    if isinstance(on, dict):
        # next는 성공 전이로 취급(가장 안전)
        if top_next is not None:
            on.setdefault("success", top_next)

        if top_success is not None:
            on.setdefault("success", top_success)

        if top_fail is not None:
            on.setdefault("fail", top_fail)

        if top_always is not None:
            on.setdefault("always", top_always)

    return on

def next_step(on, rc: int):
    if on is None:
        return None
    if isinstance(on, str):
        return on  # 무조건 다음 step
    if isinstance(on, dict):
        if rc == 0 and on.get("success") is not None:
            return on.get("success")
        if rc != 0 and on.get("fail") is not None:
            return on.get("fail")
        if on.get("always") is not None:
            return on.get("always")
        return on.get("next")
    return None


def validate_cfg(cfg: dict, log: TeeLogger, flow_name: str) -> bool:
    steps = cfg.get("steps", []) or []
    if not isinstance(steps, list) or not steps:
        log.error(f"[{flow_name}] steps가 비어있거나 리스트가 아닙니다.")
        return False

    ids = []
    for s in steps:
        if not isinstance(s, dict):
            log.error(f"[{flow_name}] step 항목이 dict가 아닙니다: {s}")
            return False
        sid = s.get("id")
        if not sid:
            log.error(f"[{flow_name}] step에 'id'가 없습니다: {s}")
            return False
        ids.append(sid)
        if not s.get("cmd"):
            log.error(f"[{flow_name}] step '{sid}' cmd가 비었습니다.")
            return False

    if len(ids) != len(set(ids)):
        log.error(f"[{flow_name}] step id가 중복되었습니다: {ids}")
        return False

    idset = set(ids)
    # 참조 검증
    for s in steps:
        sid = s["id"]
        on = normalize_on(s)
        refs = []
        if isinstance(on, str):
            refs.append(on)
        elif isinstance(on, dict):
            for k in ("success", "fail", "always", "next"):
                v = on.get(k)
                if isinstance(v, str):
                    refs.append(v)

        for r in refs:
            if r not in idset:
                log.error(f"[{flow_name}] step '{sid}'가 참조하는 다음 step '{r}'가 steps에 없습니다.")
                return False

    return True


def run_step(cmd, workdir: Path | None, timeout: int | None, out_path: Path):
    t0 = time.time()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        with out_path.open("wb") as f:
            rc = subprocess.run(
                cmd,
                cwd=str(workdir) if workdir else None,
                stdout=f,
                stderr=subprocess.STDOUT,
                timeout=timeout,
            ).returncode
        dt = time.time() - t0
        return rc, dt, None
    except subprocess.TimeoutExpired:
        dt = time.time() - t0
        return 124, dt, f"TimeoutExpired after {timeout}s"
    except FileNotFoundError as e:
        dt = time.time() - t0
        return 127, dt, f"FileNotFoundError: {e}"
    except Exception as e:
        dt = time.time() - t0
        return 1, dt, f"Exception: {e}"


def main():
    _configure_stdio_utf8()
    ap = argparse.ArgumentParser()
    ap.add_argument("flow_yaml", help="flow yaml path")
    ap.add_argument("--name", default=None, help="Flow name shown in logs")
    ap.add_argument("--start", default=None, help="start step id (default: first step)")
    ap.add_argument("--log-dir", default=None, help="override log directory")
    ap.add_argument("--timeout", type=int, default=None, help="override globals.timeout_sec")
    ap.add_argument("--dry-run", action="store_true", help="validate and print steps only")
    args = ap.parse_args()

    flow_path = Path(args.flow_yaml).resolve()
    if not flow_path.exists():
        print(f"[FLOW] config not found: {flow_path}", file=sys.stderr)
        return 2

    cfg = load_yaml(flow_path) or {}
    g = cfg.get("globals", {}) or {}

    flow_name = args.name or cfg.get("name") or flow_path.stem

    # log dir 결정: --log-dir > globals.log_dir > <yaml_dir>/logs
    base_log_dir = args.log_dir or g.get("log_dir")
    log_dir = Path(base_log_dir).resolve() if base_log_dir else (flow_path.parent / "logs")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    main_log_path = log_dir / f"{flow_name}_{stamp}.log"
    log = TeeLogger(main_log_path)

    try:
        tokens = {
            "python": g.get("python", sys.executable),
            "flow_dir": str(flow_path.parent),
            "log_dir": str(log_dir),
            "stamp": stamp,
        }

        workdir = Path(g["workdir"]).resolve() if g.get("workdir") else None
        timeout = args.timeout if args.timeout is not None else g.get("timeout_sec", None)

        log.info(f"[{flow_name}] START flow={flow_path}")
        log.info(f"[{flow_name}] workdir={workdir or '(none)'} timeout={timeout or '(none)'} log={main_log_path}")

        if not validate_cfg(cfg, log, flow_name):
            return 2

        steps = cfg.get("steps", []) or []
        step_map = {s["id"]: s for s in steps}

        current = args.start or steps[0]["id"]
        visited = set()
        path_taken = []
        started_at = time.time()

        if args.dry_run:
            log.info(f"[{flow_name}] DRY-RUN: steps=" + ", ".join(step_map.keys()))
            return 0

        while current:
            if current not in step_map:
                log.error(f"[{flow_name}] Unknown step id: {current}")
                return 2
            if current in visited:
                log.error(f"[{flow_name}] Loop detected at step: {current}")
                return 2
            visited.add(current)

            step = step_map[current]
            step_name = step.get("name", current)

            cmd = fmt_tokens(step.get("cmd", []), tokens)
            if not isinstance(cmd, list) or not cmd:
                log.error(f"[{flow_name}] Step '{current}' cmd는 리스트 형태여야 합니다.")
                return 2

            step_out = log_dir / f"{flow_name}_{stamp}_{current}.out.txt"

            log.info(f"[{flow_name}] >>> RUN {current} ({step_name})")
            log.info(f"[{flow_name}] CMD: {cmd}")
            log.info(f"[{flow_name}] OUT: {step_out}")

            # step별 timeout_sec가 있으면 우선
            step_timeout = step.get("timeout_sec", None)
            eff_timeout = step_timeout if step_timeout is not None else timeout

            rc, dt, err_msg = run_step(cmd, workdir=workdir, timeout=eff_timeout, out_path=step_out)

            log.info(f"[{flow_name}] <<< END {current} rc={rc} elapsed={dt:.2f}s")
            if err_msg:
                log.warn(f"[{flow_name}] {err_msg}")

            tail_text = tail_file(step_out, 12000).rstrip()
            if tail_text:
                log.info(f"[{flow_name}] [OUTPUT TAIL]\n{tail_text}")

            path_taken.append({"step": current, "rc": rc, "elapsed": dt})

            on = normalize_on(step)
            current = next_step(on, rc)

        total = time.time() - started_at
        ok = all(x["rc"] == 0 for x in path_taken) if path_taken else False
        last = path_taken[-1]["step"] if path_taken else "(none)"

        log.info(f"[{flow_name}] DONE status={'OK' if ok else 'FAIL'} total={total:.2f}s last={last}")
        log.info(f"[{flow_name}] PATH: " + " -> ".join([f"{x['step']}[rc={x['rc']}]" for x in path_taken]))

        return 0 if ok else 1

    finally:
        log.close()


if __name__ == "__main__":
    raise SystemExit(main())
