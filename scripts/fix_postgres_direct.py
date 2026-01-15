"""
Direct PostgreSQL Fix for Railway
Connects directly to PostgreSQL and fixes column size
"""
import os
import psycopg2

def fix_postgres_column():
    """Connect directly to PostgreSQL and fix source_file_id column."""
    # Get PostgreSQL URL from environment
    database_url = os.getenv('DATABASE_URL')
    
    if not database_url:
        print("❌ DATABASE_URL environment variable not found!")
        print("Make sure you're running this on Railway with PostgreSQL addon.")
        return
    
    print(f"Connecting to PostgreSQL...")
    print(f"Database URL: {database_url[:50]}...")  # Show first 50 chars only
    
    try:
        # Connect to PostgreSQL
        conn = psycopg2.connect(database_url)
        cursor = conn.cursor()
        
        # Check if table exists
        cursor.execute("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.tables 
                WHERE table_name = 'cv_candidates'
            );
        """)
        table_exists = cursor.fetchone()[0]
        
        if not table_exists:
            print("⚠️  Table 'cv_candidates' doesn't exist yet. Creating tables...")
            # Import and run db.create_all()
            from app import create_app
            from models import db
            app = create_app('production')
            with app.app_context():
                db.create_all()
            print("✅ Tables created!")
            conn.close()
            return
        
        # Check current column size
        cursor.execute("""
            SELECT character_maximum_length 
            FROM information_schema.columns 
            WHERE table_name = 'cv_candidates' 
            AND column_name = 'source_file_id';
        """)
        
        result = cursor.fetchone()
        if result:
            current_length = result[0]
            print(f"Current source_file_id length: {current_length}")
            
            if current_length == 500:
                print("✅ Column is already the correct size (500)!")
                conn.close()
                return
            
            # Alter the column
            print("Altering source_file_id column to VARCHAR(500)...")
            cursor.execute("""
                ALTER TABLE cv_candidates 
                ALTER COLUMN source_file_id TYPE VARCHAR(500);
            """)
            conn.commit()
            
            # Verify the change
            cursor.execute("""
                SELECT character_maximum_length 
                FROM information_schema.columns 
                WHERE table_name = 'cv_candidates' 
                AND column_name = 'source_file_id';
            """)
            new_length = cursor.fetchone()[0]
            
            print(f"✅ Column altered successfully!")
            print(f"   Old length: {current_length}")
            print(f"   New length: {new_length}")
        else:
            print("⚠️  Column 'source_file_id' not found!")
        
        cursor.close()
        conn.close()
        print("✅ Database connection closed.")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        raise

if __name__ == '__main__':
    fix_postgres_column()
