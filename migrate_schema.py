"""Auto-fix DB schema for description_suggeree column."""
import os

def migrate_description_column():
    """Change description_suggeree from varchar(50) to text."""
    db_uri = os.environ.get('DATABASE_URL', '')
    if not db_uri:
        return
    db_path = os.environ.get('DB_PATH')
    use_postgres = 'true' == os.environ.get('USE_POSTGRES', 'false').lower()
    if use_postgres:
        import psycopg2
        try:
            conn = psycopg2.connect(db_uri, connect_timeout=10)
            conn.autocommit = True
            cur = conn.cursor()
            # Check column type
            cur.execute("""
                SELECT data_type, character_maximum_length
                FROM information_schema.columns
                WHERE table_name = 'suggestions_taches' AND column_name = 'description_suggeree'
            """)
            row = cur.fetchone()
            if row and row[0] == 'character varying':
                cur.execute("ALTER TABLE suggestions_taches ALTER COLUMN description_suggeree TYPE TEXT")
                print("✅ Migrated description_suggeree: varchar(50) -> TEXT")
            else:
                print(f"ℹ️ description_suggeree is {row[0] if row else 'unknown'} - no migration needed")
            cur.close()
            conn.close()
        except Exception as e:
            print(f"⚠️ Migration error: {e}")
    else:
        # SQLite - the column type doesn't matter much, but let's check
        import sqlite3
        if db_path and os.path.exists(db_path):
            try:
                conn = sqlite3.connect(db_path)
                cur = conn.cursor()
                cur.execute("PRAGMA table_info(suggestions_taches)")
                cols = {row[1]: row[2] for row in cur.fetchall()}
                print(f"ℹ️ SQLite description_suggeree type: {cols.get('description_suggeree', 'unknown')}")
                conn.close()
            except Exception as e:
                print(f"⚠️ SQLite migration error: {e}")
