"""
Database Migration Script for Railway PostgreSQL
Run this to create ATS Agent tables in production
"""
import os
import sys

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from models import db

def migrate_database():
    """Create all missing tables and columns."""
    app = create_app()
    
    with app.app_context():
        print("Starting database migration...")
        
        try:
            # Create all tables (this will only create missing ones)
            db.create_all()
            print("✅ Database migration completed successfully!")
            print("All ATS Agent tables have been created.")
            
        except Exception as e:
            print(f"❌ Error during migration: {e}")
            raise

if __name__ == '__main__':
    migrate_database()
