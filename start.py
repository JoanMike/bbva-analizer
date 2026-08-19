#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Script de inicio rápido para BBVA Analizer
Ejecuta este archivo para iniciar la aplicación automáticamente
"""

import os
import sys
import logging
import webbrowser
from threading import Timer
from app import app
from config import settings


def configure_logging():
    """Configura el logging para consola o archivo según el contexto."""
    log_format = '%(asctime)s [%(levelname)s] %(message)s'

    if getattr(sys, 'frozen', False):
        log_file = os.path.join(os.getcwd(), 'bbva_analizer.log')
        logging.basicConfig(
            level=logging.INFO,
            format=log_format,
            handlers=[logging.FileHandler(log_file, encoding='utf-8')]
        )
    else:
        logging.basicConfig(
            level=logging.INFO,
            format=log_format,
            handlers=[logging.StreamHandler(sys.stdout)]
        )


configure_logging()
logger = logging.getLogger(__name__)

def open_browser():
    """Abre el navegador después de 1.5 segundos"""
    webbrowser.open(f'http://localhost:{settings.FLASK_PORT}')

if __name__ == '__main__':
    banner = "=" * 60
    mensajes = [
        banner,
        "🚀 BBVA Analizer - Iniciando aplicación...",
        banner,
        "",
        "📋 Información:",
        f"   - URL: http://localhost:{settings.FLASK_PORT}",
        "   - Presiona Ctrl+C para detener el servidor",
        "",
        "💡 La aplicación se abrirá automáticamente en tu navegador",
        banner,
        ""
    ]

    for mensaje in mensajes:
        logger.info(mensaje)
        if not getattr(sys, 'frozen', False):
            print(mensaje)
    
    # Abrir navegador automáticamente después de 1.5 segundos
    Timer(1.5, open_browser).start()
    
    # Iniciar servidor Flask (debug=False para evitar mensaje de advertencia)
    try:
        app.run(debug=False, port=settings.FLASK_PORT, use_reloader=False)
    except KeyboardInterrupt:
        mensaje = "\n\n👋 Aplicación detenida. ¡Hasta pronto!"
        logger.info(mensaje)
        if not getattr(sys, 'frozen', False):
            print(mensaje)
        sys.exit(0)
