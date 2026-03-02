"""
StockQueen V1 - Database Initialization Script
Initialize Supabase database with schema
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import settings
from app.database import get_db
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def read_schema():
    """Read schema SQL file"""
    schema_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "database",
        "schema.sql"
    )
    
    with open(schema_path, 'r', encoding='utf-8') as f:
        return f.read()


def init_database():
    """Initialize database with schema"""
    try:
        logger.info("Starting database initialization...")
        
        # Read schema
        schema_sql = read_schema()
        
        # Get database client
        db = get_db()
        
        # Execute schema (split by semicolon for multiple statements)
        # Note: Supabase Python client doesn't support direct SQL execution
        # You need to run the SQL in Supabase SQL Editor
        # This script is for reference
        
        logger.info("=" * 60)
        logger.info("Database Schema SQL")
        logger.info("=" * 60)
        logger.info(schema_sql)
        logger.info("=" * 60)
        logger.info("")
        logger.info("⚠️  Please run the above SQL in Supabase SQL Editor:")
        logger.info("    1. Go to https://supabase.com/dashboard")
        logger.info("    2. Select your project")
        logger.info("    3. Click 'SQL Editor' in the left sidebar")
        logger.info("    4. Click 'New Query'")
        logger.info("    5. Paste the SQL above and click 'Run'")
        logger.info("=" * 60)
        
        return True
        
    except Exception as e:
        logger.error(f"Error initializing database: {e}")
        return False


if __name__ == "__main__":
    success = init_database()
    sys.exit(0 if success else 1)
