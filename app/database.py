"""
StockQueen V1 - Database Module
Supabase client initialization and database operations
"""

from supabase import create_client, Client, ClientOptions
from app.config import settings
import logging

logger = logging.getLogger(__name__)


class Database:
    """Supabase database client singleton"""
    _instance: Client = None

    @classmethod
    def get_client(cls) -> Client:
        """Get or create Supabase client"""
        if cls._instance is None:
            cls._instance = create_client(
                settings.supabase_url,
                settings.supabase_service_key,
                options=ClientOptions(timeout=10),  # 10s timeout — prevents blocking event loop indefinitely
            )
            logger.info("Supabase client initialized")
        return cls._instance


# Convenience function
def get_db() -> Client:
    """Get database client"""
    return Database.get_client()
