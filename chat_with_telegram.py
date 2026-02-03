import os
import time
from pathlib import Path
import requests


BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
#CHAT_ID   = os.environ["TELEGRAM_CHAT_ID"]
CHAT_ID = "1762561636"
print("TOKEN startswith:", BOT_TOKEN[:10])


DEFAULT_MESSAGE = "✅ 작업이 완료되었습니다. 첨부파일 확인 바랍니다."
DEFAULT_FILE    = r"C:\access\rpa\summary\1월매출실적.txt"  # <- 여기만 바꾸면 됨


def _api_url(method: str) -> str:
    return f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"


def _post_with_retry(url: str, *, json=None, data=None, files=None, timeout=60, max_retry=5):
    """
    - 네트워크/일시적 오류 재시도
    - 429(Too Many Requests)면 retry_after를 읽어 대기
    """
    for i in range(max_retry):
        try:
            r = requests.post(url, json=json, data=data, files=files, timeout=timeout)

                # ✅ 추가: 에러 본문 출력 (핵심)
            if r.status_code >= 400:
                print("HTTP", r.status_code, "URL:", url)
                print("RESPONSE:", r.text)

            # 레이트리밋 처리
            if r.status_code == 429:
                try:
                    retry_after = r.json().get("parameters", {}).get("retry_after", 2)
                except Exception:
                    retry_after = 2
                time.sleep(int(retry_after) + 1)
                continue

            r.raise_for_status()
            return r

        except requests.RequestException:
            if i == max_retry - 1:
                raise
            time.sleep(1.5 * (i + 1))  # 간단 백오프


def tg_send_text(chat_id:str, text: str) -> None:
    url = _api_url("sendMessage")
    _post_with_retry(url, json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True}, timeout=20)


def tg_send_file(chat_id:str, file_path: str | Path, caption: str | None = None) -> None:
    path = Path(file_path)
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(str(path))

    # sendDocument는 봇 파일 업로드 크기 제한이 있으니(대략 50MB 안내) 큰 파일은 예외 처리 권장
    size_mb = path.stat().st_size / (1024 * 1024)
    if size_mb > 49:
        raise ValueError(f"파일이 너무 큽니다: {size_mb:.1f}MB (압축/링크 전송 권장)")

    url = _api_url("sendDocument")
    data = {"chat_id": chat_id}
    if caption:
        data["caption"] = caption

    with path.open("rb") as f:
        files = {"document": (path.name, f)}
        _post_with_retry(url, data=data, files=files, timeout=120)


def send_fixed_message_and_file(
    chat_id:str = DEFAULT_MESSAGE, 
    message: str = DEFAULT_MESSAGE,
    file_path: str | Path = DEFAULT_FILE
) -> None:
    # 1) 텍스트 먼저
    #chat_id = CHAT_ID
    tg_send_text(chat_id, message)

    # 2) 파일 전송(캡션에 파일명/크기)
    p = Path(file_path)
    cap = f"{p.name} ({p.stat().st_size/1024:.0f} KB)"
    tg_send_file(chat_id, p, caption=cap)


if __name__ == "__main__":
    # 실행 테스트
    send_fixed_message_and_file(CHAT_ID)
