# app.py
import sys
from PySide6.QtWidgets import QApplication
from logging_setup import setup_logging
from store import Store
from executor import Executor
from scheduler_engine import Engine
from ui_main import MainWindow

def main():
    setup_logging()

    store = Store(db_path="rpa.db")
    store.init_db()

    executor = Executor()
    engine = Engine(store=store, executor=executor)
    engine.start()
    engine.reload_jobs()

    app = QApplication(sys.argv)
    win = MainWindow(store=store, engine=engine)
    win.show()

    code = app.exec()

    engine.stop()
    sys.exit(code)

if __name__ == "__main__":
    main()
