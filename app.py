from flask import Flask, render_template, request, jsonify
import os
import sys
import threading
import base64
from datetime import datetime
from uuid import uuid4
from werkzeug.utils import secure_filename

# Importar configuración y base de datos
from config import settings
from src import database as db
from src.pdf_parser import extract_bbva_data
from src.imaging import generar_imagen_pago

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = settings.UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = settings.MAX_CONTENT_LENGTH

IS_FROZEN_BUILD = getattr(sys, 'frozen', False)

# Crear carpetas necesarias si no existen
os.makedirs(settings.DATA_DIR, exist_ok=True)
os.makedirs(settings.UPLOAD_FOLDER, exist_ok=True)

# Importar constantes desde settings
PERSONAS_FILE = settings.PERSONAS_FILE
DESCRIPTIONS_FILE = settings.DESCRIPTIONS_FILE
DEFAULT_PERSONAS_FILE = getattr(settings, 'BUNDLED_PERSONAS_FILE', PERSONAS_FILE)
DEFAULT_DESCRIPTIONS_FILE = getattr(settings, 'BUNDLED_DESCRIPTIONS_FILE', DESCRIPTIONS_FILE)
DEFAULT_PERSONAS = settings.DEFAULT_PERSONAS


# Migrar datos existentes de JSON a BD al iniciar
def migrate_legacy_data():
    """Migra datos de archivos JSON a la base de datos si es necesario"""
    try:
        # Verificar si hay datos en la BD
        stats = db.get_database_stats()

        # Si no hay personas en BD, migrar desde JSON o usar defaults
        if stats['personas_count'] == 0:
            if os.path.exists(PERSONAS_FILE) or os.path.exists(DEFAULT_PERSONAS_FILE):
                app.logger.info('Migrando personas desde JSON a BD...')
                db.migrate_from_json()
            else:
                # Insertar personas por defecto
                app.logger.info('Insertando personas por defecto en BD...')
                for persona in DEFAULT_PERSONAS:
                    db.add_persona(persona['id'], persona['nombre'], persona['icono'], persona['color'])

        # Migrar reemplazos de descripciones si existen
        if stats['replacements_count'] == 0 and (
            os.path.exists(DESCRIPTIONS_FILE) or os.path.exists(DEFAULT_DESCRIPTIONS_FILE)
        ):
            app.logger.info('Migrando reemplazos de descripciones desde JSON a BD...')
            db.migrate_from_json()

        app.logger.info('Migración de datos completada')
        app.logger.info(f'Estadísticas de BD: {stats}')
    except Exception as e:
        app.logger.warning(f'Error en migración de datos: {e}')


# Ejecutar migración al iniciar
migrate_legacy_data()


def load_personas():
    """Carga la lista de personas desde la base de datos"""
    return db.get_all_personas()


@app.route('/')
def index():
    return render_template('index.html', is_frozen=IS_FROZEN_BUILD)


def _shutdown_werkzeug_server():
    shutdown_func = request.environ.get('werkzeug.server.shutdown')
    if shutdown_func is None:
        return False
    shutdown_func()
    return True


def _schedule_process_exit(delay_seconds: float = 0.5) -> None:
    timer = threading.Timer(delay_seconds, lambda: os._exit(0))
    timer.daemon = True
    timer.start()


def safe_delete_file(file_path):
    """Intenta eliminar un archivo temporal sin interrumpir la respuesta de la API."""
    if not file_path:
        return

    try:
        if os.path.exists(file_path):
            os.remove(file_path)
    except Exception as cleanup_error:
        app.logger.warning(f'No se pudo eliminar archivo temporal {file_path}: {cleanup_error}')


@app.route('/shutdown', methods=['POST'])
def shutdown_server():
    """Detiene la aplicación cuando se ejecuta como ejecutable."""
    if not IS_FROZEN_BUILD:
        return jsonify({'status': 'ignored'}), 200

    app.logger.info('Solicitud de apagado recibida. Cerrando aplicación...')

    shutdown_called = _shutdown_werkzeug_server()

    if not shutdown_called:
        app.logger.warning('No se encontró el hook de apagado de Werkzeug. Se forzará el cierre del proceso.')

    _schedule_process_exit()

    return jsonify({'status': 'shutting down'})


@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({'error': 'No se encontró archivo'}), 400

    file = request.files['file']

    if file.filename == '':
        return jsonify({'error': 'No se seleccionó archivo'}), 400

    if file and file.filename.lower().endswith('.pdf'):
        filename = secure_filename(file.filename)
        base_name, ext = os.path.splitext(filename)
        unique_filename = f"{base_name}_{uuid4().hex}{ext}"
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
        file.save(filepath)

        try:
            # Extraer datos del PDF
            data = extract_bbva_data(filepath)

            return jsonify(data)

        except ValueError as e:
            return jsonify({'error': str(e)}), 400

        except Exception as e:
            return jsonify({'error': f'Error al procesar PDF: {str(e)}'}), 500

        finally:
            safe_delete_file(filepath)

    return jsonify({'error': 'El archivo debe ser un PDF'}), 400


@app.route('/calculate', methods=['POST'])
def calculate_totals():
    """
    Calcula los totales por persona según las asignaciones
    """
    data = request.json
    transacciones = data.get('transacciones', [])

    # Cargar personas configuradas
    personas = load_personas()

    # Inicializar totales dinámicamente según las personas configuradas
    totales = {}
    for persona in personas:
        totales[persona['id']] = {'cargos': 0, 'abonos': 0, 'total': 0}

    # Agregar categoría "sin_asignar"
    totales['sin_asignar'] = {'cargos': 0, 'abonos': 0, 'total': 0}

    for trans in transacciones:
        asignado = trans.get('asignado_a', 'sin_asignar')

        # Validar que el monto sea numérico
        try:
            monto = float(trans.get('monto', 0))
        except (ValueError, TypeError):
            monto = 0.0

        tipo = trans.get('tipo', 'cargo')

        if asignado in totales:
            if tipo == 'cargo':
                totales[asignado]['cargos'] += monto
                totales[asignado]['total'] += monto
            else:
                totales[asignado]['abonos'] += monto
                totales[asignado]['total'] -= monto

    return jsonify(totales)


@app.route('/personas', methods=['GET'])
def get_personas():
    """Obtiene la lista de personas configuradas"""
    return jsonify(db.get_all_personas())


@app.route('/personas', methods=['POST'])
def add_persona():
    """Agrega una nueva persona"""
    nueva_persona = request.json

    # Validar que tenga los campos requeridos
    if not all(k in nueva_persona for k in ['id', 'nombre', 'icono', 'color']):
        return jsonify({'error': 'Faltan campos requeridos'}), 400

    try:
        db.add_persona(
            nueva_persona['id'],
            nueva_persona['nombre'],
            nueva_persona['icono'],
            nueva_persona['color']
        )
        return jsonify({'success': True, 'personas': db.get_all_personas()})
    except Exception as e:
        return jsonify({'error': f'Error al agregar persona: {str(e)}'}), 400


@app.route('/personas/<persona_id>', methods=['DELETE'])
def delete_persona(persona_id):
    """Elimina una persona"""
    success = db.delete_persona(persona_id)
    if success:
        return jsonify({'success': True, 'personas': db.get_all_personas()})
    return jsonify({'error': 'Persona no encontrada'}), 404


@app.route('/personas/<persona_id>', methods=['PUT'])
def update_persona(persona_id):
    """Actualiza una persona"""
    persona_actualizada = request.json

    if not all(k in persona_actualizada for k in ['nombre', 'icono', 'color']):
        return jsonify({'error': 'Faltan campos requeridos'}), 400

    success = db.update_persona(
        persona_id,
        persona_actualizada['nombre'],
        persona_actualizada['icono'],
        persona_actualizada['color']
    )

    if success:
        return jsonify({'success': True, 'personas': db.get_all_personas()})
    return jsonify({'error': 'Persona no encontrada'}), 404


# Endpoints para reemplazos de descripciones
@app.route('/description-replacements', methods=['GET'])
def get_description_replacements():
    """Obtiene todos los reemplazos de descripciones"""
    replacements = db.get_all_description_replacements()
    return jsonify({'success': True, 'replacements': replacements})


@app.route('/description-replacements', methods=['POST'])
def add_description_replacement():
    """Agrega o actualiza un reemplazo de descripción"""
    data = request.json
    original = data.get('original')
    replacement = data.get('replacement')

    if not original or not replacement:
        return jsonify({'error': 'Se requiere descripción original y reemplazo'}), 400

    db.add_description_replacement(original, replacement)
    replacements = db.get_all_description_replacements()

    return jsonify({'success': True, 'replacements': replacements})


@app.route('/description-replacements/<path:original>', methods=['DELETE'])
def delete_description_replacement(original):
    """Elimina un reemplazo de descripción"""
    success = db.delete_description_replacement(original)

    if success:
        replacements = db.get_all_description_replacements()
        return jsonify({'success': True, 'replacements': replacements})

    return jsonify({'error': 'Reemplazo no encontrado'}), 404


# Endpoints para asignaciones de transacciones
@app.route('/assignments/<pdf_id>', methods=['POST'])
def save_assignments(pdf_id):
    """Guarda las asignaciones de transacciones de un PDF"""
    data = request.json

    if not data or 'transacciones' not in data:
        return jsonify({'error': 'Datos inválidos'}), 400

    try:
        filename = data.get('filename', 'unknown.pdf')
        info_general = data.get('info_general', {})
        transacciones = data.get('transacciones', [])

        # Guardar en la base de datos
        db.save_pdf_data(pdf_id, filename, info_general, transacciones)

        return jsonify({'success': True, 'message': 'Asignaciones guardadas correctamente'})
    except Exception as e:
        return jsonify({'error': f'Error al guardar asignaciones: {str(e)}'}), 500


@app.route('/assignments/<pdf_id>', methods=['GET'])
def load_assignments(pdf_id):
    """Carga las asignaciones guardadas de un PDF"""
    try:
        pdf_data = db.get_pdf_data(pdf_id)

        if pdf_data:
            return jsonify({
                'success': True,
                'found': True,
                'data': pdf_data
            })
        else:
            return jsonify({
                'success': True,
                'found': False,
                'message': 'No hay asignaciones guardadas para este PDF'
            })
    except Exception as e:
        return jsonify({'error': f'Error al cargar asignaciones: {str(e)}'}), 500


@app.route('/assignments/<pdf_id>/transaction/<int:transaction_index>', methods=['PUT'])
def update_assignment(pdf_id, transaction_index):
    """Actualiza la asignación de una transacción específica"""
    data = request.json

    if not data or 'asignado_a' not in data:
        return jsonify({'error': 'Datos inválidos'}), 400

    try:
        success = db.update_transaction_assignment(
            pdf_id,
            transaction_index,
            data['asignado_a']
        )

        if success:
            return jsonify({'success': True, 'message': 'Asignación actualizada'})
        else:
            return jsonify({'error': 'Transacción no encontrada'}), 404
    except Exception as e:
        return jsonify({'error': f'Error al actualizar asignación: {str(e)}'}), 500


@app.route('/assignments/<pdf_id>', methods=['DELETE'])
def clear_assignments(pdf_id):
    """Limpia las asignaciones de un PDF"""
    try:
        # Obtener transacciones y marcarlas como sin_asignar
        transacciones = db.get_transactions_by_pdf(pdf_id)

        for trans in transacciones:
            db.update_transaction_assignment(pdf_id, trans['transaction_index'], 'sin_asignar')

        return jsonify({'success': True, 'message': 'Asignaciones limpiadas'})
    except Exception as e:
        return jsonify({'error': f'Error al limpiar asignaciones: {str(e)}'}), 500


@app.route('/database/stats', methods=['GET'])
def get_stats():
    """Obtiene estadísticas de la base de datos"""
    try:
        stats = db.get_database_stats()
        return jsonify({'success': True, 'stats': stats})
    except Exception as e:
        return jsonify({'error': f'Error al obtener estadísticas: {str(e)}'}), 500


@app.route('/database/cleanup', methods=['POST'])
def cleanup_old_data():
    """Limpia datos antiguos de la base de datos"""
    try:
        days = request.json.get('days', 90) if request.json else 90
        deleted = db.clean_old_pdfs(days)
        return jsonify({
            'success': True,
            'message': f'Se eliminaron {deleted} PDFs antiguos',
            'deleted_count': deleted
        })
    except Exception as e:
        return jsonify({'error': f'Error al limpiar datos: {str(e)}'}), 500


@app.route('/generar-pagos', methods=['POST'])
def generar_pagos():
    """
    Genera imágenes de pago para cada persona con saldo pendiente
    Retorna las imágenes en formato base64 para descarga en el cliente
    """
    data = request.json
    totales = data.get('totales', {})
    personas_data = data.get('personas', [])

    # Crear diccionario de personas por ID para fácil acceso
    personas_dict = {p['id']: p for p in personas_data}

    imagenes = []

    for persona_id, datos in totales.items():
        # Saltar "sin_asignar" y personas con total = 0
        if persona_id == 'sin_asignar' or datos['total'] <= 0:
            continue

        # Obtener información de la persona
        persona = personas_dict.get(persona_id, {})
        nombre = persona.get('nombre', persona_id.title())
        color = persona.get('color', '#1e88e5')

        # Generar imagen
        img_bytes = generar_imagen_pago(nombre, datos['total'], color)

        # Convertir a base64
        img_base64 = base64.b64encode(img_bytes).decode('utf-8')

        # Generar nombre de archivo
        fecha_actual = datetime.now().strftime('%Y%m%d')
        nombre_archivo = f"Pago_{nombre.replace(' ', '_')}_{fecha_actual}.jpg"

        imagenes.append({
            'nombre_archivo': nombre_archivo,
            'imagen_base64': img_base64,
            'persona': nombre,
            'monto': datos['total']
        })

    return jsonify({
        'success': True,
        'imagenes': imagenes,
        'total_generadas': len(imagenes)
    })


if __name__ == '__main__':
    app.run(debug=False, port=settings.FLASK_PORT)
