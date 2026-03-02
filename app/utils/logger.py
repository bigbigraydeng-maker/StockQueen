"""
StockQueen V1 - Logging Utilities
Structured logging for better observability
"""

import logging
import json
from datetime import datetime
from typing import Any, Dict


class StructuredLogFormatter(logging.Formatter):
    """JSON formatter for structured logging"""
    
    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": datetime.utcnow().isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        
        # Add extra fields if present
        if hasattr(record, "extra"):
            log_data.update(record.extra)
        
        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
        
        return json.dumps(log_data, default=str)


def get_logger(name: str) -> logging.Logger:
    """Get logger with structured formatting"""
    logger = logging.getLogger(name)
    return logger


def log_event(
    logger: logging.Logger,
    event_type: str,
    message: str,
    extra: Dict[str, Any] = None,
    level: str = "info"
):
    """Log structured event"""
    log_data = {
        "event_type": event_type,
        **(extra or {})
    }
    
    record = logger.makeRecord(
        logger.name,
        getattr(logging, level.upper()),
        "",  # fn
        0,   # lno
        message,
        (),  # args
        None,  # exc_info
        extra={"extra": log_data}
    )
    
    logger.handle(record)
