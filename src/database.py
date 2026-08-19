import sqlite3
import json
import os
from datetime import datetime, timedelta, timezone
from contextlib import contextmanager
from config import settings

DATA_DIR = settings.DATA_DIR
DATABASE_FILE = settings.DATABASE_FILE
PERSONAS_FILE = settings.PERSONAS_FILE
DESCRIPTIONS_FILE = settings.DESCRIPTIONS_FILE
BUNDLED_PERSONAS_FILE = getattr(settings, 'BUNDLED_PERSONAS_FILE', PERSONAS_FILE)
BUNDLED_DESCRIPTIONS_FILE = getattr(settings, 'BUNDLED_DESCRIPTIONS_FILE', DESCRIPTIONS_FILE)

# Asegurar que existe el directorio data
os.makedirs(DATA_DIR, exist_ok=True)


def _resolve_existing_file(*candidates):
    """Devuelve el primer archivo existente dentro de una lista de candidatos."""
    for candidate in candidates:
        if candidate and os.path.exists(candidate):
            return candidate
    return candidates[0] if candidates else None

@contextmanager
def get_db():
    """Context manager para conexión a la base de datos"""
    conn = sqlite3.connect(DATABASE_FILE)
    conn.row_factory = sqlite3.Row  # Para acceder a columnas por nombre
    try:
        yield conn
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()

def init_database():
    """Inicializa la base de datos y crea las tablas necesarias"""
    with get_db() as conn:
        cursor = conn.cursor()
        
        # Tabla de personas
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS personas (
                id TEXT PRIMARY KEY,
                nombre TEXT NOT NULL,
                icono TEXT NOT NULL,
                color TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Tabla de reemplazos de descripciones
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS description_replacements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                original_description TEXT UNIQUE NOT NULL,
                new_description TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Tabla de PDFs procesados
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS pdfs (
                pdf_id TEXT PRIMARY KEY,
                filename TEXT NOT NULL,
                upload_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                info_general TEXT,  -- JSON con info general del PDF
                last_accessed TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Tabla de transacciones
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pdf_id TEXT NOT NULL,
                transaction_index INTEGER NOT NULL,
                fecha TEXT NOT NULL,
                descripcion TEXT NOT NULL,
                descripcion_original TEXT,
                monto REAL NOT NULL,
                asignado_a TEXT DEFAULT 'sin_asignar',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (pdf_id) REFERENCES pdfs(pdf_id) ON DELETE CASCADE,
                UNIQUE(pdf_id, transaction_index)
            )
        ''')
        
        # Índices para mejorar rendimiento
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_transactions_pdf_id ON transactions(pdf_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_transactions_asignado ON transactions(asignado_a)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_pdfs_last_accessed ON pdfs(last_accessed)')
        
        print("✅ Base de datos inicializada correctamente")

def migrate_from_json():
    """Migra datos existentes de archivos JSON a la base de datos"""
    with get_db() as conn:
        cursor = conn.cursor()
        
        # Migrar personas
        personas_file = _resolve_existing_file(PERSONAS_FILE, BUNDLED_PERSONAS_FILE)
        if os.path.exists(personas_file):
            with open(personas_file, 'r', encoding='utf-8') as f:
                personas = json.load(f)
                for persona in personas:
                    cursor.execute('''
                        INSERT OR REPLACE INTO personas (id, nombre, icono, color)
                        VALUES (?, ?, ?, ?)
                    ''', (persona['id'], persona['nombre'], persona['icono'], persona['color']))
                print(f"✅ Migradas {len(personas)} personas desde JSON")
        
        # Migrar reemplazos de descripciones
        desc_file = _resolve_existing_file(DESCRIPTIONS_FILE, BUNDLED_DESCRIPTIONS_FILE)
        if os.path.exists(desc_file):
            with open(desc_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                replacements = data.get('replacements', {})
                for original, new_desc in replacements.items():
                    cursor.execute('''
                        INSERT OR REPLACE INTO description_replacements (original_description, new_description)
                        VALUES (?, ?)
                    ''', (original, new_desc))
                print(f"✅ Migrados {len(replacements)} reemplazos de descripciones desde JSON")

# === FUNCIONES CRUD PARA PERSONAS ===

def get_all_personas():
    """Obtiene todas las personas"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT id, nombre, icono, color FROM personas ORDER BY nombre')
        rows = cursor.fetchall()
        return [dict(row) for row in rows]

def add_persona(persona_id, nombre, icono, color):
    """Agrega una nueva persona"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO personas (id, nombre, icono, color)
            VALUES (?, ?, ?, ?)
        ''', (persona_id, nombre, icono, color))
        return persona_id

def update_persona(persona_id, nombre, icono, color):
    """Actualiza una persona existente"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE personas 
            SET nombre = ?, icono = ?, color = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (nombre, icono, color, persona_id))
        return cursor.rowcount > 0

def delete_persona(persona_id):
    """Elimina una persona"""
    with get_db() as conn:
        cursor = conn.cursor()
        # Actualizar transacciones asignadas a esta persona
        cursor.execute('''
            UPDATE transactions 
            SET asignado_a = 'sin_asignar', updated_at = CURRENT_TIMESTAMP
            WHERE asignado_a = ?
        ''', (persona_id,))
        # Eliminar la persona
        cursor.execute('DELETE FROM personas WHERE id = ?', (persona_id,))
        return cursor.rowcount > 0

# === FUNCIONES CRUD PARA REEMPLAZOS DE DESCRIPCIONES ===

def get_all_description_replacements():
    """Obtiene todos los reemplazos de descripciones como diccionario"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT original_description, new_description FROM description_replacements')
        rows = cursor.fetchall()
        return {row['original_description']: row['new_description'] for row in rows}

def add_description_replacement(original, new_description):
    """Agrega un nuevo reemplazo de descripción"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO description_replacements (original_description, new_description)
            VALUES (?, ?)
        ''', (original, new_description))
        return cursor.lastrowid

def delete_description_replacement(original):
    """Elimina un reemplazo de descripción"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('DELETE FROM description_replacements WHERE original_description = ?', (original,))
        return cursor.rowcount > 0

# === FUNCIONES CRUD PARA PDFs Y TRANSACCIONES ===

def save_pdf_data(pdf_id, filename, info_general, transacciones):
    """Guarda los datos de un PDF procesado y sus transacciones"""
    with get_db() as conn:
        cursor = conn.cursor()
        
        # Guardar información del PDF
        cursor.execute('''
            INSERT OR REPLACE INTO pdfs (pdf_id, filename, info_general, upload_date, last_accessed)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        ''', (pdf_id, filename, json.dumps(info_general)))
        
        # Eliminar transacciones antiguas de este PDF
        cursor.execute('DELETE FROM transactions WHERE pdf_id = ?', (pdf_id,))
        
        # Guardar transacciones
        for index, trans in enumerate(transacciones):
            cursor.execute('''
                INSERT INTO transactions 
                (pdf_id, transaction_index, fecha, descripcion, descripcion_original, monto, asignado_a)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                pdf_id,
                index,
                trans.get('fecha', ''),
                trans.get('descripcion', ''),
                trans.get('descripcion_original'),
                trans.get('monto', 0.0),
                trans.get('asignado_a', 'sin_asignar')
            ))
        
        return pdf_id

def get_pdf_data(pdf_id):
    """Obtiene los datos de un PDF y sus transacciones"""
    with get_db() as conn:
        cursor = conn.cursor()
        
        # Actualizar última fecha de acceso
        cursor.execute('''
            UPDATE pdfs SET last_accessed = CURRENT_TIMESTAMP WHERE pdf_id = ?
        ''', (pdf_id,))
        
        # Obtener info del PDF
        cursor.execute('SELECT filename, info_general FROM pdfs WHERE pdf_id = ?', (pdf_id,))
        pdf_row = cursor.fetchone()
        
        if not pdf_row:
            return None
        
        # Obtener transacciones
        cursor.execute('''
            SELECT transaction_index, fecha, descripcion, descripcion_original, monto, asignado_a
            FROM transactions 
            WHERE pdf_id = ?
            ORDER BY transaction_index
        ''', (pdf_id,))
        trans_rows = cursor.fetchall()
        
        transacciones = [dict(row) for row in trans_rows]
        
        return {
            'filename': pdf_row['filename'],
            'info_general': json.loads(pdf_row['info_general']) if pdf_row['info_general'] else {},
            'transacciones': transacciones
        }

def update_transaction_assignment(pdf_id, transaction_index, asignado_a):
    """Actualiza la asignación de una transacción"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE transactions 
            SET asignado_a = ?, updated_at = CURRENT_TIMESTAMP
            WHERE pdf_id = ? AND transaction_index = ?
        ''', (asignado_a, pdf_id, transaction_index))
        return cursor.rowcount > 0

def get_transactions_by_pdf(pdf_id):
    """Obtiene todas las transacciones de un PDF con sus asignaciones"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT transaction_index, fecha, descripcion, descripcion_original, monto, asignado_a
            FROM transactions 
            WHERE pdf_id = ?
            ORDER BY transaction_index
        ''', (pdf_id,))
        rows = cursor.fetchall()
        return [dict(row) for row in rows]

def clean_old_pdfs(days=90):
    """Elimina PDFs que no han sido accedidos en X días"""
    with get_db() as conn:
        cursor = conn.cursor()
        cutoff_date = (datetime.now(timezone.utc) - timedelta(days=days)).strftime('%Y-%m-%d %H:%M:%S')
        cursor.execute('''
            DELETE FROM pdfs WHERE last_accessed < ?
        ''', (cutoff_date,))
        deleted_count = cursor.rowcount
        print(f"🗑️ Eliminados {deleted_count} PDFs antiguos (más de {days} días sin acceso)")
        return deleted_count

def get_database_stats():
    """Obtiene estadísticas de la base de datos"""
    with get_db() as conn:
        cursor = conn.cursor()
        
        stats = {}
        
        cursor.execute('SELECT COUNT(*) as count FROM personas')
        stats['personas_count'] = cursor.fetchone()['count']
        
        cursor.execute('SELECT COUNT(*) as count FROM description_replacements')
        stats['replacements_count'] = cursor.fetchone()['count']
        
        cursor.execute('SELECT COUNT(*) as count FROM pdfs')
        stats['pdfs_count'] = cursor.fetchone()['count']
        
        cursor.execute('SELECT COUNT(*) as count FROM transactions')
        stats['transactions_count'] = cursor.fetchone()['count']
        
        return stats

# Inicializar la base de datos al importar el módulo
if __name__ != '__main__':
    init_database()
