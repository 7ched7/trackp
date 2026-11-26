import os
import sys
import json
from logger import logger
from typing import Generator
from constants import APP_DIR, DEFAULT_IP_ADDRESS, DEFAULT_PORT, DEFAULT_LIMIT, MAX_PROCESS_LIMIT
from filelock import FileLock
from contextlib import contextmanager
from type import ConfigType

class ConfigManager:
    @staticmethod
    def _create_app_dir() -> None:
        os.makedirs(APP_DIR, exist_ok=True)

    @staticmethod
    def _get_config_path() -> str:
        ConfigManager._create_app_dir()
        return os.path.join(APP_DIR, "config.json")

    @staticmethod
    @contextmanager
    def _manage_lock(lock_file: str) -> Generator[None, None, None]:        
        lock = FileLock(lock_file)
        with lock:
            yield

    def create_config(self, ip: str=DEFAULT_IP_ADDRESS, port: int=DEFAULT_PORT, limit: int=DEFAULT_LIMIT) -> ConfigType:
        config_path = ConfigManager._get_config_path()
        
        try:
            with open(config_path, "w") as f:
                data = {
                    "ip": ip,
                    "port": port,
                    "limit": limit
                }
                json.dump(data, f, indent=4)

            return data
        except Exception as e:
            logger.error(e)
            sys.exit(1)

    def get_config(self) -> ConfigType:
        config_path = ConfigManager._get_config_path()
        lock_file = os.path.join(APP_DIR, "config.lock")

        with self._manage_lock(lock_file):
            data = {}
            try:
                with open(config_path, "r") as f:
                    data = json.load(f)
            except (json.JSONDecodeError, IOError):
                pass

            if not data:
                data = self.create_config()

            ip = data.get("ip")
            port = data.get("port")
            limit = max(1, min(data.get("limit"), MAX_PROCESS_LIMIT))

            return ip, port, limit