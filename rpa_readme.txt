# Windows RPA & Flow Automation Platform  
(OnBranding RPA v1.0.1)

본 프로젝트는 **Windows 환경에서 외부 프로그램 / Python 스크립트 / Flow(YAML) 기반 작업을
GUI 및 스케줄러로 자동 실행**하기 위한 RPA(Robotic Process Automation) 플랫폼입니다.

- PySide6 기반 GUI
- APScheduler 기반 주기/조건 실행
- SQLite 기반 Job / Run 이력 관리
- Flow(YAML) 기반 배치 실행
- LLM(Gemini/OpenAI) 연동 + 이메일 발송 지원

---

## 1. 전체 아키텍처

┌─────────────┐
│ UI (GUI) │ ← PySide6
└─────┬───────┘
│
┌─────▼──────────┐
│ SchedulerEngine │ ← APScheduler
└─────┬──────────┘
│
┌─────▼──────────┐
│ Executor │ ← subprocess
└─────┬──────────┘
│
┌─────▼──────────┐
│ External App │ (.exe / .bat / .py)
└────────────────┘

   + SQLite(Store)
   + Flow Runner (YAML)
   + Mail / LLM

## 2. 주요 구성 파일

| 파일 | 역할 |
|----|----|
| `app.py` | GUI 진입점, 전체 시스템 초기화 | :contentReference[oaicite:0]{index=0} |
| `ui_main.py` | PySide6 기반 메인 UI | :contentReference[oaicite:1]{index=1} |
| `scheduler_engine.py` | Job 스케줄링 / 조건 실행 | :contentReference[oaicite:2]{index=2} |
| `executor.py` | 외부 프로세스 실행 모듈 | :contentReference[oaicite:3]{index=3} |
| `store.py` | SQLite DB (jobs, runs) | :contentReference[oaicite:4]{index=4} |
| `models.py` | Job 데이터 모델 | :contentReference[oaicite:5]{index=5} |
| `flow_runner.py` | YAML 기반 Flow 실행기 | :contentReference[oaicite:6]{index=6} |
| `llm_config.py` | Gemini 설정 ini 생성/관리 | :contentReference[oaicite:7]{index=7} |
| `mail_main.py` | 메일 수신/발송 자동화 | :contentReference[oaicite:8]{index=8} |
| `logging_setup.py` | 로깅 설정 | :contentReference[oaicite:9]{index=9} |

---

## 3. 권장 폴더 구조 (배포용)
C:\access\rpa
├─ app.py
├─ ui_main.py
├─ executor.py
├─ scheduler_engine.py
├─ store.py
├─ models.py
├─ flow_runner.py
├─ llm_config.py
├─ logging_setup.py
├─ rpa.db # 자동 생성
├─ flows
│ ├─ flow_A1.yaml
│ └─ logs
├─ llm
│ └─ gemini_settings_00001.ini
├─ logs
│ └─ app.log
├─ email
│ ├─ mail_main.py
│ ├─ config.yaml
│ └─ secret.local
└─ requirements.txt

# 4. 실행 환경

- OS: Windows 10 / 11
- Python: **3.11 이상 권장**
- 필수 패키지:
  - PySide6
  - APScheduler
  - psutil
  - PyYAML
  - imap-tools

### requirements.txt 예시

```txt
PySide6
apscheduler
psutil
pyyaml
imap-tools

5. 설치 방법 (운영 PC)
cd C:\access\rpa
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt

6. 실행 방법
6.1 GUI 실행 (권장)
cd C:\access\rpa
.\.venv\Scripts\activate
python app.py


Job 관리

즉시 실행(Run Now)

스케줄 실행

Run 로그 및 STDOUT/STDERR 확인 가능

6.2 Flow(YAML) 단독 실행
python flow_runner.py flows\flow_A1.yaml

서버/배치 환경에서 GUI 없이 사용 가능
step 성공/실패에 따른 분기(on: success/fail/always) 지원

7. Job 스케줄링 지원 유형
유형	설명
interval	N초 주기
daily	매일 HH:MM
weekly	요일 + 시간
monthly	매월 n일
cron	cron 표현식

조건 실행:
file_exists
process_not_running
중복 실행 방지(prevent_overlap)

8. 데이터베이스
SQLite (rpa.db)
자동 마이그레이션 지원
테이블:
jobs: 작업 정의
runs: 실행 이력 / 로그

9. 로그 정책
앱 로그: logs/app.log (로테이션)
Flow 로그: flows/logs/*.log
각 step stdout/stderr 저장

10. 메일 & LLM 연동
메일 설정
email/config.yaml : 서버 정보
email/secret.local : 계정 정보 (배포 시 별도 관리)
LLM
llm_config.py로 ini 자동 생성
Gemini 기반 문서 요약 → 결과 docx → 메일 첨부

11. EXE 배포 (선택)
pip install pyinstaller
pyinstaller --onefile --noconsole app.py
생성물: dist/app.exe
flows, email, llm 폴더는 동반 배포 필수

12. 운영 체크리스트
 Python 실행 확인
 app.py GUI 정상 실행
 Job 저장 / Run Now 성공
 로그 UI 출력 확인
 Flow YAML 실행 테스트
 메일 발송 테스트

13. 버전 정보
OnBranding RPA v1.0.1
2026.01
=========-=======================-========
16. Flow Runner v3 (YAML 기반 배치 실행기)
flow_runner_v3.py는 GUI 없이 서버/배치 환경에서 실행 가능한
고급 Flow 실행 엔진입니다. 

16.1 Flow Runner 주요 기능
YAML 기반 step 정의
step 간 조건 분기(on / success / fail / always)
토큰 치환 {python}, {flow_dir}, {log_dir}, {stamp}
step별 개별 로그 파일 생성
Windows 콘솔 Unicode 안전 처리
loop / 잘못된 참조 자동 검증

16.2 Flow YAML 기본 구조
name: FlowA
globals:
  workdir: C:\access\rpa
  timeout_sec: 600
  log_dir: ./logs
  python: C:\Python311\python.exe

steps:
  - id: a1
    name: Excel → TXT
    cmd:
      - "{python}"
      - convert_excel2llm2.py
      - input.xlsx
    success: a2
    fail: end

  - id: a2
    name: LLM 분석
    cmd:
      - "{python}"
      - chat_with_gemini.py
    always: end

  - id: end
    name: 종료
    cmd:
      - echo
      - "FLOW END"

16.3 Step 분기(on) 규칙

Flow Runner는 아래 모든 형태를 지원합니다.
on: a2                      # 무조건 다음 step
on:
  success: a2
  fail: a3
  always: a4

또는 최상위 단축 표현도 가능:

success: a2
fail: a3
always: a4
next: a2   # success와 동일

📌 normalize_on() 로직에 의해 모두 동일하게 처리됩니다.

16.4 실행 로그 구조
실행 시 다음 파일들이 생성됩니다.
flows/logs/
 ├─ FlowA_20260202_101530.log          ← 메인 로그
 ├─ FlowA_20260202_101530_a1.out.txt   ← step a1 stdout+stderr
 ├─ FlowA_20260202_101530_a2.out.txt


메인 로그에는:
실행 시작/종료
step 전환
step 출력 tail(12KB) 이 자동 포함됩니다.

16.5 실행 방법
기본 실행
python flow_runner_v3.py flows\flow_A1.yaml
Dry-run (검증만)
python flow_runner_v3.py flows\flow_A1.yaml --dry-run

특정 step부터 실행
python flow_runner_v3.py flows\flow_A1.yaml --start a2

16.6 Flow 검증 기능
실행 전 자동 검증 항목:
step id 중복
step id 누락
cmd 누락
존재하지 않는 step 참조
step loop 감지
문제 발생 시 실행 중단 + 명확한 로그 출력

17. Executor vs Flow Runner 역할 분리 (중요)
구분	Executor	Flow Runner
목적	단일 Job 실행	복수 Step 배치
사용 위치	GUI / Scheduler	CLI / 서버
DB 기록	✔	✖
YAML	✖	✔
분기 처리	✖	✔
메일/LLM 연계	간접	직접

📌 권장 운영 방식

정기/상시 작업 → GUI + Scheduler + Executor
배치/보고서 파이프라인 → Flow Runner
두 방식은 상호 독립 + 병행 사용 가능

18. 운영 시 주의 사항 (중요)
Flow Runner는 DB를 사용하지 않음
cmd는 반드시 list 형태
.bat/.cmd는 자동으로 cmd /c 처리됨
한 Flow 내 step loop 발생 시 즉시 중단
Windows 콘솔 인코딩 문제로 실행이 죽지 않도록 보호됨

19. 권장 배포 형태
rpa/
 ├─ app.exe                 ← GUI (선택)
 ├─ flow_runner_v3.exe      ← 배치 전용
 ├─ flows/
 ├─ llm/
 ├─ email/
 └─ logs/

