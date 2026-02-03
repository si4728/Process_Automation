# executor.py
import os
import shlex
import subprocess
import logging

log = logging.getLogger("executor")

def _decode_bytes(data: bytes) -> str:
    """Decode subprocess output robustly across utf-8/cp949 mixed environments."""
    if data is None:
        return ""
    if isinstance(data, str):
        return data
    # Try strict decodes first (so we can fall back correctly)
    for enc in ("utf-8", "utf-8-sig", "cp949", "euc-kr"):
        try:
            return data.decode(enc, errors="strict")
        except UnicodeDecodeError:
            pass
    # Last resort: preserve as much as possible
    try:
        return data.decode("utf-8", errors="backslashreplace")
    except Exception:
        return data.decode("cp949", errors="backslashreplace")

class Executor:
    def run(self, job: dict) -> dict:
        exe_path = job["exe_path"]
        args = job.get("args") or ""
        workdir = job.get("workdir") or ""
        timeout_sec = int(job.get("timeout_sec") or 60)

        result = self.run_command(exe_path, args, workdir, timeout_sec)
        return result

    def run_command(self, exe_path: str, args: str, workdir: str, timeout_sec: int) -> dict:
        exe_path = exe_path.strip()
        ext = os.path.splitext(exe_path.lower())[1]

        # args 파싱(Windows 친화)
        arg_list = shlex.split(args, posix=False) if args else []

        # .bat/.cmd는 cmd /c 로 실행
        if ext in [".bat", ".cmd"]:
            cmd = ["cmd", "/c", exe_path] + arg_list
        else:
            cmd = [exe_path] + arg_list

        log.info("RUN: %s | cwd=%s | timeout=%s", cmd, workdir, timeout_sec)

        p = subprocess.Popen(
            cmd,
            cwd=workdir or None,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=False,
            shell=False
        )

        try:
            out_b, err_b = p.communicate(timeout=timeout_sec)
            status = "SUCCESS" if p.returncode == 0 else "FAIL"
            out_s = _decode_bytes(out_b)
            err_s = _decode_bytes(err_b)
            # FAIL일 때는 전체 stderr/stdout을 DB에 저장할 수 있도록 full도 함께 반환
            return {
                "status": status,
                "exit_code": p.returncode,
                "message": "",
                "stdout_tail": out_s[-4000:],
                "stderr_tail": err_s[-4000:],
                "stdout_full": out_s if status == "FAIL" else None,
                "stderr_full": err_s if status == "FAIL" else None,
            }
        except subprocess.TimeoutExpired:
            p.kill()
            out_b, err_b = p.communicate()
            out_s = _decode_bytes(out_b)
            err_s = _decode_bytes(err_b)
            return {
                "status": "TIMEOUT",
                "exit_code": None,
                "message": f"timeout({timeout_sec}s)",
                "stdout_tail": out_s[-4000:],
                "stderr_tail": err_s[-4000:],
                # TIMEOUT도 나중에 분석할 수 있도록 full 저장을 허용(원치 않으면 None으로 바꿔도 됨)
                "stdout_full": out_s,
                "stderr_full": err_s,
            }
        except Exception as e:
            try:
                p.kill()
            except Exception:
                pass
            return {
                "status": "FAIL",
                "exit_code": None,
                "message": f"exception: {e}",
                "stdout_tail": "",
                "stderr_tail": "",
                "stdout_full": None,
                "stderr_full": None,
            }
