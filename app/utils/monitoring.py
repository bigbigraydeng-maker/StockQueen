"""
StockQueen V1 - Monitoring Utilities
Health checks, metrics, and monitoring
"""

import time
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
from functools import wraps

logger = logging.getLogger(__name__)


class MetricsCollector:
    """Collect and track application metrics"""
    
    def __init__(self):
        self.metrics = {
            "api_calls": {},
            "errors": {},
            "signals_generated": 0,
            "orders_executed": 0,
            "uptime_start": datetime.utcnow()
        }
    
    def record_api_call(self, service: str, endpoint: str, duration_ms: int, success: bool):
        """Record API call metrics"""
        if service not in self.metrics["api_calls"]:
            self.metrics["api_calls"][service] = {
                "total": 0,
                "success": 0,
                "failed": 0,
                "total_duration_ms": 0,
                "endpoints": {}
            }
        
        service_metrics = self.metrics["api_calls"][service]
        service_metrics["total"] += 1
        service_metrics["total_duration_ms"] += duration_ms
        
        if success:
            service_metrics["success"] += 1
        else:
            service_metrics["failed"] += 1
        
        if endpoint not in service_metrics["endpoints"]:
            service_metrics["endpoints"][endpoint] = 0
        service_metrics["endpoints"][endpoint] += 1
    
    def record_error(self, error_type: str, message: str):
        """Record error metrics"""
        if error_type not in self.metrics["errors"]:
            self.metrics["errors"][error_type] = 0
        self.metrics["errors"][error_type] += 1
    
    def record_signal(self):
        """Record signal generation"""
        self.metrics["signals_generated"] += 1
    
    def record_order(self):
        """Record order execution"""
        self.metrics["orders_executed"] += 1
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get current metrics"""
        uptime = datetime.utcnow() - self.metrics["uptime_start"]
        
        return {
            "uptime_seconds": uptime.total_seconds(),
            "uptime_formatted": str(uptime),
            "api_calls": self.metrics["api_calls"],
            "errors": self.metrics["errors"],
            "signals_generated": self.metrics["signals_generated"],
            "orders_executed": self.metrics["orders_executed"],
            "timestamp": datetime.utcnow().isoformat()
        }
    
    def reset(self):
        """Reset metrics"""
        self.metrics = {
            "api_calls": {},
            "errors": {},
            "signals_generated": 0,
            "orders_executed": 0,
            "uptime_start": datetime.utcnow()
        }


# Global metrics collector
metrics = MetricsCollector()


def track_api_call(service: str):
    """Decorator to track API calls"""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            start_time = time.time()
            success = True
            error = None
            
            try:
                result = await func(*args, **kwargs)
                return result
            except Exception as e:
                success = False
                error = str(e)
                raise
            finally:
                duration_ms = int((time.time() - start_time) * 1000)
                metrics.record_api_call(
                    service=service,
                    endpoint=func.__name__,
                    duration_ms=duration_ms,
                    success=success
                )
                
                if not success:
                    metrics.record_error(f"{service}_error", error)
        
        return wrapper
    return decorator


class HealthChecker:
    """Health check utilities"""
    
    @staticmethod
    async def check_database() -> bool:
        """Check database connection"""
        try:
            from app.database import get_db
            db = get_db()
            # Simple query to test connection
            result = db.table("risk_state").select("*").limit(1).execute()
            return True
        except Exception as e:
            logger.error(f"Database health check failed: {e}")
            return False
    
    @staticmethod
    async def check_deepseek_api() -> bool:
        """Check DeepSeek API connectivity"""
        try:
            from app.config import settings
            import httpx
            
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{settings.deepseek_base_url}/models",
                    headers={"Authorization": f"Bearer {settings.deepseek_api_key}"}
                )
                return response.status_code == 200
        except Exception as e:
            logger.error(f"DeepSeek API health check failed: {e}")
            return False
    
    @staticmethod
    async def check_supabase() -> bool:
        """Check Supabase connectivity"""
        try:
            from app.config import settings
            import httpx
            
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(settings.supabase_url)
                return response.status_code == 200
        except Exception as e:
            logger.error(f"Supabase health check failed: {e}")
            return False
    
    @staticmethod
    async def run_all_health_checks() -> Dict[str, Any]:
        """Run all health checks"""
        checks = {
            "database": await HealthChecker.check_database(),
            "deepseek_api": await HealthChecker.check_deepseek_api(),
            "supabase": await HealthChecker.check_supabase()
        }
        
        all_healthy = all(checks.values())
        
        return {
            "healthy": all_healthy,
            "checks": checks,
            "timestamp": datetime.utcnow().isoformat()
        }


class AlertManager:
    """Alert management for critical events"""
    
    def __init__(self):
        self.alert_history = []
        self.alert_cooldown = timedelta(minutes=30)  # Don't alert same issue within 30 min
    
    def should_alert(self, alert_type: str) -> bool:
        """Check if alert should be sent (avoid spam)"""
        now = datetime.utcnow()
        
        # Filter recent alerts of same type
        recent_alerts = [
            a for a in self.alert_history
            if a["type"] == alert_type
            and (now - a["timestamp"]) < self.alert_cooldown
        ]
        
        return len(recent_alerts) == 0
    
    def record_alert(self, alert_type: str, message: str):
        """Record alert in history"""
        self.alert_history.append({
            "type": alert_type,
            "message": message,
            "timestamp": datetime.utcnow()
        })
        
        # Clean old alerts (keep last 100)
        if len(self.alert_history) > 100:
            self.alert_history = self.alert_history[-100:]


# Global alert manager
alert_manager = AlertManager()
