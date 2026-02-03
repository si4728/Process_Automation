
# ui_main.py
# 2026.1.22, 09:00
from PySide6.QtGui import QAction
from pathlib import Path
from PySide6.QtCore import Qt, QTimer, QTime, QObject, Signal, Slot
from collections import deque
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem,  # ✅ 여기 추가
    QTextEdit, QPlainTextEdit, QGroupBox, QFormLayout, QLineEdit,
    QCheckBox, QComboBox, QSpinBox, QTimeEdit, QFileDialog,
    QMessageBox, QSplitter, QDialog, QAbstractItemView
)
from PySide6.QtWidgets import QApplication

import logging
import sys


class _QtLogEmitter(QObject):
    text = Signal(str)


class QtLogHandler(logging.Handler):
    """Forward Python logging records to a Qt signal (thread-safe)."""

    def __init__(self, emitter: _QtLogEmitter):
        super().__init__()
        self._emitter = emitter

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
        except Exception:
            msg = record.getMessage()
        self._emitter.text.emit(msg)


class _ConsoleStream:
    """File-like object to redirect sys.stdout / sys.stderr into the UI console."""

    def __init__(self, emitter: _QtLogEmitter, prefix: str = ""):
        self._emitter = emitter
        self._prefix = prefix
        self._buf = ""

    def write(self, data):
        if data is None:
            return
        if isinstance(data, bytes):
            try:
                data = data.decode('utf-8', errors='replace')
            except Exception:
                data = str(data)
        else:
            data = str(data)
        self._buf += data
        while '\n' in self._buf:
            line, self._buf = self._buf.split('\n', 1)
            if line.strip() == "" and self._prefix == "":
                continue
            self._emitter.text.emit(f"{self._prefix}{line}")

    def flush(self):
        if self._buf:
            self._emitter.text.emit(f"{self._prefix}{self._buf}")
            self._buf = ""

    def isatty(self):
        return False


class MainWindow(QMainWindow):
    def __init__(self, store, engine):
        super().__init__()
        self.store = store
        self.engine = engine
        self.current_job_id = None

        self.setWindowTitle("Windows Process Automation by OnBranding Ver 1.0.1")
        self.resize(1200, 700)

        root = QWidget()
        self.setCentralWidget(root)

        # 메뉴바(File/Help)
        self._build_menu_bar()

        # ✅ (변경) 전체는 세로 레이아웃: 상단바 + 중앙 splitter
        root_layout = QVBoxLayout(root)

        # =========================
        # 2) 중앙: 좌 Jobs / 우 RecentRuns+Tail
        # =========================
        split_h = QSplitter(Qt.Horizontal)
        root_layout.addWidget(split_h, 1)

        # ---------- 좌측: Jobs ----------
        left_w = QWidget()
        left = QVBoxLayout(left_w)

        left.addWidget(QLabel("Jobs"))
        self.tbl_jobs = QTableWidget(0, 4)
        self.tbl_jobs.setHorizontalHeaderLabels(["ID", "Name", "Trigger", "Enabled"])
        self.tbl_jobs.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tbl_jobs.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tbl_jobs.cellClicked.connect(self.on_job_selected)
        left.addWidget(self.tbl_jobs)

        # (선택) 좌측 하단에는 Reload만 남겨도 깔끔
        left_btn_row = QHBoxLayout()
        self.btn_reload = QPushButton("Reload")
        left_btn_row.addWidget(self.btn_reload)
        left_btn_row.addStretch(1)
        left.addLayout(left_btn_row)
        self.btn_reload.clicked.connect(self.refresh_all)

        split_h.addWidget(left_w)

        # ---------- 우측: Recent Runs + Tail (세로 splitter) ----------
        right_w = QWidget()
        right = QVBoxLayout(right_w)

        split_v = QSplitter(Qt.Vertical)
        right.addWidget(split_v, 1)

        # Recent Runs 영역
        runs_wrap = QWidget()
        runs_layout = QVBoxLayout(runs_wrap)
        runs_layout.addWidget(QLabel("Recent Runs"))

        self.tbl_runs = QTableWidget(0, 9)
        self.tbl_runs.setHorizontalHeaderLabels(
            ["RunID", "Job", "Exe Path", "Args", "Started", "Ended", "Status", "Exit", "Message"]
        )
        self.tbl_runs.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tbl_runs.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tbl_runs.cellClicked.connect(self.on_run_selected)

        ##sort feature
        self.tbl_runs.setSortingEnabled(True)
        self.tbl_runs.horizontalHeader().sectionClicked.connect(self.on_runs_header_clicked)
        self.tbl_runs.sortItems(4, Qt.DescendingOrder)  # "Started"가 4번 컬럼일 때

        runs_layout.addWidget(self.tbl_runs)

        # Tail 영역
        tail_wrap = QWidget()
        tail_layout = QVBoxLayout(tail_wrap)
        tail_layout.addWidget(QLabel("Stdout/Stderr Tail"))

        self.txt_out = QTextEdit()
        self.txt_out.setReadOnly(True)
        tail_layout.addWidget(self.txt_out)

        split_v.addWidget(runs_wrap)
        split_v.addWidget(tail_wrap)
        split_v.setStretchFactor(0, 3)
        split_v.setStretchFactor(1, 2)

        split_h.addWidget(right_w)
        split_h.setStretchFactor(0, 2)
        split_h.setStretchFactor(1, 3)

        # =========================
        # 2.5) 하단: Console 로그 (python app.py 콘솔 출력 표시)
        # =========================
        console_grp = QGroupBox("Console")
        console_layout = QVBoxLayout(console_grp)

        # --- Console control bar (Level / Search / Clear / Auto-scroll) ---
        console_bar = QHBoxLayout()
        console_bar.addWidget(QLabel("Level"))
        self.cb_log_level = QComboBox()
        self.cb_log_level.addItems(["ALL", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"])
        self.cb_log_level.setCurrentText("ALL")
        console_bar.addWidget(self.cb_log_level)

        console_bar.addSpacing(12)
        console_bar.addWidget(QLabel("Search"))
        self.ed_log_search = QLineEdit()
        self.ed_log_search.setPlaceholderText("type keyword and press Enter")
        console_bar.addWidget(self.ed_log_search, 1)
        self.btn_log_find = QPushButton("Find Next")
        console_bar.addWidget(self.btn_log_find)

        console_bar.addSpacing(12)
        self.chk_log_autoscroll = QCheckBox("Auto-scroll")
        self.chk_log_autoscroll.setChecked(True)
        console_bar.addWidget(self.chk_log_autoscroll)

        self.btn_log_clear = QPushButton("Clear")
        console_bar.addWidget(self.btn_log_clear)

        console_layout.addLayout(console_bar)

        self.txt_console = QPlainTextEdit()
        self.txt_console.setReadOnly(True)
        # 너무 커지지 않게 로그 라인 제한(표시)
        self.txt_console.setMaximumBlockCount(5000)
        console_layout.addWidget(self.txt_console)

        # 내부 버퍼(필터 변경 시 재구성)
        self._console_buf = deque(maxlen=20000)
        console_grp.setMinimumHeight(140)
        console_grp.setMaximumHeight(220)
        root_layout.addWidget(console_grp)

        # Console controls wiring
        self.cb_log_level.currentTextChanged.connect(self._rebuild_console)
        self.btn_log_clear.clicked.connect(self._clear_console)
        self.btn_log_find.clicked.connect(self._find_next_console)
        self.ed_log_search.returnPressed.connect(self._find_next_console)

        # =========================
        # 3) Job Editor: 메인 우측에서 제거 -> 다이얼로그로 이동
        # =========================
        self.grp = QGroupBox("Job Editor")
        form = QFormLayout(self.grp)

        self.ed_name = QLineEdit()
        self.chk_enabled = QCheckBox("Enabled")
        self.chk_enabled.setChecked(True)

        # exe + browse
        exe_row = QHBoxLayout()
        self.ed_exe = QLineEdit()
        self.btn_browse_exe = QPushButton("Browse...")
        exe_row.addWidget(self.ed_exe, 1)
        exe_row.addWidget(self.btn_browse_exe)
        self.btn_browse_exe.clicked.connect(self.browse_exe)
        exe_wrap = QWidget()
        exe_wrap.setLayout(exe_row)

        self.ed_args = QLineEdit()

        # workdir + browse
        wd_row = QHBoxLayout()
        self.ed_workdir = QLineEdit()
        self.btn_browse_wd = QPushButton("Browse...")
        wd_row.addWidget(self.ed_workdir, 1)
        wd_row.addWidget(self.btn_browse_wd)
        self.btn_browse_wd.clicked.connect(self.browse_workdir)
        wd_wrap = QWidget()
        wd_wrap.setLayout(wd_row)

        self.cb_trigger = QComboBox()
        self.cb_trigger.addItems(["interval", "daily", "weekly", "monthly", "cron"])
        self.cb_trigger.currentTextChanged.connect(self.on_trigger_changed)

        self.sp_interval = QSpinBox()
        self.sp_interval.setRange(1, 24 * 3600)
        self.sp_interval.setValue(60)

        self.tm_daily = QTimeEdit()
        self.tm_daily.setDisplayFormat("HH:mm")
        self.tm_daily.setTime(QTime(9, 0))

        self.cb_cond = QComboBox()
        self.cb_cond.addItems(["none", "file_exists", "process_not_running"])
        self.cb_cond.currentTextChanged.connect(self.on_cond_changed)

        self.ed_cond_val = QLineEdit()

        self.sp_timeout = QSpinBox()
        self.sp_timeout.setRange(1, 24 * 3600)
        self.sp_timeout.setValue(60)

        # ===== Trigger 확장 입력 위젯 =====
        self.ed_dow = QLineEdit()   # weekly: mon,wed,fri 또는 mon-fri
        self.sp_dom = QSpinBox()    # monthly: 1~31
        self.sp_dom.setRange(1, 31)
        self.sp_dom.setValue(1)
        self.ed_cron = QLineEdit()  # cron: "분 시 일 월 요일"
        # ==============================

        self.sp_retry = QSpinBox()
        self.sp_retry.setRange(0, 20)
        self.sp_retry.setValue(0)

        self.sp_retry_delay = QSpinBox()
        self.sp_retry_delay.setRange(1, 3600)
        self.sp_retry_delay.setValue(5)

        self.chk_overlap = QCheckBox("Prevent Overlap")
        self.chk_overlap.setChecked(True)

        form.addRow("Name", self.ed_name)
        form.addRow("", self.chk_enabled)
        form.addRow("Exe Path", exe_wrap)
        form.addRow("Args", self.ed_args)
        form.addRow("Working Dir", wd_wrap)
        form.addRow("Trigger Type", self.cb_trigger)
        form.addRow("Interval (sec)", self.sp_interval)
        form.addRow("Daily Time", self.tm_daily)

        # (원하면 아래 3줄도 trigger 타입별로 show/hide 되도록 on_trigger_changed에서 처리)
        form.addRow("Weekly DOW", self.ed_dow)
        form.addRow("Monthly DOM", self.sp_dom)
        form.addRow("Cron Expr", self.ed_cron)

        form.addRow("Condition", self.cb_cond)
        form.addRow("Cond Value", self.ed_cond_val)
        form.addRow("Timeout (sec)", self.sp_timeout)
        form.addRow("Retry Count", self.sp_retry)
        form.addRow("Retry Delay (sec)", self.sp_retry_delay)
        form.addRow("", self.chk_overlap)

        # (기존 버튼들) -> Job Editor 다이얼로그 내부로 이동
        editor_btn_row = QHBoxLayout()
        self.btn_new = QPushButton("New")
        self.btn_save = QPushButton("Save")
        self.btn_delete = QPushButton("Delete")
        self.btn_run = QPushButton("Run Now")
        editor_btn_row.addWidget(self.btn_new)
        editor_btn_row.addWidget(self.btn_save)
        editor_btn_row.addWidget(self.btn_delete)
        editor_btn_row.addWidget(self.btn_run)
        editor_btn_row.addStretch(1)

        editor_btn_wrap = QWidget()
        editor_btn_wrap.setLayout(editor_btn_row)
        form.addRow("", editor_btn_wrap)

        self.btn_new.clicked.connect(self.on_new)
        self.btn_save.clicked.connect(self.on_save)
        self.btn_delete.clicked.connect(self.on_delete)
        self.btn_run.clicked.connect(self.on_run_now)

        # Job Editor 다이얼로그 생성
        self.job_editor_dlg = QDialog(self)
        self.job_editor_dlg.setWindowTitle("Job Editor")
        dlg_layout = QVBoxLayout(self.job_editor_dlg)
        dlg_layout.addWidget(self.grp)
        self.job_editor_dlg.resize(720, 640)

        # =========================
        # 4) 주기적 refresh (Runs)
        # =========================
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh_runs)
        self.timer.start(2000)

        self.on_trigger_changed(self.cb_trigger.currentText())
        self.on_cond_changed(self.cb_cond.currentText())
        self.refresh_all()

        # 콘솔 로그(UI 하단)로 로깅/출력 리다이렉트
        self._install_console_logging()


    def closeEvent(self, event):
        try:
            self._uninstall_console_logging()
        except Exception:
            pass
        QApplication.instance().quit()
        event.accept()


    # =========================
    # Menu Bar
    # =========================
    def _build_menu_bar(self):
        menubar = self.menuBar()

        # File
        menu_file = menubar.addMenu("File")

        act_browse = QAction("Browse...", self)
        act_browse.triggered.connect(self.on_file_browse)
        menu_file.addAction(act_browse)

        act_load = QAction("Load Config...", self)
        act_load.triggered.connect(self.on_cload_clicked)
        menu_file.addAction(act_load)

        menu_file.addSeparator()
        act_exit = QAction("Exit", self)
        act_exit.triggered.connect(lambda: QApplication.instance().quit())
        menu_file.addAction(act_exit)

        # Edit (job actions)
        menu_edit = menubar.addMenu("Edit")

        act_new = QAction("New Job", self)
        act_new.triggered.connect(self.on_new)
        menu_edit.addAction(act_new)

        act_save = QAction("Save Job", self)
        act_save.triggered.connect(self.on_save)
        menu_edit.addAction(act_save)

        act_delete = QAction("Delete Job", self)
        act_delete.triggered.connect(self.on_delete)
        menu_edit.addAction(act_delete)

        menu_edit.addSeparator()
        act_run = QAction("Run Now", self)
        act_run.triggered.connect(self.on_run_now)
        menu_edit.addAction(act_run)

        # Job Edit (open editor dialog)
        menu_jobedit = menubar.addMenu("Job Edit")
        act_open_editor = QAction("Open Job Editor", self)
        act_open_editor.triggered.connect(self.open_job_editor)
        menu_jobedit.addAction(act_open_editor)

        # Help
        menu_help = menubar.addMenu("Help")
        act_help = QAction("View Help (rpa_help.txt)", self)
        act_help.triggered.connect(self.on_view_help)
        menu_help.addAction(act_help)

        # About (top-level)
        menu_about = menubar.addMenu("About")
        act_about = QAction("About", self)
        act_about.triggered.connect(self.on_about_clicked)
        menu_about.addAction(act_about)

    def on_file_browse(self):
        start_dir = str(Path.cwd())
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Browse File",
            start_dir,
            "All Files (*.*)"
        )
        if not path:
            return
        QMessageBox.information(self, "Selected", f"Selected:\n{path}")

    def on_view_help(self):
        help_path = Path.cwd() / "rpa_help.txt"
        if not help_path.exists():
            QMessageBox.warning(self, "Help", f"File not found:\n{help_path}")
            return
        try:
            text = help_path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            QMessageBox.critical(self, "Help", f"Read failed:\n{e}")
            return

        dlg = QDialog(self)
        dlg.setWindowTitle("RPA Help")
        dlg.resize(900, 600)
        layout = QVBoxLayout(dlg)
        viewer = QTextEdit()
        viewer.setReadOnly(True)
        viewer.setPlainText(text)
        layout.addWidget(viewer)
        dlg.exec()


    def open_job_editor(self):
        self.job_editor_dlg.show()
        self.job_editor_dlg.raise_()
        self.job_editor_dlg.activateWindow()

    def on_close_clicked(self):
        QApplication.instance().quit()

    def on_cload_clicked(self):
        path, _ = QFileDialog.getOpenFileName(self, "Load Config", "", "Config Files (*.json *.yaml *.yml *.ini);;All Files (*)")
        if not path:
            return
        # 프로젝트에 load_config가 있으면 연결
        if hasattr(self.engine, "load_config"):
            try:
                self.engine.load_config(path)
            except Exception as e:
                QMessageBox.critical(self, "Cload Failed", str(e))
                return
        # 로드 후 jobs 갱신
        self.refresh_all()


    def on_about_clicked(self):
        QMessageBox.information(self, "About", "Robot Process Automation made by Onbrand 2026)")

    def browse_exe(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select executable/bat", "", "All Files (*.*)")
        if path:
            self.ed_exe.setText(path)

    def browse_workdir(self):
        path = QFileDialog.getExistingDirectory(self, "Select working directory")
        if path:
            self.ed_workdir.setText(path)

    def on_trigger_changed(self, t: str):
        self.sp_interval.setEnabled(t == "interval")
        self.tm_daily.setEnabled(t in ["daily", "weekly", "monthly"])  # time은 cron 외 대부분 사용

        self.ed_dow.setEnabled(t == "weekly")
        self.sp_dom.setEnabled(t == "monthly")
        self.ed_cron.setEnabled(t == "cron")

    def on_cond_changed(self, c: str):
        self.ed_cond_val.setEnabled(c != "none")

    def refresh_all(self):
        self.engine.reload_jobs()
        self.refresh_jobs()
        self.refresh_runs()

    def refresh_jobs(self):
        jobs = self.store.list_jobs(enabled_only=False)
        self.tbl_jobs.setRowCount(0)
        for j in jobs:
            r = self.tbl_jobs.rowCount()
            self.tbl_jobs.insertRow(r)
            self.tbl_jobs.setItem(r, 0, QTableWidgetItem(str(j["id"])))
            self.tbl_jobs.setItem(r, 1, QTableWidgetItem(j["name"]))
            trig = j["trigger_type"] or ""
            if trig == "interval":
                trig = f'interval({j.get("interval_sec")}s)'
            elif trig == "daily":
                trig = f'daily({j.get("daily_time")})'
            elif trig == "weekly":
                trig = f'weekly({j.get("day_of_week")},{j.get("daily_time")})'
            elif trig == "monthly":
                trig = f'monthly({j.get("day_of_month")},{j.get("daily_time")})'
            elif trig == "cron":
                trig = f'cron({j.get("cron_expr")})'
            else:
                trig = trig
            self.tbl_jobs.setItem(r, 2, QTableWidgetItem(trig))
            self.tbl_jobs.setItem(r, 3, QTableWidgetItem("Y" if j["enabled"] else "N"))

        self.tbl_jobs.resizeColumnsToContents()


    def refresh_runs(self):
        # ✅ 현재 정렬 상태 저장 (헤더 클릭 정렬 유지)
        header = self.tbl_runs.horizontalHeader()
        sort_col = header.sortIndicatorSection()
        sort_order = header.sortIndicatorOrder()

        # ✅ 채우는 중 정렬 꺼서 row가 튀는 현상 방지
        was_sorting = self.tbl_runs.isSortingEnabled()
        self.tbl_runs.setSortingEnabled(False)

        runs = self.store.list_runs(limit=200)

        self.tbl_runs.setRowCount(0)
        for rr in runs:
            r = self.tbl_runs.rowCount()
            self.tbl_runs.insertRow(r)

            # RunID: 숫자 정렬되도록 Qt.EditRole에 int 저장
            run_item = QTableWidgetItem()
            try:
                rid = int(rr.get("id"))
            except Exception:
                rid = rr.get("id")
            run_item.setData(Qt.EditRole, rid)
            run_item.setData(Qt.DisplayRole, "" if rid is None else str(rid))
            self.tbl_runs.setItem(r, 0, run_item)
            self.tbl_runs.setItem(r, 1, QTableWidgetItem(rr.get("job_name") or ""))
            self.tbl_runs.setItem(r, 2, QTableWidgetItem(rr.get("exe_path") or ""))
            self.tbl_runs.setItem(r, 3, QTableWidgetItem(rr.get("args") or ""))

            # Started/Ended: "YYYY-MM-DD HH:MM:SS" 형태면 문자열 정렬도 정상 동작
            self.tbl_runs.setItem(r, 4, QTableWidgetItem(rr.get("started_at") or ""))
            self.tbl_runs.setItem(r, 5, QTableWidgetItem(rr.get("ended_at") or ""))
            self.tbl_runs.setItem(r, 6, QTableWidgetItem(rr.get("status") or ""))

            # Exit: ✅ 숫자 정렬이 되도록 EditRole에 int로 저장
            exit_item = QTableWidgetItem()
            if rr.get("exit_code") is None:
                exit_item.setData(Qt.EditRole, "")  # 빈 값은 뒤로
            else:
                try:
                    exit_item.setData(Qt.EditRole, int(rr["exit_code"]))
                except Exception:
                    exit_item.setData(Qt.EditRole, str(rr["exit_code"]))
            self.tbl_runs.setItem(r, 7, exit_item)

            self.tbl_runs.setItem(r, 8, QTableWidgetItem(rr.get("message") or ""))

        self.tbl_runs.resizeColumnsToContents()

        # ✅ 정렬 다시 켜고, 기존 정렬 상태 복원
        self.tbl_runs.setSortingEnabled(was_sorting if was_sorting else True)
        if sort_col >= 0:
            self.tbl_runs.sortItems(sort_col, sort_order)


    def on_runs_header_clicked(self, logical_index: int):
        # 헤더 클릭 정렬은 Qt가 자동 처리
        return


    def on_job_selected(self, row: int, col: int):
        job_id = int(self.tbl_jobs.item(row, 0).text())
        job = self.store.get_job(job_id)
        if not job:
            return
        self.current_job_id = job_id

        self.ed_name.setText(job["name"])
        self.chk_enabled.setChecked(bool(job["enabled"]))
        self.ed_exe.setText(job["exe_path"])
        self.ed_args.setText(job.get("args") or "")
        self.ed_workdir.setText(job.get("workdir") or "")

        self.cb_trigger.setCurrentText(job["trigger_type"] or "interval")
        self.sp_interval.setValue(int(job.get("interval_sec") or 60))

        t = job.get("daily_time") or "09:00"
        hh, mm = t.split(":")
        self.tm_daily.setTime(QTime(int(hh), int(mm)))

        ctype = job.get("cond_type") or "none"
        self.cb_cond.setCurrentText(ctype if ctype in ["file_exists", "process_not_running"] else "none")
        self.ed_cond_val.setText(job.get("cond_value") or "")

        self.sp_timeout.setValue(int(job.get("timeout_sec") or 60))
        self.sp_retry.setValue(int(job.get("retry_count") or 0))
        self.sp_retry_delay.setValue(int(job.get("retry_delay_sec") or 5))
        self.chk_overlap.setChecked(bool(job.get("prevent_overlap") or 1))

    def on_new(self):
        self.current_job_id = None
        self.ed_name.setText("")
        self.chk_enabled.setChecked(True)
        self.ed_exe.setText("")
        self.ed_args.setText("")
        self.ed_workdir.setText("")
        self.cb_trigger.setCurrentText("interval")
        self.sp_interval.setValue(60)
        self.tm_daily.setTime(QTime(9, 0))
        self.cb_cond.setCurrentText("none")
        self.ed_cond_val.setText("")
        self.sp_timeout.setValue(60)
        self.sp_retry.setValue(0)
        self.sp_retry_delay.setValue(5)
        self.chk_overlap.setChecked(True)

    def on_save(self):
        name = self.ed_name.text().strip()
        exe = self.ed_exe.text().strip()
        if not name:
            QMessageBox.warning(self, "Validation", "Name is required.")
            return
        if not exe:
            QMessageBox.warning(self, "Validation", "Exe Path is required.")
            return

        trigger_type = self.cb_trigger.currentText()
        interval_sec = int(self.sp_interval.value()) if trigger_type == "interval" else None
        daily_time = self.tm_daily.time().toString("HH:mm") if trigger_type in ["daily", "weekly", "monthly"] else None
        day_of_week = self.ed_dow.text().strip() if trigger_type == "weekly" else None
        day_of_month = int(self.sp_dom.value()) if trigger_type == "monthly" else None
        cron_expr = self.ed_cron.text().strip() if trigger_type == "cron" else None

        cond_type = self.cb_cond.currentText()
        if cond_type == "none":
            cond_type = None
            cond_value = None
        else:
            cond_value = self.ed_cond_val.text().strip()
            if not cond_value:
                QMessageBox.warning(self, "Validation", "Cond Value is required for selected condition.")
                return

        job = {
            "id": self.current_job_id,
            "name": name,
            "enabled": 1 if self.chk_enabled.isChecked() else 0,
            "exe_path": exe,
            "args": self.ed_args.text(),
            "workdir": self.ed_workdir.text(),
            "trigger_type": trigger_type,
            "interval_sec": interval_sec,
            "daily_time": daily_time,
            "cond_type": cond_type,
            "cond_value": cond_value,
            "timeout_sec": int(self.sp_timeout.value()),
            "retry_count": int(self.sp_retry.value()),
            "retry_delay_sec": int(self.sp_retry_delay.value()),
            "prevent_overlap": 1 if self.chk_overlap.isChecked() else 0,
            "day_of_week": day_of_week,
            "day_of_month": day_of_month,
            "cron_expr": cron_expr,
        }

        job_id = self.store.upsert_job(job)
        self.current_job_id = job_id
        self.refresh_all()


    def on_delete(self):
        if not self.current_job_id:
            QMessageBox.information(self, "Info", "Select a job first.")
            return
        self.store.delete_job(self.current_job_id)
        self.current_job_id = None
        self.refresh_all()

        self.on_new()

    def on_run_now(self):
        if not self.current_job_id:
            QMessageBox.information(self, "Info", "Select a job first.")
            return
        self.engine.run_now(self.current_job_id)

    def on_run_selected(self, row: int, col: int):
        # 선택된 run의 stdout/stderr 보여주기 위해 runs 다시 읽고 해당 id 매칭
        run_id = int(self.tbl_runs.item(row, 0).text())
        runs = self.store.list_runs(limit=200)
        target = next((x for x in runs if int(x["id"]) == run_id), None)
        if not target:
            self.txt_out.setPlainText("")
            return

        out = (target.get("stdout_full") or target.get("stdout_tail") or "")
        err = (target.get("stderr_full") or target.get("stderr_tail") or "")
        msg = f"[STDOUT]\n{out}\n\n[STDERR]\n{err}"
        self.txt_out.setPlainText(msg)


    @Slot(str)
    def _append_console(self, line: str):
        # store all lines to buffer (for filtering / searching)
        if not hasattr(self, '_console_buf') or self._console_buf is None:
            # buffer might not be ready during early init
            return
        self._console_buf.append(line)

        # apply current level filter
        if not hasattr(self, 'txt_console') or self.txt_console is None:
            return
        if self._passes_log_filter(line):
            self.txt_console.appendPlainText(line)
            if getattr(self, 'chk_log_autoscroll', None) is not None and self.chk_log_autoscroll.isChecked():
                sb = self.txt_console.verticalScrollBar()
                sb.setValue(sb.maximum())

    
    def _passes_log_filter(self, line: str) -> bool:
        # Expect formatted log lines like: "YYYY-MM-DD ... | INFO | logger | message"
        level_text = None
        if " | " in line:
            parts = line.split(" | ")
            if len(parts) >= 3:
                level_text = parts[1].strip()
        if level_text is None:
            # stdout/stderr redirected lines: show always unless filter is ERROR+ and line looks like INFO etc.
            return self.cb_log_level.currentText() in ["ALL", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

        wanted = self.cb_log_level.currentText()
        if wanted == "ALL":
            return True

        order = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "WARN": 30, "ERROR": 40, "CRITICAL": 50}
        cur = order.get(level_text, 0)
        minv = order.get(wanted, 0)
        return cur >= minv

    def _rebuild_console(self):
        if not hasattr(self, 'txt_console') or self.txt_console is None:
            return
        self.txt_console.clear()
        for line in getattr(self, '_console_buf', []):
            if self._passes_log_filter(line):
                self.txt_console.appendPlainText(line)
        if getattr(self, 'chk_log_autoscroll', None) is not None and self.chk_log_autoscroll.isChecked():
            sb = self.txt_console.verticalScrollBar()
            sb.setValue(sb.maximum())

    def _clear_console(self):
        if hasattr(self, '_console_buf') and self._console_buf is not None:
            self._console_buf.clear()
        if hasattr(self, 'txt_console') and self.txt_console is not None:
            self.txt_console.clear()

    def _find_next_console(self):
        if not hasattr(self, 'txt_console') or self.txt_console is None:
            return
        term = self.ed_log_search.text().strip() if hasattr(self, 'ed_log_search') else ""
        if not term:
            return
        found = self.txt_console.find(term)
        if not found:
            # wrap-around
            cursor = self.txt_console.textCursor()
            cursor.movePosition(cursor.Start)
            self.txt_console.setTextCursor(cursor)
            self.txt_console.find(term)

    def _install_console_logging(self):
        # 1) logging -> UI
        self._log_emitter = _QtLogEmitter()
        self._log_emitter.text.connect(self._append_console)

        handler = QtLogHandler(self._log_emitter)
        handler.setLevel(logging.DEBUG)

        # 기존 로거 핸들러 포맷이 있으면 그대로 사용
        root_logger = logging.getLogger()
        fmt = None
        for h in root_logger.handlers:
            if h.formatter is not None:
                fmt = h.formatter
                break
        if fmt is None:
            fmt = logging.Formatter('%(asctime)s | %(levelname)s | %(name)s | %(message)s')
        handler.setFormatter(fmt)
        root_logger.addHandler(handler)

        # 2) print()/traceback 등 stdout/stderr -> UI (옵션)
        self._orig_stdout = sys.stdout
        self._orig_stderr = sys.stderr
        sys.stdout = _ConsoleStream(self._log_emitter, prefix='')
        sys.stderr = _ConsoleStream(self._log_emitter, prefix='[STDERR] ')

    def _uninstall_console_logging(self):
        # stdout/stderr 복구
        if hasattr(self, '_orig_stdout') and self._orig_stdout is not None:
            sys.stdout = self._orig_stdout
        if hasattr(self, '_orig_stderr') and self._orig_stderr is not None:
            sys.stderr = self._orig_stderr