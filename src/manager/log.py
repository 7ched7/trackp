import json
import os
from datetime import datetime, timedelta
from filelock import FileLock
from contextlib import contextmanager
from typing import Generator
from constants import APP_DIR

class LogManager:
    def __init__(self):
        self.logs_dir = os.path.join(APP_DIR, "logs")
        self.lock_file = os.path.join(self.logs_dir, "logs.lock")

        if not os.path.exists(self.logs_dir):
            os.makedirs(self.logs_dir)           
    
    @contextmanager
    def _manage_lock(self) -> Generator[None, None, None]:
        lock = FileLock(self.lock_file)
        with lock:
            yield

    def _write_logs(self, path: str, data: dict) -> None:
        with open(path, "w") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def get_logs(self, path: str) -> dict:
        data = {}
        try:
            with open(path, "r") as f:
                data = json.load(f)
        except:
            pass
        return data

    def save_start_time(self, process_name: str, start_time: datetime) -> None:
        log_file = os.path.join(self.logs_dir, start_time.strftime("%Y%m%d"))

        inf = { 
            "start_time": start_time.isoformat(),
            "end_time": start_time.isoformat()
        }

        with self._manage_lock():
            data = self.get_logs(log_file)

            if process_name in data:
                data[process_name].append(inf)
            else:
                data[process_name] = [inf]

            self._write_logs(log_file, data)

    def save_end_time(self, process_name: str, start_time: datetime) -> None:
        now = datetime.now()
        log_file = os.path.join(self.logs_dir, now.strftime("%Y%m%d"))

        with self._manage_lock():
            if start_time.date() != now.date():
                elapsed_day = (now - start_time).days

                # if the process spans multiple days, update the corresponding log file for each day
                for day in range(elapsed_day + 1):
                    t = now - timedelta(days=day)
                    daily_log_file = os.path.join(self.logs_dir, t.strftime("%Y%m%d"))

                    daily_data = self.get_logs(daily_log_file)

                    if t.date() == now.date():
                        inf = {
                            "start_time": now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat(),
                            "end_time": now.isoformat()
                        }
                        daily_data[process_name] = [inf]
                    elif t.date() == start_time.date():
                        daily_data[process_name][-1]["end_time"] = t.replace(hour=23, minute=59, second=59, microsecond=999999).isoformat()
                    else:
                        inf = {
                            "start_time": t.replace(hour=0, minute=0, second=0, microsecond=0).isoformat(),
                            "end_time": t.replace(hour=23, minute=59, second=59, microsecond=999999).isoformat()
                        }
                        daily_data[process_name] = [inf]

                    self._write_logs(daily_log_file, daily_data)
            else:
                data = self.get_logs(log_file)

                if process_name in data:
                    data[process_name][-1]["end_time"] = now.isoformat()

                self._write_logs(log_file, data)