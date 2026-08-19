"""
Script de utilidad para migrar datos y administrar la base de datos
"""
from src import database as db
import os
import json

def migrate_from_json_files():
    """Migra datos desde archivos JSON a la base de datos"""
    print("=" * 60)
    print("MIGRACIÓN DE DATOS A BASE DE DATOS SQLite")
    print("=" * 60)
    
    # Inicializar base de datos
    print("\n1. Inicializando base de datos...")
    db.init_database()
    
    # Migrar desde archivos JSON
    print("\n2. Migrando datos desde archivos JSON...")
    db.migrate_from_json()
    
    # Mostrar estadísticas
    print("\n3. Estadísticas de la base de datos:")
    stats = db.get_database_stats()
    print(f"   - Personas: {stats['personas_count']}")
    print(f"   - Reemplazos de descripciones: {stats['replacements_count']}")
    print(f"   - PDFs guardados: {stats['pdfs_count']}")
    print(f"   - Transacciones totales: {stats['transactions_count']}")
    
    print("\n✅ Migración completada exitosamente!")
    print(f"📁 Base de datos creada en: {db.DATABASE_FILE}")
    print("=" * 60)

def show_database_info():
    """Muestra información sobre la base de datos"""
    print("=" * 60)
    print("INFORMACIÓN DE BASE DE DATOS")
    print("=" * 60)
    
    if not os.path.exists(db.DATABASE_FILE):
        print("\n⚠️ La base de datos no existe aún.")
        print("   Ejecuta la migración primero con: python migrate_db.py migrate")
        return
    
    stats = db.get_database_stats()
    
    print(f"\n📊 Estadísticas generales:")
    print(f"   Archivo: {db.DATABASE_FILE}")
    print(f"   Tamaño: {os.path.getsize(db.DATABASE_FILE) / 1024:.2f} KB")
    print(f"\n📈 Registros:")
    print(f"   - Personas: {stats['personas_count']}")
    print(f"   - Reemplazos de descripciones: {stats['replacements_count']}")
    print(f"   - PDFs guardados: {stats['pdfs_count']}")
    print(f"   - Transacciones totales: {stats['transactions_count']}")
    
    # Mostrar personas
    print(f"\n👥 Personas configuradas:")
    personas = db.get_all_personas()
    for persona in personas:
        print(f"   {persona['icono']} {persona['nombre']} (ID: {persona['id']}, Color: {persona['color']})")
    
    # Mostrar algunos reemplazos
    print(f"\n📝 Reemplazos de descripciones:")
    replacements = db.get_all_description_replacements()
    if replacements:
        count = 0
        for original, nuevo in replacements.items():
            print(f"   '{original}' → '{nuevo}'")
            count += 1
            if count >= 5:
                remaining = len(replacements) - 5
                if remaining > 0:
                    print(f"   ... y {remaining} más")
                break
    else:
        print("   (ninguno)")
    
    print("=" * 60)

def cleanup_old_data(days=90):
    """Limpia datos antiguos de la base de datos"""
    print("=" * 60)
    print(f"LIMPIEZA DE DATOS ANTIGUOS (más de {days} días)")
    print("=" * 60)
    
    if not os.path.exists(db.DATABASE_FILE):
        print("\n⚠️ La base de datos no existe.")
        return
    
    print(f"\n🗑️ Eliminando PDFs sin acceso en {days} días...")
    deleted = db.clean_old_pdfs(days)
    
    print(f"\n✅ Limpieza completada!")
    print(f"   - PDFs eliminados: {deleted}")
    print("=" * 60)

def export_to_json():
    """Exporta datos de la BD a archivos JSON (backup)"""
    print("=" * 60)
    print("EXPORTAR DATOS A JSON (BACKUP)")
    print("=" * 60)
    
    if not os.path.exists(db.DATABASE_FILE):
        print("\n⚠️ La base de datos no existe.")
        return
    
    # Exportar personas
    personas = db.get_all_personas()
    with open('personas_backup.json', 'w', encoding='utf-8') as f:
        json.dump(personas, f, ensure_ascii=False, indent=2)
    print(f"\n✅ Personas exportadas a: personas_backup.json ({len(personas)} registros)")
    
    # Exportar reemplazos
    replacements = db.get_all_description_replacements()
    with open('description_replacements_backup.json', 'w', encoding='utf-8') as f:
        json.dump({'replacements': replacements}, f, ensure_ascii=False, indent=2)
    print(f"✅ Reemplazos exportados a: description_replacements_backup.json ({len(replacements)} registros)")
    
    print("\n" + "=" * 60)

if __name__ == '__main__':
    import sys
    
    if len(sys.argv) < 2:
        print("\nUso:")
        print("  python migrate_db.py migrate    - Migrar datos desde JSON a BD")
        print("  python migrate_db.py info       - Mostrar información de la BD")
        print("  python migrate_db.py cleanup    - Limpiar datos antiguos (90 días)")
        print("  python migrate_db.py export     - Exportar datos a JSON (backup)")
        sys.exit(1)
    
    command = sys.argv[1].lower()
    
    if command == 'migrate':
        migrate_from_json_files()
    elif command == 'info':
        show_database_info()
    elif command == 'cleanup':
        days = int(sys.argv[2]) if len(sys.argv) > 2 else 90
        cleanup_old_data(days)
    elif command == 'export':
        export_to_json()
    else:
        print(f"\n❌ Comando desconocido: {command}")
        print("\nComandos disponibles: migrate, info, cleanup, export")
