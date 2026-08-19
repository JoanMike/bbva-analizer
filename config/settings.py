"""
Configuración y constantes del proyecto BBVA Analizer
"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv


def _looks_like_local_project_root(path):
    """Detecta si un directorio parece la raíz del proyecto en desarrollo."""
    required_markers = ('config', 'static', 'templates')
    return all((path / marker).exists() for marker in required_markers)


def _resolve_runtime_base_dir():
    """Resuelve la base operativa para código fuente y ejecutable compilado."""
    source_base_dir = Path(__file__).resolve().parent.parent

    if not getattr(sys, 'frozen', False):
        return source_base_dir

    executable_dir = Path(sys.executable).resolve().parent
    parent_dir = executable_dir.parent

    if executable_dir.name.lower() == 'dist' and _looks_like_local_project_root(parent_dir):
        return parent_dir

    return executable_dir


SOURCE_BASE_DIR = Path(__file__).resolve().parent.parent
BASE_DIR = _resolve_runtime_base_dir()
BUNDLE_DIR = Path(getattr(sys, '_MEIPASS', SOURCE_BASE_DIR)).resolve()
IS_FROZEN_BUILD = getattr(sys, 'frozen', False)


def _load_environment_variables():
    """Carga .env desde la ubicación correcta según el modo de ejecución."""
    env_candidates = [BASE_DIR / '.env', Path.cwd() / '.env']

    if IS_FROZEN_BUILD:
        env_candidates.insert(1, Path(sys.executable).resolve().parent / '.env')
    else:
        env_candidates.append(SOURCE_BASE_DIR / '.env')

    seen = set()
    for env_path in env_candidates:
        resolved_path = str(env_path.resolve())
        if resolved_path in seen:
            continue
        seen.add(resolved_path)
        if env_path.exists():
            load_dotenv(str(env_path), override=False)


_load_environment_variables()

# Directorios de datos
DATA_DIR = os.path.join(str(BASE_DIR), 'data')
UPLOAD_FOLDER = os.path.join(str(BASE_DIR), 'uploads')
BUNDLED_DATA_DIR = os.path.join(str(BUNDLE_DIR), 'data')

# Archivos de configuración y datos (legacy)
PERSONAS_FILE = os.path.join(DATA_DIR, 'personas.json')
DESCRIPTIONS_FILE = os.path.join(DATA_DIR, 'description_replacements.json')
DATABASE_FILE = os.path.join(DATA_DIR, 'bbva_analizer.db')
BUNDLED_PERSONAS_FILE = os.path.join(BUNDLED_DATA_DIR, 'personas.json')
BUNDLED_DESCRIPTIONS_FILE = os.path.join(BUNDLED_DATA_DIR, 'description_replacements.json')

# Configuración de Flask
MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max
FLASK_PORT = 5000

# Contraseña para desbloquear PDFs protegidos
PDF_UNLOCK_PASSWORD = os.getenv('PDF_UNLOCK_PASSWORD')

# Personas por defecto
DEFAULT_PERSONAS = [
    {'id': 'persona1', 'nombre': 'Persona 1', 'icono': '👤', 'color': '#1e88e5'},
    {'id': 'persona2', 'nombre': 'Persona 2', 'icono': '👤', 'color': '#43a047'},
    {'id': 'persona3', 'nombre': 'Persona 3', 'icono': '👤', 'color': '#e53935'}
]

# Conceptos a excluir de las transacciones
CONCEPTOS_EXCLUIDOS = [
    'SALDO CREDITO UTILIZADO MES ANTERIOR',
    'SALDO INTERESES Y GASTOS MES ANTERIOR',
    'PAGO RECIBIDO',
    'SEGURO DE DESGRAVAMEN'
]

# Keywords a excluir de descripciones
DESCRIPTION_EXCLUDE_KEYWORDS = [
    'TOTALES', 'RESUMEN', 'LIMITE', 'CONSUMOS', 'NOMBRE USUARIO',
    'DETALLE CUOTAS', 'TASA DE', 'CAPITAL DE', 'NUMERO DE CUOTA',
    'INTERESES SI PAGA', 'ORIGINAL', 'IMPORTE DE CUOTA'
]
