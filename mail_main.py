import email
from email.header import decode_header, make_header
from email.utils import parseaddr
from email.mime.text import MIMEText
from email.message import EmailMessage
import mimetypes
import smtplib
import imaplib
from pathlib import Path
from imap_tools.imap_utf7 import utf7_decode
import os
import configparser
import sys
import re
import argparse
import yaml

## temp solution
APP_DIR = Path(__file__).resolve().parents[1]  # adir의 상위 = app
sys.path.insert(0, str(APP_DIR))
import llm_config
##################################################################


with open("./email/config.yaml") as fp:
    config = yaml.load(fp, yaml.FullLoader)

IMAP_SERVER = config["IMAP_SERVER"]
IMAP_PORT = config["IMAP_PORT"]
SMTP_SERVER = config["SMTP_SERVER"]
SMTP_PORT = config["SMTP_PORT"]


with open("./email/secret.local") as fp:
    secrets = yaml.load(fp, yaml.FullLoader)
MAIL_ID = secrets["MAIL_ID"]
MAIL_PW = secrets["MAIL_PW"]
SENDER_ID = secrets["SENDER_ID"]

LIST_RE = re.compile(
    r"^\((?P<flags>.+)\)\s+" r'(?:"(?P<delim>.+)"|NIL)\s+' r'(?:"(?P<name>.+)")$'
)

def parse_mailbox_list(line: str):
    res = re.search(LIST_RE, line)
    flags = res.group("flags")
    delim = res.group("delim")
    name = res.group("name")
    return flags, delim, name

def decode_mime_header(value: str) -> str:
    if not value:
        return ""
    # 여러 파트로 쪼개진 헤더도 안전하게 처리
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        # 최후 fallback
        parts = decode_header(value)
        out = []
        for v, enc in parts:
            if isinstance(v, bytes):
                out.append(v.decode(enc or "utf-8", errors="replace"))
            else:
                out.append(v)
        return "".join(out)


def safe_utf7_decode(v):
    # utf7_decode는 bytes 입력을 기대함
    if isinstance(v, (bytes, bytearray)):
        return utf7_decode(v)
    return v  # str이면 그대로

def list_mailboxes(imap):
    status, mail_boxes = imap.list()
    if status != "OK":
        return []

    decoded = []
    for raw in mail_boxes:
        # raw는 보통 bytes
        if isinstance(raw, (bytes, bytearray)):
            line = raw.decode("utf-8", errors="replace")
        else:
            line = str(raw)

        # 마지막 따옴표 안의 폴더명 추출
        if '"' in line:
            name = line.split('"')[-2]   # <- 여기서 name은 str
        else:
            name = line.split()[-1]      # <- 여기서도 str

        # ✅ name이 str이므로 utf7_decode 호출하면 안 됨
        # IMAP modified UTF-7 문자열(&...-) 자체는 ASCII str로 전달되므로,
        # 필요하면 "bytes로 인코딩 후" decode 하거나,
        # 그냥 그대로 출력해도 대부분 문제 없음.
        #
        # 가장 안전: "&"가 포함된 경우에만 bytes로 변환해서 decode 시도
        if "&" in name:
            try:
                decoded_name = utf7_decode(name.encode("ascii", errors="ignore"))
            except Exception:
                decoded_name = name
        else:
            decoded_name = name

        decoded.append(decoded_name)

    return decoded


def fetch_latest_subject_from_inbox(imap: imaplib.IMAP4_SSL):
    status, _ = imap.select("INBOX")
    if status != "OK":
        raise RuntimeError("Failed to select INBOX")

    status, messages = imap.search(None, "ALL")
    if status != "OK":
        raise RuntimeError("Search failed")

    mail_ids = messages[0].split()
    if not mail_ids:
        return None  # 메일 없음

    latest_id = mail_ids[-1]
    status, msg_data = imap.fetch(latest_id, "(RFC822)")
    if status != "OK" or not msg_data or not msg_data[0]:
        raise RuntimeError("Fetch failed")

    raw_email = msg_data[0][1]
    msg = email.message_from_bytes(raw_email)

    subject = decode_mime_header(msg.get("Subject", ""))
    from_raw = msg.get("From", "")
    from_name, from_addr = parseaddr(from_raw)

    return {
        "from": from_raw,
        "from_name": decode_mime_header(from_name),
        "from_addr": from_addr,
        "subject": subject,
    }

def send_test_mail(attachments, subjects:str, contents:str):
    attachments = attachments or []

    msg = EmailMessage()
    msg["Subject"] = subjects
    msg["From"] = SENDER_ID
    msg["To"] = MAIL_ID
    msg.set_content(contents)

    for p in attachments:
        path = Path(p)
        if not path.exists():
            raise FileNotFoundError(f"Attachment not found: {path}")

        ctype, encoding = mimetypes.guess_type(str(path))
        if ctype is None or encoding is not None:
            ctype = "application/octet-stream"
        maintype, subtype = ctype.split("/", 1)

        data = path.read_bytes()
        msg.add_attachment(
            data,
            maintype=maintype,
            subtype=subtype,
            filename=path.name
        )

    # 465면 SMTP_SSL, 587이면 SMTP+STARTTLS
    if int(SMTP_PORT) == 465:
        with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as smtp:
            smtp.login(MAIL_ID, MAIL_PW)
            smtp.send_message(msg)
    else:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.ehlo()
            smtp.login(MAIL_ID, MAIL_PW)
            smtp.send_message(msg)

    print("sent with attachments:", [str(a) for a in attachments])

def list_receive_main():
    imap = None
    try:
        imap = imaplib.IMAP4_SSL(IMAP_SERVER, IMAP_PORT)
        imap.login(MAIL_ID, MAIL_PW)

        boxes = list_mailboxes(imap)
        print("[MAILBOXES]")
        for b in boxes:
            print(" -", b)

        latest = fetch_latest_subject_from_inbox(imap)
        if latest is None:
            print("INBOX has no messages.")
        else:
            print("[LATEST MAIL]")
            print("From:", latest["from"])
            print("Subject:", latest["subject"])

    finally:
        if imap is not None:
            try:
                imap.logout()
            except Exception:
                pass


def get_ready_attach():        
    ROOT_DIR = Path(r".\logs\mail_ready")  

    # 1) 바로 아래 폴더의 .docx만
    docx_files = sorted(ROOT_DIR.glob("*.docx"))
    return docx_files

def make_body(option):
    config = configparser.ConfigParser()
    target_file, output_file_path = ""
    if option=="0":
        config_file = llm_config.get_last_gemini_settings_ini()
        
        if not os.path.exists(config_file):
            print(f"오류: 설정 파일({config_file})이 존재하지 않습니다.")
            return

        config.read(config_file, encoding='utf-8')
        section = 'GEMINI_SETTINGS'        
        target_file = config.get(section, 'file_path')
        output_file_path = config.get(section, 'output_file_path')
    return target_file, output_file_path


def main(action: str = "read", subjects:str="Monthly Analysis", contents:str="") :
    action = (action or "read").lower().strip()
    print(f"IMAP={IMAP_SERVER}:{IMAP_PORT}, SMTP={SMTP_SERVER}:{SMTP_PORT}, USER={MAIL_ID}, FROM={SENDER_ID}")
    if action == "read":
        list_receive_main()
        return 1
    if action =="send":
        attach_list = get_ready_attach()
        #send_test_mail(attachments, subjects:str, contents:str)
        if len(attach_list) > 0:
            send_test_mail(attach_list, subjects, contents)
            print("Reporting mail sent")
        else:
            print("Have not ready file in .\\rpa\\logs\\mail_ready")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Mail automation: read or send")
    parser.add_argument(
        "--action",
        choices=["read", "send"],
        default="read",
        help="read: list_receive_main() 실행, send: send_test_mail() 실행"
    )
    parser.add_argument(
        "--subject",
        default="Analysis Report",
        help="메일 제목 (action=send 일 때 사용)"
    )
    parser.add_argument(
        "--contents",
        default="LLM이 분석한 보고서입니다.\n",
        help="메일 본문 (action=send 일 때 사용)"
    )
    args = parser.parse_args()
    main(args.action, args.subject, args.contents)
