"""
Lógica de parsing de estados de cuenta BBVA en PDF.

Extrae información general, transacciones (cuotas y compras directas)
y el resumen financiero de los distintos formatos de estado de cuenta BBVA.
"""
import re
from datetime import datetime

import pdfplumber

from config import settings
from src import database as db

CONCEPTOS_EXCLUIDOS = settings.CONCEPTOS_EXCLUIDOS
DESCRIPTION_EXCLUDE_KEYWORDS = settings.DESCRIPTION_EXCLUDE_KEYWORDS
PDF_UNLOCK_PASSWORD = settings.PDF_UNLOCK_PASSWORD

SPANISH_MONTHS = {
    'enero': 1,
    'febrero': 2,
    'marzo': 3,
    'abril': 4,
    'mayo': 5,
    'junio': 6,
    'julio': 7,
    'agosto': 8,
    'septiembre': 9,
    'setiembre': 9,
    'octubre': 10,
    'noviembre': 11,
    'diciembre': 12
}


def is_password_protected_pdf_error(error):
    """Detecta errores comunes relacionados con PDFs protegidos por contraseña."""
    error_text = f"{type(error).__name__} {repr(error)} {str(error)}".lower()
    password_error_keywords = [
        'password',
        'encrypted',
        'decrypt',
        'encryption',
        'authenticate',
        'passphrase',
        'pdfpasswordincorrect',
        'file has not been decrypted'
    ]
    return any(keyword in error_text for keyword in password_error_keywords)


def _extract_bbva_data_from_open_pdf(pdf):
    """Procesa un PDF ya abierto y devuelve la estructura de datos normalizada."""
    data = {
        'info_general': {},
        'transacciones': [],
        'resumen': {}
    }

    all_text = ""

    # Extraer texto de todas las páginas
    for page_num, page in enumerate(pdf.pages, 1):
        text = page.extract_text()
        if text:
            all_text += text + "\n"

            # Extraer información general de la primera página
            if page_num == 1:
                data['info_general'] = extract_general_info(text)

            # Extraer transacciones
            transactions = extract_transactions(text)
            for trans in transactions:
                trans['pagina'] = page_num
                data['transacciones'].append(trans)

    # Extraer resumen financiero
    data['resumen'] = extract_summary(all_text)

    if not data['info_general']:
        data['info_general'] = extract_general_info(all_text)
    else:
        full_info = extract_general_info(all_text)
        for key, value in full_info.items():
            if key not in data['info_general'] and value:
                data['info_general'][key] = value

    # Complementar info_general con datos que pueden estar en otras páginas
    # (como el periodo de facturación que suele estar en la página 2)
    if 'periodo' not in data['info_general']:
        periodo_match = re.search(
            r'PERIODO\s+DE\s+FACTURACION\s+DEL[:\s]+(\d{2}/\d{2}/\d{4})\s+AL[:\s]+(\d{2}/\d{2}/\d{4})',
            all_text, re.IGNORECASE
        )
        if periodo_match:
            data['info_general']['periodo'] = f"{periodo_match.group(1)} - {periodo_match.group(2)}"
        else:
            periodo_match_new = re.search(
                r'del\s+(\d{2}/\d{2})\s+al\s+cierre\s+de\s+(\d{2}/\d{2})',
                all_text,
                re.IGNORECASE
            )
            if periodo_match_new:
                data['info_general']['periodo'] = f"{periodo_match_new.group(1)} - {periodo_match_new.group(2)}"

    # Eliminar duplicados de todas las transacciones recolectadas
    data['transacciones'] = remove_duplicate_transactions(data['transacciones'])

    # Aplicar reemplazos de descripciones
    data['transacciones'] = apply_description_replacements(data['transacciones'])

    # Usar el pago_total_mes extraído del PDF si está disponible
    # Esto es más preciso que calcularlo sumando transacciones
    if 'pago_total_mes' in data['resumen']:
        data['resumen']['total_pagar_mes'] = data['resumen']['pago_total_mes']
    else:
        # Fallback: calcular el total sumando transacciones + seguro
        total_pagar_mes = sum(trans['monto'] for trans in data['transacciones'])

        # Agregar el seguro de desgravamen solo si no está ya incluido en las transacciones
        # y si existe en el resumen
        seguro_desgravamen = data['resumen'].get('seguro_desgravamen', 0)
        if seguro_desgravamen:
            total_pagar_mes += seguro_desgravamen

        data['resumen']['total_pagar_mes'] = total_pagar_mes

    # Calcular y agregar información de verificación
    total_transacciones = sum(trans['monto'] for trans in data['transacciones'])
    data['resumen']['total_transacciones_calculado'] = total_transacciones

    # Agregar conteo de tipos de transacciones
    compras_directas = [t for t in data['transacciones'] if t.get('es_compra_directa', False)]
    cuotas_mensuales = [t for t in data['transacciones'] if not t.get('es_compra_directa', False)]

    data['resumen']['info_transacciones'] = {
        'cuotas_mensuales': len(cuotas_mensuales),
        'compras_directas': len(compras_directas),
        'total': len(data['transacciones'])
    }

    return data


def extract_bbva_data(pdf_path):
    """
    Extrae información del estado de cuenta BBVA
    """
    try:
        with pdfplumber.open(pdf_path) as pdf:
            return _extract_bbva_data_from_open_pdf(pdf)

    except Exception as first_error:
        if not is_password_protected_pdf_error(first_error):
            print(f"Error al procesar PDF: {str(first_error)}")
            raise

        if not PDF_UNLOCK_PASSWORD:
            raise ValueError(
                'El PDF está protegido y no se configuró PDF_UNLOCK_PASSWORD. '
                'Configura la contraseña en el archivo .env.'
            ) from first_error

        last_encrypted_error = None
        for password_candidate in (PDF_UNLOCK_PASSWORD, PDF_UNLOCK_PASSWORD.encode('utf-8')):
            try:
                with pdfplumber.open(pdf_path, password=password_candidate) as pdf:
                    return _extract_bbva_data_from_open_pdf(pdf)
            except Exception as encrypted_error:
                last_encrypted_error = encrypted_error

        print(f"Error al procesar PDF: {str(last_encrypted_error)}")
        if last_encrypted_error and is_password_protected_pdf_error(last_encrypted_error):
            raise ValueError('No se pudo desbloquear el PDF con la contraseña configurada.') from last_encrypted_error
        if last_encrypted_error:
            raise last_encrypted_error
        raise ValueError('No se pudo desbloquear el PDF con la contraseña configurada.')


def remove_duplicate_transactions(transactions):
    """
    Elimina transacciones duplicadas de la lista.
    Dos transacciones son duplicadas si tienen la misma fecha, descripción y monto.
    """
    seen = set()
    unique_transactions = []

    for trans in transactions:
        # Crear una clave única basada en fecha, descripción y monto
        # Redondeamos el monto a 2 decimales para evitar problemas de precisión
        key = (trans['fecha'], trans['descripcion'].strip(), round(trans['monto'], 2))

        if key not in seen:
            seen.add(key)
            unique_transactions.append(trans)

    return unique_transactions


def normalize_statement_date(date_text):
    """Normaliza fechas del estado BBVA para mantener formato consistente de salida."""
    if not date_text:
        return date_text

    normalized = date_text.strip().replace('-', '/')
    slash_match = re.match(r'^(\d{1,2})/(\d{1,2})/(\d{4})$', normalized)
    if slash_match:
        day = int(slash_match.group(1))
        month = int(slash_match.group(2))
        year = int(slash_match.group(3))
        return f"{day:02d}/{month:02d}/{year}"

    return normalized


def parse_spanish_textual_date(day_text, month_text, year_text):
    """Convierte fechas textuales en español a DD/MM/YYYY."""
    month_number = SPANISH_MONTHS.get(month_text.lower())
    if not month_number:
        return None

    day = int(day_text)
    year = int(year_text)
    return f"{day:02d}/{month_number:02d}/{year}"


def infer_payment_year(reference_date, payment_month):
    """Infiere año de pago a partir del mes de cierre cuando no viene explícito."""
    if not reference_date:
        return datetime.now().year

    reference_match = re.match(r'^(\d{2})/(\d{2})/(\d{4})$', reference_date)
    if not reference_match:
        return datetime.now().year

    reference_month = int(reference_match.group(2))
    reference_year = int(reference_match.group(3))
    if payment_month < reference_month:
        return reference_year + 1
    return reference_year


def clean_narrative_description(text):
    """Limpia descripciones extraídas del formato narrativo de BBVA."""
    cleaned = text.strip()
    cleaned = re.sub(r'\s+', ' ', cleaned)
    cleaned = re.sub(r'S/', '', cleaned)
    cleaned = re.sub(r'\$0\b', '', cleaned)
    cleaned = re.sub(r'\b\d{1,2}[/-]\d{1,2}[/-]\d{4}\b', '', cleaned)
    cleaned = re.sub(r'\b\d{1,2}\s*/\s*\d{1,2}\b', '', cleaned)
    cleaned = re.sub(r'\b\d+%\b', '', cleaned)
    cleaned = re.sub(r'\b\d{1,3}(?:,\d{3})*\.\d{2}\b', '', cleaned)
    cleaned = re.sub(r'\bPERU\b', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip(' -')
    return cleaned


def extract_narrative_direct_purchases(lines):
    """Extrae compras directas del formato narrativo BBVA."""
    purchases = []
    start_idx = None
    end_idx = None

    for idx, line in enumerate(lines):
        if re.search(r'compras\s+sin\s+cuotas.*pagos\s+realizados', line, re.IGNORECASE):
            start_idx = idx
            continue
        if start_idx is not None and re.search(r'compras\s+en\s+cuotas.*a\s+pagar\s+este\s+per[íi]odo', line, re.IGNORECASE):
            end_idx = idx
            break

    if start_idx is None:
        return purchases

    if end_idx is None:
        end_idx = len(lines)

    for idx in range(start_idx + 1, end_idx):
        line = lines[idx].strip()
        if not re.search(r'^\d{1,2}[/-]\d{1,2}[/-]\d{4}\b', line):
            continue

        next_line = lines[idx + 1].strip() if idx + 1 < len(lines) else ''
        if re.search(r'\bCUOTAS?\b', line, re.IGNORECASE) or re.fullmatch(r'CUOTAS?', next_line, re.IGNORECASE):
            continue

        amount_match = re.search(r'S/\s*(-?\d{1,3}(?:,\d{3})*\.\d{2})', line)
        if not amount_match:
            continue

        amount = float(amount_match.group(1).replace(',', ''))
        if amount <= 0:
            continue

        description_match = re.search(r'^\d{1,2}[/-]\d{1,2}[/-]\d{4}\s+(.+?)\s+(?:PERU|S/)', line)
        if description_match:
            description = description_match.group(1)
        else:
            previous_line = lines[idx - 1].strip() if idx > 0 else ''
            if previous_line.startswith('(C)'):
                description = previous_line.replace('(C)', '').replace('CUOTAS', '').strip()
            else:
                description = line

        description = clean_narrative_description(description)
        if not description or description.upper() in {'CUOTAS', 'PERU'}:
            fallback_description = ''
            for lookback in range(idx - 1, max(-1, idx - 6), -1):
                candidate = lines[lookback].strip()
                if not candidate:
                    continue
                if re.search(r'Fecha\s+Descripci[óo]n', candidate, re.IGNORECASE):
                    continue
                if re.search(r'compras\s+sin\s+cuotas', candidate, re.IGNORECASE):
                    continue
                if candidate.upper() == 'CUOTAS':
                    continue
                if '(C)' in candidate:
                    fallback_description = candidate.replace('(C)', '').strip()
                    break
                if not re.search(r'^\d{1,2}[/-]\d{1,2}[/-]\d{4}', candidate):
                    fallback_description = candidate
                    break

            description = clean_narrative_description(fallback_description)
        if not description:
            continue

        description_upper = description.upper()
        if any(keyword in description_upper for keyword in DESCRIPTION_EXCLUDE_KEYWORDS):
            continue
        if any(concepto in description_upper for concepto in CONCEPTOS_EXCLUIDOS):
            continue

        date_text = re.match(r'^(\d{1,2}[/-]\d{1,2}[/-]\d{4})', line).group(1)
        purchases.append({
            'fecha': normalize_statement_date(date_text),
            'descripcion': description,
            'monto': amount,
            'tipo': 'cargo',
            'cuota_info': None,
            'asignado_a': 'sin_asignar',
            'es_compra_directa': True
        })

    return purchases


def extract_narrative_installments(lines):
    """Extrae compras en cuotas del formato narrativo BBVA."""
    installments = []
    start_idx = None
    end_idx = None

    for idx, line in enumerate(lines):
        if re.search(r'compras\s+en\s+cuotas.*a\s+pagar\s+este\s+per[íi]odo', line, re.IGNORECASE):
            start_idx = idx
            continue
        if start_idx is not None and re.search(r'^Subtotal\s+S/', line, re.IGNORECASE):
            end_idx = idx
            break

    if start_idx is None:
        return installments

    if end_idx is None:
        end_idx = len(lines)

    section_lines = lines[start_idx + 1:end_idx]
    return parse_narrative_installment_rows(section_lines)


def parse_narrative_installment_rows(section_lines):
    """Parsea filas de cuotas narrativas BBVA desde un bloque de líneas."""
    installments = []
    for idx, line in enumerate(section_lines):
        line = line.strip()
        if not re.search(r'^\d{1,2}[/-]\d{1,2}[/-]\d{4}\b', line):
            continue
        if not re.search(r'\b\d+\s*/\s*\d+\b', line):
            continue

        previous_line = section_lines[idx - 1].strip() if idx > 0 else ''
        next_line = section_lines[idx + 1].strip() if idx + 1 < len(section_lines) else ''
        context = f"{previous_line} {line} {next_line}".strip()

        cuota_match = re.search(r'\b(\d{1,2})\s*/\s*(\d{1,2})(?!/\d{4})\b', line)
        if not cuota_match:
            cuota_match = re.search(r'\b(\d{1,2})\s*/\s*(\d{1,2})(?!/\d{4})\b', context)
        if not cuota_match:
            continue

        cuota_actual = int(cuota_match.group(1))
        cuota_total = int(cuota_match.group(2))

        amount_matches_line = re.findall(r'S/\s*(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)', line)
        amount_matches_context = re.findall(r'S/\s*(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)', context)

        if amount_matches_line:
            monthly_amount = float(amount_matches_line[-1].replace(',', ''))
        elif amount_matches_context:
            monthly_amount = float(amount_matches_context[-1].replace(',', ''))
        else:
            continue

        description_match = re.search(
            r'^\d{1,2}[/-]\d{1,2}[/-]\d{4}\s+(.+?)\s+(?:S/|\d+\s*/\s*\d+)',
            line
        )
        if description_match:
            description = description_match.group(1).strip()
        else:
            description = f"{previous_line} {next_line}".strip()

        if re.match(r'^S/\s*\d', description) or re.match(r'^\d+\s*/\s*\d+', description):
            description = f"{previous_line} {next_line}".strip()

        if re.fullmatch(r'S/?', description) or description.upper() in {'S/', 'S', '0%'}:
            description = f"{previous_line} {next_line}".strip()

        if not re.search(r'[A-Za-zÁÉÍÓÚáéíóúÑñ*]', description):
            description = f"{previous_line} {next_line}".strip()

        date_text = re.match(r'^(\d{1,2}[/-]\d{1,2}[/-]\d{4})', line).group(1)

        description = clean_narrative_description(description)
        if not description:
            continue

        description_upper = description.upper()
        if any(keyword in description_upper for keyword in DESCRIPTION_EXCLUDE_KEYWORDS):
            continue
        if any(concepto in description_upper for concepto in CONCEPTOS_EXCLUIDOS):
            continue

        installments.append({
            'fecha': normalize_statement_date(date_text),
            'descripcion': description,
            'monto': abs(monthly_amount),
            'tipo': 'cargo',
            'cuota_info': f"{cuota_actual} de {cuota_total}",
            'asignado_a': 'sin_asignar',
            'es_compra_directa': False
        })

    return installments


def extract_narrative_installments_continuation(lines):
    """Extrae cuotas de páginas continuadas del formato narrativo sin encabezado principal."""
    subtotal_idx = None
    for idx, line in enumerate(lines):
        if re.search(r'^Subtotal\s+S/', line, re.IGNORECASE):
            subtotal_idx = idx
            break

    if subtotal_idx is None:
        return []

    candidate_lines = lines[:subtotal_idx]
    has_installment_rows = any(
        re.search(r'^\d{1,2}[/-]\d{1,2}[/-]\d{4}\b', ln.strip()) and re.search(r'\b\d+\s*/\s*\d+\b', ln)
        for ln in candidate_lines
    )
    if not has_installment_rows:
        return []

    return parse_narrative_installment_rows(candidate_lines)


def extract_general_info(text):
    """
    Extrae información general del estado de cuenta
    """
    info = {}

    # Buscar número de tarjeta
    # Formato: 123456******1234 o similar
    tarjeta_patterns = [
        r'([4-6]\d{3}-\d{2}\*{2}-\*{4}-\d{4})',
        r'N[°º]\s*DE\s*TARJETA[:\s]+([\d\-\*]+\d{4})',  # 1234-56**-****-1234
        r'(\d{6}\*+\d{4})',  # 123456******1234
        r'(?:Tarjeta|Card).*?(\d{4})'  # Últimos 4 dígitos
    ]
    for pattern in tarjeta_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            tarjeta = match.group(1)
            if '*' in tarjeta:
                info['tarjeta'] = tarjeta
            else:
                info['tarjeta'] = f"****{tarjeta}"
            break

    # Buscar titular/nombre de usuario
    # Formato BBVA: "Señor: ... APELLIDO1 APELLIDO2 NOMBRE1 NOMBRE2 Tarjeta Titular"
    # O en RESUMEN: "123456******1234 NOMBRE APELLIDO 33,500.00"
    nombre_patterns = [
        # Formato narrativo: nombre en línea posterior al número de tarjeta
        r'\d{4}-\d{2}\*{2}-\*{4}-\d{4}\s*\n\s*([A-ZÁÉÍÓÚÑ\s]+?)\s*\n',
        # Formato nuevo: "Señor:" en una línea y nombre en la siguiente
        r'Señor:\s*\n\s*([A-ZÁÉÍÓÚÑ\s]+?)\s*(?:\n|$)',
        # Patrón para "Señor: " seguido del nombre hasta "Tarjeta Titular"
        r'Señor[:\s]+(?:Tipo de Tarjeta[^\n]*\n)?([A-ZÁÉÍÓÚÑ\s]+?)\s+Tarjeta\s+Titular',
        # Patrón para RESUMEN MENSUAL: tarjeta seguida de nombre
        r'\d{6}\*+\d{4}\s+([A-ZÁÉÍÓÚÑ\s]+?)\s+\d{1,3}(?:,\d{3})*\.\d{2}',
        # Patrón legacy
        r'NOMBRE\s+USUARIO\s+([A-ZÁÉÍÓÚÑ\s]+?)(?:\s+LIMITE|$)'
    ]
    for pattern in nombre_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            nombre = match.group(1).strip()
            # Limpiar el nombre
            nombre = re.sub(r'\s+', ' ', nombre)
            if len(nombre) > 3:  # Validar que sea un nombre real
                info['titular'] = nombre
                break

    # Buscar fecha de cierre
    cierre_patterns = [
        r'cierre\s+de\s+(\d{2}/\d{2})',
        r'al\s+(\d{1,2}\s+de\s+[a-záéíóúñ]+\s+de\s+\d{4})',
        r'Fecha\s+de\s+Cierre\s+(\d{2}/\d{2}/\d{4})',
        r'(?:Periodo|Período|Fecha de Corte)[:|\s]+(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})'
    ]
    for pattern in cierre_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            raw_date = match.group(1).strip()
            textual_match = re.match(r'^(\d{1,2})\s+de\s+([a-záéíóúñ]+)\s+de\s+(\d{4})$', raw_date, re.IGNORECASE)
            if textual_match:
                parsed_date = parse_spanish_textual_date(
                    textual_match.group(1),
                    textual_match.group(2),
                    textual_match.group(3)
                )
                if parsed_date:
                    info['fecha_cierre'] = parsed_date
                    break

            info['fecha_cierre'] = normalize_statement_date(raw_date)
            break

    # Buscar último día de pago
    pago_patterns = [
        r'[ÚU]ltimo\s+d[ií]a\s+de\s+Pago\s+(\d{2}/\d{2}/\d{4})',
        r'(?:Fecha de Pago|Pago hasta|Pagar hasta)[:|\s]+(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})',
        r'([Ll]unes|[Mm]artes|[Mm]i[ée]rcoles|[Jj]ueves|[Vv]iernes|[Ss][áa]bado|[Dd]omingo)\s+(\d{1,2})\s+de\s+([a-záéíóúñ]+)'
    ]
    for pattern in pago_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            if match.lastindex == 3:
                payment_month = SPANISH_MONTHS.get(match.group(3).lower())
                if payment_month:
                    inferred_year = infer_payment_year(info.get('fecha_cierre'), payment_month)
                    parsed_date = parse_spanish_textual_date(match.group(2), match.group(3), str(inferred_year))
                    if parsed_date:
                        info['fecha_pago'] = parsed_date
                        break
            else:
                info['fecha_pago'] = normalize_statement_date(match.group(1))
                break

    # Buscar periodo de facturación
    periodo_match_textual = re.search(
        r'per[ií]odo\s+del\s+(\d{1,2})\s+de\s+([a-záéíóúñ]+)\s+de\s+(\d{4})\s+al\s+(\d{1,2})\s+de\s+([a-záéíóúñ]+)\s+de\s+(\d{4})',
        text,
        re.IGNORECASE
    )
    if periodo_match_textual:
        start_date = parse_spanish_textual_date(
            periodo_match_textual.group(1),
            periodo_match_textual.group(2),
            periodo_match_textual.group(3)
        )
        end_date = parse_spanish_textual_date(
            periodo_match_textual.group(4),
            periodo_match_textual.group(5),
            periodo_match_textual.group(6)
        )
        if start_date and end_date:
            info['periodo'] = f"{start_date} - {end_date}"
            if 'fecha_cierre' not in info:
                info['fecha_cierre'] = end_date

    if 'periodo' not in info:
        periodo_match = re.search(r'PERIODO\s+DE\s+FACTURACION\s+DEL[:\s]+(\d{2}/\d{2}/\d{4})\s+AL[:\s]+(\d{2}/\d{2}/\d{4})', text, re.IGNORECASE)
        if periodo_match:
            info['periodo'] = f"{periodo_match.group(1)} - {periodo_match.group(2)}"
        else:
            periodo_match_new = re.search(r'del\s+(\d{2}/\d{2})\s+al\s+cierre\s+de\s+(\d{2}/\d{2})', text, re.IGNORECASE)
            if periodo_match_new:
                info['periodo'] = f"{periodo_match_new.group(1)} - {periodo_match_new.group(2)}"

    # Fallback de fecha de cierre con periodo si aún no existe
    if 'fecha_cierre' not in info and 'periodo' in info:
        period_dates = re.findall(r'(\d{2}/\d{2}/\d{4})', info['periodo'])
        if len(period_dates) == 2:
            info['fecha_cierre'] = period_dates[1]

    # Buscar oficina
    # Formato: "Oficina OF.PUENTE PIEDRA" o "Oficina NOMBRE"
    oficina_patterns = [
        r'Oficina\s+(OF\.?[A-ZÁÉÍÓÚÑ\s\-\.]+?)(?:\s+Cuenta|\s+Fecha|$)',
        r'Oficina\s+([A-ZÁÉÍÓÚÑ\s\-]+?)(?:\s+Cuenta|\s+Fecha|$)'
    ]
    for pattern in oficina_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            oficina = match.group(1).strip()
            # Limpiar "OF." si está presente
            if oficina.upper().startswith('OF.'):
                oficina = oficina[3:].strip()
            info['oficina'] = oficina
            break

    return info


def extract_direct_purchases(text):
    """
    Extrae compras directas (sin cuotas) de la sección de operaciones del mes.
    Estas son compras que se pagan completas en el mes actual y NO aparecen
    en la sección "DETALLE CUOTAS DEL MES".

    Formatos en el PDF:
    - Cuotas: DD/MM/YYYY 1234 (C) DESCRIPCION S/ MONTO X CU 0.00 0.00  <- Ignorar
    - Directa: DD/MM/YYYY 1234 (C) DESCRIPCION MONTO 0.00              <- Capturar
    """
    direct_purchases = []

    lines = text.split('\n')

    # Buscar la sección de operaciones (antes de DETALLE CUOTAS DEL MES)
    operations_text = ""
    for line in lines:
        # Detenerse cuando llegamos a DETALLE CUOTAS DEL MES
        if re.search(r'DETALLE\s+CUOTAS\s+DEL\s+MES', line, re.IGNORECASE):
            break
        operations_text += line + "\n"

    for line in operations_text.split('\n'):
        # Saltar líneas que tienen indicador de cuotas (S/ MONTO X CU)
        if re.search(r'S/\s*[\d,]+\.?\d*\s+\d+\s+CU', line, re.IGNORECASE):
            continue

        # Patrón para compras directas: fecha, tarjeta, (C), descripción, monto, 0.00
        # Ejemplo: 02/11/2025 1234 (C) MP *ALIEXPRESS 26.36 0.00
        # El monto de soles está antes del 0.00 de dólares
        pattern = r'(\d{2}/\d{2}/\d{4})\s+\d{4}\s+\(C\)\s+(.+?)\s+(\d+\.\d{2})\s+0\.00\s*$'

        match = re.search(pattern, line)
        if match:
            fecha = match.group(1)
            descripcion = match.group(2).strip()
            monto_str = match.group(3)

            # Excluir conceptos que no son compras
            descripcion_upper = descripcion.upper()
            if any(concepto in descripcion_upper for concepto in CONCEPTOS_EXCLUIDOS):
                continue

            try:
                monto = float(monto_str)
            except ValueError:
                continue

            # Solo incluir si el monto es mayor a 0
            if monto > 0:
                direct_purchases.append({
                    'fecha': fecha,
                    'descripcion': descripcion,
                    'monto': abs(monto),
                    'tipo': 'cargo',
                    'cuota_info': None,  # Compras directas no tienen cuotas
                    'asignado_a': 'sin_asignar',
                    'es_compra_directa': True
                })

    return direct_purchases


def extract_transactions(text):
    """
    Extrae las transacciones del texto del estado de cuenta BBVA.
    Combina:
    1. Cuotas mensuales de compras diferidas (de "DETALLE CUOTAS DEL MES")
    2. Compras directas sin cuotas (de la sección de operaciones)
    """
    transactions = []

    if re.search(r'compras\s+en\s+cuotas.*a\s+pagar\s+este\s+per[íi]odo', text, re.IGNORECASE):
        lines = text.split('\n')
        narrative_transactions = []
        narrative_transactions.extend(extract_narrative_installments(lines))
        narrative_transactions.extend(extract_narrative_direct_purchases(lines))
        return narrative_transactions

    if re.search(r'^Subtotal\s+S/', text, re.IGNORECASE | re.MULTILINE):
        continuation_transactions = extract_narrative_installments_continuation(text.split('\n'))
        if continuation_transactions:
            return continuation_transactions

    # Formato nuevo BBVA (2026+): las transacciones útiles del mes están en las
    # secciones de compras en cuotas y pago sin intereses.
    if re.search(r'DETALLE\s+DE\s+TU\s+PAGO\s+DEL\s+MES', text, re.IGNORECASE):
        for line in text.split('\n'):
            line = line.strip()
            if not line:
                continue

            # Ejemplo:
            # 20-01-2026 MDOPAGO*MDOPAGO MERCAD 1,249.00 1 / 12 0.00% 104.08 0.00 104.08 ---
            monthly_installment_pattern = (
                r'^(\d{2}[-/]\d{2}[-/]\d{4})\s+(.+?)\s+'
                r'(\d{1,3}(?:,\d{3})*\.\d{2})\s+'
                r'(\d+)\s*/\s*(\d+)\s+'
                r'\d+\.\d{2}%\s+'
                r'\d+\.\d{2}\s+\d+\.\d{2}\s+'
                r'(\d+\.\d{2})\s+(?:---|\d+\.\d{2})\s*$'
            )
            match = re.match(monthly_installment_pattern, line)
            if not match:
                continue

            fecha = normalize_statement_date(match.group(1))
            descripcion = re.sub(r'\s+', ' ', match.group(2).strip())
            cuota_actual = int(match.group(4))
            cuota_total = int(match.group(5))
            cuota_info = f"{cuota_actual} de {cuota_total}"

            if any(keyword in descripcion.upper() for keyword in DESCRIPTION_EXCLUDE_KEYWORDS):
                continue
            if any(concepto in descripcion.upper() for concepto in CONCEPTOS_EXCLUIDOS):
                continue

            try:
                monto = float(match.group(6).replace(',', ''))
            except ValueError:
                continue

            transactions.append({
                'fecha': fecha,
                'descripcion': descripcion,
                'monto': abs(monto),
                'tipo': 'cargo',
                'cuota_info': cuota_info,
                'asignado_a': 'sin_asignar',
                'es_compra_directa': False
            })

        return transactions

    # 1. Extraer cuotas mensuales de la sección "DETALLE CUOTAS DEL MES"
    lines = text.split('\n')

    in_transaction_section = False
    transaction_section_text = ""

    for i, line in enumerate(lines):
        if re.search(r'DETALLE\s+CUOTAS\s+DEL\s+MES', line, re.IGNORECASE):
            in_transaction_section = True
            continue

        if in_transaction_section and re.search(r'INF[ÓO]RMATE\s+SOBRE', line, re.IGNORECASE):
            break

        if in_transaction_section:
            transaction_section_text += line + "\n"

    if not transaction_section_text:
        transaction_section_text = text

    # Patrón para cuotas mensuales
    # Ejemplo: 27/05/2025 MDOPAGO*MDOPAGO MERCADO P 173.00 4 de 6 0.00% 28.83 0 28.83
    pattern = r'(\d{2}/\d{2}/\d{4})\s+(.+)'

    matches = re.finditer(pattern, transaction_section_text)

    for match in matches:
        fecha = normalize_statement_date(match.group(1))
        line_content = match.group(2).strip()

        montos_encontrados = re.findall(r'\d+\.\d{2}', line_content)

        if not montos_encontrados:
            continue

        # El monto de la cuota es el ÚLTIMO número en la línea
        monto_str = montos_encontrados[-1]

        # Extraer información de cuotas (ej: "4 de 6")
        cuota_info = None
        cuota_match = re.search(r'(\d+)\s+de\s+(\d+)', line_content)
        if cuota_match:
            cuota_actual = int(cuota_match.group(1))
            cuota_total = int(cuota_match.group(2))
            cuota_info = f"{cuota_actual} de {cuota_total}"

        descripcion_match = re.match(r'(.+?)\s+(?:\d{1,3},\d{3}\.\d{2}|\d+\.\d{2}\s+\d+)', line_content)
        if descripcion_match:
            descripcion = descripcion_match.group(1).strip()
        else:
            descripcion_match2 = re.match(r'(.+?)\s+\d+\.\d{2}', line_content)
            if descripcion_match2:
                descripcion = descripcion_match2.group(1).strip()
            else:
                descripcion = line_content[:50].strip()

        if any(keyword in descripcion.upper() for keyword in DESCRIPTION_EXCLUDE_KEYWORDS):
            continue

        descripcion = re.sub(r'\s+', ' ', descripcion)
        descripcion = descripcion.strip()

        if len(descripcion) < 3:
            continue

        descripcion_upper = descripcion.upper()
        if any(concepto in descripcion_upper for concepto in CONCEPTOS_EXCLUIDOS):
            continue

        try:
            monto = float(monto_str)
        except ValueError:
            continue

        tipo = 'cargo'

        transactions.append({
            'fecha': fecha,
            'descripcion': descripcion,
            'monto': abs(monto),
            'tipo': tipo,
            'cuota_info': cuota_info,  # "X de Y" o None para compras directas
            'asignado_a': 'sin_asignar',
            'es_compra_directa': False
        })

    # 2. Extraer compras directas (sin cuotas) de la sección de operaciones
    direct_purchases = extract_direct_purchases(text)

    # Combinar ambas listas
    transactions.extend(direct_purchases)

    return transactions


def extract_summary(text):
    """
    Extrae el resumen financiero del estado de cuenta.
    Incluye los componentes del pago: Atrasos, Capital mínimo, Intereses,
    Comisiones, Cuota del Mes, Pago Mínimo y Pago Total Mes.
    """
    summary = {}

    # Línea de Crédito
    linea_credito_patterns = [
        r'Tu\s+l[íi]nea\s+de\s+cr[ée]dito\s+es[:\s\n\r]{0,120}S/\s*(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)',
        r'S/\s*(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)\s*\n\s*Tu\s+L[íÍI]nea\s+de\s+Cr[éeÉE]dito\s+es\s+de',
        r'L[ÍI]NEA\s+DE\s+CR[ÉE]DITO\s+S/\s*(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)',
        r'LIMITE\s+DE\s+USO\s+(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)'
    ]
    for pattern in linea_credito_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            summary['linea_credito'] = float(match.group(1).replace(',', ''))
            break

    # Periodo de Facturación
    periodo_match = re.search(r'PERIODO\s+DE\s+FACTURACION\s+DEL[:\s]+(\d{2}/\d{2}/\d{4})\s+AL[:\s]+(\d{2}/\d{2}/\d{4})', text, re.IGNORECASE)
    if periodo_match:
        summary['periodo_facturacion'] = f"{periodo_match.group(1)} AL: {periodo_match.group(2)}"
    else:
        periodo_match_textual = re.search(
            r'per[ií]odo\s+del\s+(\d{1,2})\s+de\s+([a-záéíóúñ]+)\s+de\s+(\d{4})\s+al\s+(\d{1,2})\s+de\s+([a-záéíóúñ]+)\s+de\s+(\d{4})',
            text,
            re.IGNORECASE
        )
        if periodo_match_textual:
            start_date = parse_spanish_textual_date(
                periodo_match_textual.group(1),
                periodo_match_textual.group(2),
                periodo_match_textual.group(3)
            )
            end_date = parse_spanish_textual_date(
                periodo_match_textual.group(4),
                periodo_match_textual.group(5),
                periodo_match_textual.group(6)
            )
            if start_date and end_date:
                summary['periodo_facturacion'] = f"{start_date} AL: {end_date}"

        periodo_match_new = re.search(r'del\s+(\d{2}/\d{2})\s+al\s+cierre\s+de\s+(\d{2}/\d{2})', text, re.IGNORECASE)
        if periodo_match_new and 'periodo_facturacion' not in summary:
            summary['periodo_facturacion'] = f"{periodo_match_new.group(1)} AL: {periodo_match_new.group(2)}"

    # Formato narrativo BBVA: bloque de pago total/mínimo del período
    narrativo_pagos_match = re.search(
        r'Pago\s+total\s+del\s+per[íi]odo\s+Pago\s+m[íi]nimo\s+del\s+per[íi]odo[\s\S]{0,220}?'
        r'Soles:\s*S/\s*(\d{1,3}(?:,\d{3})*\.\d{2})\s+Soles:\s*S/\s*(\d{1,3}(?:,\d{3})*\.\d{2})',
        text,
        re.IGNORECASE
    )
    if narrativo_pagos_match:
        summary['pago_total_mes'] = float(narrativo_pagos_match.group(1).replace(',', ''))
        summary['pago_minimo'] = float(narrativo_pagos_match.group(2).replace(',', ''))

    # Capturar fecha de pago textual en formato narrativo
    pago_textual_match = re.search(
        r'([Ll]unes|[Mm]artes|[Mm]i[ée]rcoles|[Jj]ueves|[Vv]iernes|[Ss][áa]bado|[Dd]omingo)\s+(\d{1,2})\s+de\s+([a-záéíóúñ]+)',
        text,
        re.IGNORECASE
    )
    if pago_textual_match:
        payment_month = SPANISH_MONTHS.get(pago_textual_match.group(3).lower())
        if payment_month:
            reference_date = None
            if 'periodo_facturacion' in summary:
                period_dates = re.findall(r'(\d{2}/\d{2}/\d{4})', summary['periodo_facturacion'])
                if len(period_dates) == 2:
                    reference_date = period_dates[1]
            inferred_year = infer_payment_year(reference_date, payment_month)
            parsed_date = parse_spanish_textual_date(
                pago_textual_match.group(2),
                pago_textual_match.group(3),
                str(inferred_year)
            )
            if parsed_date:
                summary['fecha_pago'] = parsed_date

    # Nuevo formato BBVA: bloque de pago mínimo/total al inicio
    pagos_mes_match = re.search(
        r'PAGO\s+M[ÍI]NIMO\s+DEL\s+MES\s+PAGO\s+TOTAL\s+DEL\s+MES\s+[ÚU]LTIMO\s+D[ÍI]A\s+DE\s+PAGO[\s\S]{0,200}?'
        r'S/\s*(\d{1,3}(?:,\d{3})*\.\d{2})\s+S/\s*(\d{1,3}(?:,\d{3})*\.\d{2})\s+(\d{2}/\d{2}/\d{4})',
        text,
        re.IGNORECASE
    )
    if pagos_mes_match:
        summary['pago_minimo'] = float(pagos_mes_match.group(1).replace(',', ''))
        summary['pago_total_mes'] = float(pagos_mes_match.group(2).replace(',', ''))
        summary['fecha_pago'] = normalize_statement_date(pagos_mes_match.group(3))

    # Extraer componentes del pago desde la tabla de resumen
    # Formato: Atrasos + Cápital mínimo + Intereses + Comisiones + Cuota del Mes = Pago Mínimo | Pago Total Mes
    # Ejemplo: Soles 0.00 + 30.00 + 1.69 + 8.85 + 455.14 = 495.68 495.94

    # Patrón para extraer la línea de Soles con todos los componentes
    resumen_pattern = r'Soles\s+(\d+\.\d{2})\s*\+\s*(\d+\.\d{2})\s*\+\s*(\d+\.\d{2})\s*\+\s*(\d+\.\d{2})\s*\+\s*(\d+\.\d{2})\s*=\s*(\d+\.\d{2})\s+(\d+\.\d{2})'
    resumen_match = re.search(resumen_pattern, text, re.IGNORECASE)

    if resumen_match:
        summary['atrasos'] = float(resumen_match.group(1))
        summary['capital_minimo'] = float(resumen_match.group(2))
        summary['intereses'] = float(resumen_match.group(3))
        summary['comisiones'] = float(resumen_match.group(4))
        summary['cuota_mes'] = float(resumen_match.group(5))
        summary['pago_minimo'] = float(resumen_match.group(6))
        summary['pago_total_mes'] = float(resumen_match.group(7))

        # El seguro de desgravamen está incluido en comisiones en este formato
        summary['seguro_desgravamen'] = summary['comisiones']
    else:
        # Fallback: intentar extraer valores individualmente si el patrón no coincide

        # Seguro de Desgravamen
        seguro_patterns = [
            r'SEGURO\s+DE\s+DESGRAVAMEN[^\n]*S/\s*(\d+\.\d{2})',
            r'SEGURO\s+DE\s+DESGRAVAMEN\s+\d{2}-\d{2}-\d{4}\s+(\d+\.\d{2})',
            r'SEGURO\s+DE\s+DESGRAVAMEN\s+\d{2}/\d{2}/\d{4}\s+(\d+\.\d{2})',
            r'SEGURO\s+DESGRAVAMEN[^\d]*(\d+\.\d{2})'
        ]
        for pattern in seguro_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                summary['seguro_desgravamen'] = float(match.group(1).replace(',', ''))
                break

        # Intereses si paga mínimo
        intereses_minimo_match = re.search(r'INTERESES\s+SI\s+PAGA\s+MINIMO\s+(\d+\.\d{2})', text, re.IGNORECASE)
        if intereses_minimo_match:
            summary['intereses_pago_minimo'] = float(intereses_minimo_match.group(1).replace(',', ''))

        # Pago mínimo
        pago_min_match = re.search(r'(?:Pago Mínimo|Mínimo a Pagar)[:|\s]+[S/.\s]*?([-]?\d{1,3}(?:,\d{3})*(?:\.\d{2})?)', text, re.IGNORECASE)
        if pago_min_match:
            summary['pago_minimo'] = float(pago_min_match.group(1).replace(',', ''))

        pago_min_periodo_match = re.search(r'Pago\s+m[íi]nimo\s+del\s+per[íi]odo\s+S/\s*(\d{1,3}(?:,\d{3})*\.\d{2})', text, re.IGNORECASE)
        if pago_min_periodo_match and 'pago_minimo' not in summary:
            summary['pago_minimo'] = float(pago_min_periodo_match.group(1).replace(',', ''))

    # Consumos totales
    consumos_match = re.search(r'CONSUMOS\s+(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)', text, re.IGNORECASE)
    if consumos_match:
        summary['total_cargos'] = float(consumos_match.group(1).replace(',', ''))

    # Total abonos / Pagos recibidos
    abonos_patterns = [
        r'PAGO\s+RECIBIDO\s+[-]?(\d+\.\d{2})',
        r'(?:Total Abonos|Pagos)[:|\s]+[S/.\s]*?([-]?\d{1,3}(?:,\d{3})*(?:\.\d{2})?)'
    ]
    for pattern in abonos_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            summary['total_abonos'] = float(match.group(1).replace(',', ''))
            break

    # Pago total/saldo actual / Deuda total
    pago_patterns = [
        r'Deuda\s+total\s+\(inc\.\s+Cuota\s+(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)',
        r'(?:Pago Total|Total a Pagar|Saldo Actual|Nuevo Saldo)[:|\s]+[S/.\s]*?([-]?\d{1,3}(?:,\d{3})*(?:\.\d{2})?)'
    ]
    for pattern in pago_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            summary['pago_total'] = float(match.group(1).replace(',', ''))
            break

    # TEA (Tasa Efectiva Anual)
    tea_match = re.search(r'TEA\s+SOL[:\.\s]+(\d+\.\d{2})%', text, re.IGNORECASE)
    if tea_match:
        summary['tea'] = float(tea_match.group(1))

    # Total de cuotas del mes (de la sección DETALLE CUOTAS DEL MES)
    total_cuotas_match = re.search(r'TOTAL\s+CUOTAS\s+DEL\s+MES\s+LINEA\s+DE\s+CREDITO\s+(\d+\.\d{2})', text, re.IGNORECASE)
    if total_cuotas_match:
        summary['total_cuotas_mes'] = float(total_cuotas_match.group(1))

    subtotal_match = re.search(r'Subtotal\s+S/\s*(\d{1,3}(?:,\d{3})*\.\d{2})', text, re.IGNORECASE)
    if subtotal_match:
        summary['total_cuotas_mes'] = float(subtotal_match.group(1).replace(',', ''))

    # Nuevo formato BBVA: suma de totales de secciones de cuotas
    cuotas_nuevo_patterns = [
        r'TOTAL\s+COMPRAS\s+EN\s+CUOTAS\s+Y\s+DISPOSICION\s+DE\s+EFECTIVO\s+EN\s+CUOTAS\s+\d+\.\d{2}\s+\d+\.\d{2}\s+(\d+\.\d{2})\s+(?:---|\d+\.\d{2})',
        r'TOTAL\s+COMPRAS\s+PAGO\s+SIN\s+INTERESES\s+\d+\.\d{2}\s+\d+\.\d{2}\s+(\d+\.\d{2})\s+(?:---|\d+\.\d{2})'
    ]
    total_cuotas_nuevo = 0.0
    for pattern in cuotas_nuevo_patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            total_cuotas_nuevo += float(match.group(1))

    if total_cuotas_nuevo > 0:
        summary['total_cuotas_mes'] = total_cuotas_nuevo

    return summary


def load_description_replacements():
    """Carga los reemplazos de descripciones desde la base de datos"""
    return db.get_all_description_replacements()


def apply_description_replacements(transactions):
    """Aplica los reemplazos de descripciones a las transacciones"""
    replacements = load_description_replacements()
    for trans in transactions:
        original_desc = trans['descripcion']
        if original_desc in replacements:
            trans['descripcion_original'] = original_desc
            trans['descripcion'] = replacements[original_desc]
    return transactions
