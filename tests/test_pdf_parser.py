"""
Tests unitarios del parser de estados de cuenta BBVA (src.pdf_parser).

Usan textos sintéticos que replican los formatos reconocidos por los
regex del parser; no requieren PDFs reales.
"""
import unittest
from datetime import datetime

from src.pdf_parser import (
    clean_narrative_description,
    extract_general_info,
    extract_summary,
    extract_transactions,
    infer_payment_year,
    is_password_protected_pdf_error,
    normalize_statement_date,
    parse_spanish_textual_date,
    remove_duplicate_transactions,
)


class TestNormalizeStatementDate(unittest.TestCase):
    def test_formato_dd_mm_yyyy(self):
        self.assertEqual(normalize_statement_date('05/03/2025'), '05/03/2025')

    def test_digitos_simples_se_rellenan_con_ceros(self):
        self.assertEqual(normalize_statement_date('5/3/2025'), '05/03/2025')

    def test_guiones_se_convierten_a_barras(self):
        self.assertEqual(normalize_statement_date('05-03-2025'), '05/03/2025')

    def test_entrada_vacia(self):
        self.assertEqual(normalize_statement_date(''), '')
        self.assertIsNone(normalize_statement_date(None))

    def test_texto_no_fecha_se_devuelve_normalizado(self):
        self.assertEqual(normalize_statement_date('15/12'), '15/12')


class TestParseSpanishTextualDate(unittest.TestCase):
    def test_mes_valido(self):
        self.assertEqual(parse_spanish_textual_date('1', 'enero', '2026'), '01/01/2026')

    def test_setiembre_variante_peruana(self):
        self.assertEqual(parse_spanish_textual_date('5', 'setiembre', '2025'), '05/09/2025')

    def test_septiembre_estandar(self):
        self.assertEqual(parse_spanish_textual_date('5', 'septiembre', '2025'), '05/09/2025')

    def test_mes_invalido_devuelve_none(self):
        self.assertIsNone(parse_spanish_textual_date('1', 'foo', '2025'))


class TestInferPaymentYear(unittest.TestCase):
    def test_mes_pago_menor_que_mes_cierre_es_ano_siguiente(self):
        # Cierre en diciembre, pago en enero -> año siguiente
        self.assertEqual(infer_payment_year('15/12/2025', 1), 2026)

    def test_mes_pago_mayor_o_igual_mismo_ano(self):
        self.assertEqual(infer_payment_year('15/12/2025', 12), 2025)
        self.assertEqual(infer_payment_year('15/03/2025', 6), 2025)

    def test_sin_fecha_referencia_usa_ano_actual(self):
        self.assertEqual(infer_payment_year(None, 5), datetime.now().year)
        self.assertEqual(infer_payment_year('fecha-invalida', 5), datetime.now().year)


class TestCleanNarrativeDescription(unittest.TestCase):
    def test_elimina_montos_moneda_fechas_y_peru(self):
        texto = 'MP *ALIEXPRESS S/ 26.36 PERU 02/11/2025'
        self.assertEqual(clean_narrative_description(texto), 'MP *ALIEXPRESS')

    def test_elimina_montos_con_miles(self):
        texto = 'COMPRA PLAZA VEA 1,249.00'
        self.assertEqual(clean_narrative_description(texto), 'COMPRA PLAZA VEA')

    def test_colapsa_espacios(self):
        self.assertEqual(clean_narrative_description('  ALGO    SIMPLE  '), 'ALGO SIMPLE')


class TestRemoveDuplicateTransactions(unittest.TestCase):
    def _trans(self, fecha, descripcion, monto):
        return {'fecha': fecha, 'descripcion': descripcion, 'monto': monto}

    def test_elimina_duplicados_por_fecha_descripcion_monto(self):
        transacciones = [
            self._trans('01/01/2025', 'COMPRA A', 10.0),
            self._trans('01/01/2025', 'COMPRA A', 10.0),
            self._trans('01/01/2025', 'COMPRA B', 10.0),
        ]
        resultado = remove_duplicate_transactions(transacciones)
        self.assertEqual(len(resultado), 2)

    def test_monto_redondeado_a_dos_decimales(self):
        transacciones = [
            self._trans('01/01/2025', 'COMPRA A', 10.0),
            self._trans('01/01/2025', 'COMPRA A', 10.004),
        ]
        resultado = remove_duplicate_transactions(transacciones)
        self.assertEqual(len(resultado), 1)

    def test_descripcion_con_espacios_extra_es_duplicado(self):
        transacciones = [
            self._trans('01/01/2025', 'COMPRA A', 10.0),
            self._trans('01/01/2025', '  COMPRA A  ', 10.0),
        ]
        resultado = remove_duplicate_transactions(transacciones)
        self.assertEqual(len(resultado), 1)


class TestIsPasswordProtectedPdfError(unittest.TestCase):
    def test_positivo_password(self):
        self.assertTrue(is_password_protected_pdf_error(Exception('password required')))

    def test_positivo_not_decrypted(self):
        self.assertTrue(
            is_password_protected_pdf_error(ValueError('File has not been decrypted'))
        )

    def test_positivo_nombre_de_tipo(self):
        class PDFPasswordIncorrect(Exception):
            pass

        self.assertTrue(is_password_protected_pdf_error(PDFPasswordIncorrect('boom')))

    def test_negativo(self):
        self.assertFalse(is_password_protected_pdf_error(ValueError('boom')))


class TestExtractGeneralInfo(unittest.TestCase):
    TEXTO = (
        'BBVA ESTADO DE CUENTA\n'
        'Tarjeta: 414791******4154\n'
        'Señor:\n'
        'PEREZ GARCIA JUAN CARLOS\n'
        'Fecha de Cierre 15/12/2025\n'
    )

    def setUp(self):
        self.info = extract_general_info(self.TEXTO)

    def test_tarjeta_enmascarada(self):
        self.assertEqual(self.info['tarjeta'], '414791******4154')

    def test_titular_via_patron_senor(self):
        self.assertEqual(self.info['titular'], 'PEREZ GARCIA JUAN CARLOS')

    def test_fecha_cierre(self):
        self.assertEqual(self.info['fecha_cierre'], '15/12/2025')


class TestExtractTransactions(unittest.TestCase):
    """Formato clásico: compras directas antes de 'DETALLE CUOTAS DEL MES'
    y cuotas dentro de esa sección."""

    TEXTO = (
        'OPERACIONES DEL MES\n'
        '02/11/2025 1234 (C) MP *ALIEXPRESS 26.36 0.00\n'
        '05/11/2025 1234 (C) PAGO RECIBIDO 100.00 0.00\n'
        'DETALLE CUOTAS DEL MES\n'
        '27/05/2025 MDOPAGO*MDOPAGO MERCADO P 173.00 4 de 6 0.00% 28.83 0 28.83\n'
        'INFÓRMATE SOBRE TUS BENEFICIOS\n'
    )

    def setUp(self):
        self.transacciones = extract_transactions(self.TEXTO)
        self.por_descripcion = {t['descripcion']: t for t in self.transacciones}

    def test_extrae_cuota_con_cuota_info(self):
        cuota = self.por_descripcion.get('MDOPAGO*MDOPAGO MERCADO P')
        self.assertIsNotNone(cuota)
        self.assertEqual(cuota['cuota_info'], '4 de 6')
        self.assertEqual(cuota['monto'], 28.83)
        self.assertEqual(cuota['fecha'], '27/05/2025')
        self.assertFalse(cuota['es_compra_directa'])

    def test_extrae_compra_directa(self):
        directa = self.por_descripcion.get('MP *ALIEXPRESS')
        self.assertIsNotNone(directa)
        self.assertTrue(directa['es_compra_directa'])
        self.assertIsNone(directa['cuota_info'])
        self.assertEqual(directa['monto'], 26.36)

    def test_conceptos_excluidos_no_aparecen(self):
        descripciones = [t['descripcion'].upper() for t in self.transacciones]
        self.assertFalse(any('PAGO RECIBIDO' in d for d in descripciones))

    def test_total_transacciones(self):
        self.assertEqual(len(self.transacciones), 2)


class TestExtractSummary(unittest.TestCase):
    TEXTO = (
        'Tu línea de crédito es: S/ 33,500.00\n'
        'PAGO MÍNIMO DEL MES PAGO TOTAL DEL MES ÚLTIMO DÍA DE PAGO\n'
        'S/ 495.68 S/ 1,495.94 28/12/2025\n'
    )

    def setUp(self):
        self.summary = extract_summary(self.TEXTO)

    def test_linea_credito(self):
        self.assertEqual(self.summary['linea_credito'], 33500.0)

    def test_pago_minimo(self):
        self.assertEqual(self.summary['pago_minimo'], 495.68)

    def test_pago_total_mes(self):
        self.assertEqual(self.summary['pago_total_mes'], 1495.94)

    def test_fecha_pago(self):
        self.assertEqual(self.summary['fecha_pago'], '28/12/2025')


if __name__ == '__main__':
    unittest.main()
