import os
import sqlite3
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash

DATABASE_URL = os.environ.get("DATABASE_URL")
IS_POSTGRES = DATABASE_URL is not None

if IS_POSTGRES:
    import psycopg2
    from psycopg2.extras import DictCursor

DATABASE = 'instance/sentiment_app.db'

def get_db():
    if IS_POSTGRES:
        conn = psycopg2.connect(DATABASE_URL)
        return conn
    else:
        conn = sqlite3.connect(DATABASE)
        conn.row_factory = sqlite3.Row
        return conn

def get_cursor(conn):
    if IS_POSTGRES:
        return conn.cursor(cursor_factory=DictCursor)
    return conn.cursor()

def execute_query(cursor, query, params=()):
    if IS_POSTGRES:
        query = query.replace('?', '%s')
    cursor.execute(query, params)

def init_db():
    if not IS_POSTGRES:
        os.makedirs('instance', exist_ok=True)
    
    conn = get_db()
    cursor = get_cursor(conn)
    
    id_type = "SERIAL PRIMARY KEY" if IS_POSTGRES else "INTEGER PRIMARY KEY AUTOINCREMENT"
    
    cursor.execute(f'''
        CREATE TABLE IF NOT EXISTS users (
            id {id_type},
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    cursor.execute(f'''
        CREATE TABLE IF NOT EXISTS predictions (
            id {id_type},
            user_id INTEGER NOT NULL,
            video_id TEXT NOT NULL,
            sentiment TEXT NOT NULL,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    
    cursor.execute(f'''
        CREATE TABLE IF NOT EXISTS tracker_history (
            id {id_type},
            user_id INTEGER NOT NULL,
            video_id TEXT NOT NULL,
            views_plot_path TEXT,
            likes_plot_path TEXT,
            subscribers_plot_path TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    
    conn.commit()
    conn.close()
    print(f"Database initialized successfully! (Using {'PostgreSQL' if IS_POSTGRES else 'SQLite'})")

def create_user(username, email, password):
    conn = get_db()
    cursor = get_cursor(conn)
    
    try:
        hashed_password = generate_password_hash(password, method='pbkdf2:sha256')
        query = 'INSERT INTO users (username, email, password) VALUES (?, ?, ?)'
        
        if IS_POSTGRES:
            query = query.replace('?', '%s') + ' RETURNING id'
            cursor.execute(query, (username, email, hashed_password))
            user_id = cursor.fetchone()['id']
        else:
            cursor.execute(query, (username, email, hashed_password))
            user_id = cursor.lastrowid
            
        conn.commit()
        conn.close()
        return user_id
    except Exception as e:
        print("Error creating user:", e)
        conn.close()
        return None

def verify_user(email, password):
    conn = get_db()
    cursor = get_cursor(conn)
    execute_query(cursor, 'SELECT * FROM users WHERE email = ?', (email,))
    user = cursor.fetchone()
    conn.close()
    
    if user and check_password_hash(user['password'], password):
        return dict(user)
    return None

def get_user_by_id(user_id):
    conn = get_db()
    cursor = get_cursor(conn)
    execute_query(cursor, 'SELECT * FROM users WHERE id = ?', (user_id,))
    user = cursor.fetchone()
    conn.close()
    return dict(user) if user else None

def add_prediction(user_id, video_id, sentiment):
    conn = get_db()
    cursor = get_cursor(conn)
    query = 'INSERT INTO predictions (user_id, video_id, sentiment) VALUES (?, ?, ?)'
    
    if IS_POSTGRES:
        query = query.replace('?', '%s') + ' RETURNING id'
        cursor.execute(query, (user_id, video_id, sentiment))
        prediction_id = cursor.fetchone()['id']
    else:
        cursor.execute(query, (user_id, video_id, sentiment))
        prediction_id = cursor.lastrowid
        
    conn.commit()
    conn.close()
    return prediction_id

def get_user_predictions(user_id, limit=None):
    conn = get_db()
    cursor = get_cursor(conn)
    
    if limit:
        execute_query(cursor, 'SELECT * FROM predictions WHERE user_id = ? ORDER BY timestamp DESC LIMIT ?', (user_id, limit))
    else:
        execute_query(cursor, 'SELECT * FROM predictions WHERE user_id = ? ORDER BY timestamp DESC', (user_id,))
    
    predictions = cursor.fetchall()
    conn.close()
    return [dict(pred) for pred in predictions]

def get_sentiment_stats(user_id):
    conn = get_db()
    cursor = get_cursor(conn)
    execute_query(cursor, 'SELECT sentiment, COUNT(*) as count FROM predictions WHERE user_id = ? GROUP BY sentiment', (user_id,))
    stats = cursor.fetchall()
    conn.close()
    return {stat['sentiment']: stat['count'] for stat in stats}

def add_tracker_history(user_id, video_id, plots):
    conn = get_db()
    cursor = get_cursor(conn)
    
    plot_paths = {
        'views': None,
        'likes': None,
        'subscribers': None
    }
    for plot in plots:
        # Expected format: {"type": "views", "data": "base64_string"} or something similar
        if isinstance(plot, dict) and 'type' in plot and 'data' in plot:
            if plot['type'] in plot_paths:
                plot_paths[plot['type']] = plot['data']
        # Fallback for old list of paths logic (just in case)
        elif isinstance(plot, str):
            if 'views' in plot:
                plot_paths['views'] = plot
            elif 'likes' in plot:
                plot_paths['likes'] = plot
            elif 'subscribers' in plot:
                plot_paths['subscribers'] = plot

    query = 'INSERT INTO tracker_history (user_id, video_id, views_plot_path, likes_plot_path, subscribers_plot_path) VALUES (?, ?, ?, ?, ?)'
    params = (user_id, video_id, plot_paths['views'], plot_paths['likes'], plot_paths['subscribers'])
    
    if IS_POSTGRES:
        query = query.replace('?', '%s') + ' RETURNING id'
        cursor.execute(query, params)
        history_id = cursor.fetchone()['id']
    else:
        cursor.execute(query, params)
        history_id = cursor.lastrowid
        
    conn.commit()
    conn.close()
    return history_id

def get_tracker_history(user_id, limit=3):
    conn = get_db()
    cursor = get_cursor(conn)
    execute_query(cursor, 'SELECT * FROM tracker_history WHERE user_id = ? ORDER BY timestamp DESC LIMIT ?', (user_id, limit))
    history = cursor.fetchall()
    conn.close()
    return [dict(row) for row in history]

if __name__ == '__main__':
    init_db()
