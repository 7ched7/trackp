import logging
from constants import APP_NAME, RED, YELLOW, GREY, RED_LIGHT, BOLD, RESET

class AnsiColorFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord):
        start_style = {
            "DEBUG": GREY,
            "INFO": RESET,
            "WARNING": YELLOW,
            "ERROR": RED,
            "CRITICAL": RED_LIGHT + BOLD,
        }.get(record.levelname, RESET)
        end_style = RESET
        return f"{start_style}{super().format(record)}{end_style}"

format = "%(message)s"
formatter = AnsiColorFormatter(format)

logger = logging.getLogger(APP_NAME)
logger.setLevel(logging.DEBUG)

cs_handler = logging.StreamHandler()
cs_handler.setLevel(logging.DEBUG)
cs_handler.setFormatter(formatter)
logger.addHandler(cs_handler)

logging.getLogger("filelock").setLevel(logging.INFO)