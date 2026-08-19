"""
Generación de imágenes de pago (JPG 1080x1080) para cada persona.
"""
import io
from datetime import datetime

from PIL import Image, ImageDraw, ImageFont


def generar_imagen_pago(nombre, monto, color='#1e88e5'):
    """
    Genera una imagen JPG de 1080x1080 con el resumen de pago
    """
    # Dimensiones
    width, height = 1080, 1080

    # Crear imagen con fondo degradado
    img = Image.new('RGB', (width, height), color='white')
    draw = ImageDraw.Draw(img)

    # Convertir color hex a RGB
    color_rgb = hex_to_rgb(color)
    color_claro = tuple(min(255, c + 50) for c in color_rgb)

    # Crear degradado de fondo
    for y in range(height):
        ratio = y / height
        r = int(color_rgb[0] * (1 - ratio) + color_claro[0] * ratio)
        g = int(color_rgb[1] * (1 - ratio) + color_claro[1] * ratio)
        b = int(color_rgb[2] * (1 - ratio) + color_claro[2] * ratio)
        draw.line([(0, y), (width, y)], fill=(r, g, b))

    # Intentar cargar fuentes del sistema, si no, usar la por defecto
    try:
        font_titulo = ImageFont.truetype("arial.ttf", 60)
        font_subtitulo = ImageFont.truetype("arial.ttf", 80)
        font_nombre = ImageFont.truetype("arialbd.ttf", 100)
        font_monto = ImageFont.truetype("arialbd.ttf", 140)
        font_fecha = ImageFont.truetype("arial.ttf", 40)
    except Exception:
        # Si no encuentra las fuentes, usar la por defecto
        font_titulo = ImageFont.load_default()
        font_subtitulo = ImageFont.load_default()
        font_nombre = ImageFont.load_default()
        font_monto = ImageFont.load_default()
        font_fecha = ImageFont.load_default()

    # Colores de texto
    color_texto = (255, 255, 255)  # Blanco
    color_sombra = (0, 0, 0, 100)  # Negro semi-transparente

    # Posiciones
    y_offset = 150

    # Título "Resumen de Pago"
    titulo = "RESUMEN DE PAGO"
    bbox_titulo = draw.textbbox((0, 0), titulo, font=font_titulo)
    titulo_width = bbox_titulo[2] - bbox_titulo[0]
    titulo_x = (width - titulo_width) // 2
    draw.text((titulo_x, y_offset), titulo, fill=color_texto, font=font_titulo)

    y_offset += 150

    # Línea decorativa
    draw.rectangle([(width//4, y_offset), (3*width//4, y_offset + 5)], fill=color_texto)

    y_offset += 80

    # "Para:"
    subtitulo = "Para:"
    bbox_subtitulo = draw.textbbox((0, 0), subtitulo, font=font_subtitulo)
    subtitulo_width = bbox_subtitulo[2] - bbox_subtitulo[0]
    subtitulo_x = (width - subtitulo_width) // 2
    draw.text((subtitulo_x, y_offset), subtitulo, fill=color_texto, font=font_subtitulo)

    y_offset += 120

    # Nombre de la persona (más grande)
    bbox_nombre = draw.textbbox((0, 0), nombre, font=font_nombre)
    nombre_width = bbox_nombre[2] - bbox_nombre[0]
    nombre_x = (width - nombre_width) // 2
    # Sombra del nombre
    draw.text((nombre_x + 3, y_offset + 3), nombre, fill=(0, 0, 0, 150), font=font_nombre)
    # Nombre
    draw.text((nombre_x, y_offset), nombre, fill=color_texto, font=font_nombre)

    y_offset += 200

    # Rectángulo oscuro semi-transparente para el monto (mejor contraste)
    rect_padding = 40
    rect_y = y_offset - 30
    rect_height = 220

    # Crear una capa oscura semi-transparente
    overlay = Image.new('RGBA', (width, height), (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)
    overlay_draw.rectangle(
        [(rect_padding, rect_y), (width - rect_padding, rect_y + rect_height)],
        fill=(0, 0, 0, 120)  # Negro semi-transparente
    )
    # Combinar la capa oscura con la imagen base
    img = Image.alpha_composite(img.convert('RGBA'), overlay).convert('RGB')
    draw = ImageDraw.Draw(img)

    # Borde del rectángulo
    draw.rectangle(
        [(rect_padding, rect_y), (width - rect_padding, rect_y + rect_height)],
        outline=color_texto,
        width=6
    )

    y_offset += 30

    # Monto a pagar (EL MÁS PROMINENTE) - Ahora con mejor contraste
    monto_texto = f"S/ {monto:,.2f}"
    bbox_monto = draw.textbbox((0, 0), monto_texto, font=font_monto)
    monto_width = bbox_monto[2] - bbox_monto[0]
    monto_x = (width - monto_width) // 2
    # Sombra del monto más pronunciada
    draw.text((monto_x + 5, y_offset + 5), monto_texto, fill=(0, 0, 0), font=font_monto)
    # Monto en blanco brillante
    draw.text((monto_x, y_offset), monto_texto, fill=(255, 255, 255), font=font_monto)

    y_offset += 250

    # Fecha de generación
    fecha_texto = f"Generado el: {datetime.now().strftime('%d/%m/%Y %H:%M')}"
    bbox_fecha = draw.textbbox((0, 0), fecha_texto, font=font_fecha)
    fecha_width = bbox_fecha[2] - bbox_fecha[0]
    fecha_x = (width - fecha_width) // 2
    draw.text((fecha_x, y_offset), fecha_texto, fill=color_texto, font=font_fecha)

    # Guardar en bytes
    img_bytes_io = io.BytesIO()
    img.save(img_bytes_io, format='JPEG', quality=95)
    img_bytes = img_bytes_io.getvalue()

    return img_bytes


def hex_to_rgb(hex_color):
    """Convierte color hexadecimal a RGB"""
    hex_color = hex_color.lstrip('#')
    return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
