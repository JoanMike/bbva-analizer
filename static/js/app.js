// Estado global de la aplicación
let currentData = null;
let currentFilter = 'todas';
let personas = []; // Lista de personas configuradas
let currentPdfId = null; // Identificador único del PDF actual
const isFrozenBuild = document.body?.dataset?.isFrozen === 'true';

// Escapa caracteres especiales de HTML para evitar XSS al interpolar datos en innerHTML
function escapeHtml(str) {
    const map = {
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#39;'
    };
    return String(str).replace(/[&<>"']/g, char => map[char]);
}

// Inicialización
document.addEventListener('DOMContentLoaded', function () {
    loadPersonas();
    initializeApp();

    if (isFrozenBuild) {
        // Mostrar botón de apagado manual (solo versión ejecutable)
        const shutdownBtn = document.getElementById('shutdownBtn');
        if (shutdownBtn) {
            shutdownBtn.style.display = 'block';
            shutdownBtn.addEventListener('click', () => {
                fetch('/shutdown', { method: 'POST' });
                showNotification('La aplicación se está cerrando. Ya puedes cerrar esta pestaña.', 'info');
            });
        }
    }

    // Manejar Enter en el campo de nueva descripción
    const newDescInput = document.getElementById('newDescription');
    if (newDescInput) {
        newDescInput.addEventListener('keypress', function (e) {
            if (e.key === 'Enter') {
                e.preventDefault();
                saveDescriptionReplacement();
            }
        });
    }
});

// Cargar personas desde el servidor
async function loadPersonas() {
    try {
        const response = await fetch('/personas');
        personas = await response.json();
        updateFiltersUI();
    } catch (error) {
        console.error('Error cargando personas:', error);
        // Usar personas por defecto en caso de error
        personas = [
            { id: 'persona1', nombre: 'Persona 1', icono: '👤', color: '#1e88e5' },
            { id: 'persona2', nombre: 'Persona 2', icono: '👤', color: '#43a047' },
            { id: 'persona3', nombre: 'Persona 3', icono: '👤', color: '#e53935' }
        ];
    }
}

// Actualizar UI de filtros con personas dinámicas
function updateFiltersUI() {
    const filtersContainer = document.querySelector('.filters');
    if (!filtersContainer) return;

    // Limpiar filtros existentes (excepto "Todas")
    const todasBtn = filtersContainer.querySelector('[data-filter="todas"]');
    filtersContainer.innerHTML = '';

    // Re-agregar botón "Todas"
    if (todasBtn) {
        filtersContainer.appendChild(todasBtn);
    } else {
        const btnTodas = document.createElement('button');
        btnTodas.className = 'filter-btn active';
        btnTodas.dataset.filter = 'todas';
        btnTodas.onclick = (e) => filterTransactions('todas', e);
        btnTodas.innerHTML = 'Todas (<span id="count-todas">0</span>)';
        filtersContainer.appendChild(btnTodas);
    }

    // Agregar filtros de personas dinámicamente
    personas.forEach(persona => {
        const btn = document.createElement('button');
        btn.className = 'filter-btn';
        btn.dataset.filter = persona.id;
        btn.onclick = (e) => filterTransactions(persona.id, e);
        btn.textContent = `${persona.icono} ${persona.nombre} (`;
        const countSpan = document.createElement('span');
        countSpan.id = `count-${persona.id}`;
        countSpan.textContent = '0';
        btn.appendChild(countSpan);
        btn.appendChild(document.createTextNode(')'));
        filtersContainer.appendChild(btn);
    });

    // Agregar filtro "Sin Asignar"
    const btnSinAsignar = document.createElement('button');
    btnSinAsignar.className = 'filter-btn';
    btnSinAsignar.dataset.filter = 'sin_asignar';
    btnSinAsignar.onclick = (e) => filterTransactions('sin_asignar', e);
    btnSinAsignar.innerHTML = 'Sin Asignar (<span id="count-sin_asignar">0</span>)';
    filtersContainer.appendChild(btnSinAsignar);
}

// ===== FUNCIONES PARA GUARDADO DE ASIGNACIONES =====

/**
 * Genera un ID único para el PDF basado en información clave
 * Usa titular, tarjeta y periodo para identificar el estado de cuenta
 */
function generatePdfId(infoGeneral) {
    const titular = infoGeneral.titular || '';
    const tarjeta = infoGeneral.tarjeta || '';
    const periodo = infoGeneral.periodo || '';

    // Crear un string único combinando los datos
    const uniqueString = `${titular}_${tarjeta}_${periodo}`;

    // Generar un hash simple (suficiente para identificación local)
    let hash = 0;
    for (let i = 0; i < uniqueString.length; i++) {
        const char = uniqueString.charCodeAt(i);
        hash = ((hash << 5) - hash) + char;
        hash = hash & hash; // Convertir a 32bit integer
    }

    return `pdf_${Math.abs(hash)}`;
}

/**
 * Guarda las asignaciones del PDF actual en la base de datos
 */
async function saveAssignments() {
    if (!currentPdfId || !currentData || !currentData.transacciones) {
        return;
    }

    try {
        // Preparar datos para enviar al servidor
        const payload = {
            filename: currentData.filename || 'unknown.pdf',
            info_general: currentData.info_general || {},
            transacciones: currentData.transacciones.map((trans, index) => ({
                transaction_index: index,
                descripcion: trans.descripcion,
                descripcion_original: trans.descripcion_original || trans.descripcion,
                monto: trans.monto,
                fecha: trans.fecha,
                asignado_a: trans.asignado_a || 'sin_asignar'
            }))
        };

        // Enviar a la API
        const response = await fetch(`/assignments/${currentPdfId}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(payload)
        });

        const result = await response.json();

        if (result.success) {
            console.log(`✅ Asignaciones guardadas en BD para ${currentPdfId}`);
        } else {
            console.error('Error guardando asignaciones:', result.error);
        }
    } catch (error) {
        console.error('Error guardando asignaciones:', error);
    }
}

/**
 * Carga las asignaciones guardadas para el PDF actual desde la base de datos
 */
async function loadAssignments() {
    if (!currentPdfId || !currentData || !currentData.transacciones) {
        return false;
    }

    try {
        const response = await fetch(`/assignments/${currentPdfId}`);
        const result = await response.json();

        if (!result.success || !result.found) {
            console.log('ℹ️ No hay asignaciones guardadas para este PDF en BD');
            return false;
        }

        const savedData = result.data;
        const savedTransactions = savedData.transacciones || [];

        if (savedTransactions.length === 0) {
            return false;
        }

        let matchCount = 0;

        // Restaurar asignaciones por índice
        savedTransactions.forEach(saved => {
            const index = saved.transaction_index;
            if (index >= 0 && index < currentData.transacciones.length) {
                const trans = currentData.transacciones[index];

                // Verificar que coincida la descripción y monto para mayor seguridad
                const currentDesc = trans.descripcion_original || trans.descripcion;
                const savedDesc = saved.descripcion_original || saved.descripcion;

                if (currentDesc === savedDesc && trans.monto === saved.monto && trans.fecha === saved.fecha) {
                    trans.asignado_a = saved.asignado_a;
                    matchCount++;
                }
            }
        });

        if (matchCount > 0) {
            console.log(`✅ ${matchCount} asignaciones restauradas desde BD`);

            // Mostrar notificación al usuario
            showNotification(
                `Se restauraron ${matchCount} asignaciones guardadas previamente`,
                'success'
            );

            return true;
        }

        return false;
    } catch (error) {
        console.error('Error cargando asignaciones desde BD:', error);
        return false;
    }
}

/**
 * Limpia asignaciones antiguas - ahora se hace desde el servidor
 */
async function cleanOldAssignments() {
    try {
        const response = await fetch('/database/cleanup', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ days: 90 })
        });

        const result = await response.json();

        if (result.success) {
            console.log(`🗑️ ${result.message}`);
        }
    } catch (error) {
        console.error('Error limpiando asignaciones antiguas:', error);
    }
}

/**
 * Limpia las asignaciones guardadas del PDF actual
 */
async function clearSavedAssignments() {
    if (!currentPdfId) {
        showNotification('No hay asignaciones para limpiar', 'info');
        return;
    }

    const confirmed = await showConfirm(
        '¿Estás seguro de que deseas eliminar las asignaciones guardadas de este estado de cuenta?',
        'Confirmar Eliminación'
    );

    if (confirmed) {
        try {
            const response = await fetch(`/assignments/${currentPdfId}`, {
                method: 'DELETE'
            });

            const result = await response.json();

            if (result.success) {
                // Limpiar asignaciones actuales
                if (currentData && currentData.transacciones) {
                    currentData.transacciones.forEach(trans => {
                        trans.asignado_a = 'sin_asignar';
                    });

                    // Actualizar la vista
                    displayTransactions(currentData.transacciones);
                    calculateTotals();
                }

                showNotification('Asignaciones eliminadas correctamente', 'success');
                console.log(`🗑️ Asignaciones eliminadas para ${currentPdfId}`);
            } else {
                showNotification('Error al eliminar asignaciones', 'error');
            }
        } catch (error) {
            console.error('Error eliminando asignaciones:', error);
            showNotification('Error al eliminar asignaciones', 'error');
        }
    }
}

function initializeApp() {
    const fileInput = document.getElementById('fileInput');

    // Evento para selección de archivo
    fileInput.addEventListener('change', handleFileSelect);

    // Drag and drop
    const uploadCard = document.querySelector('.upload-card');

    uploadCard.addEventListener('dragover', (e) => {
        e.preventDefault();
        uploadCard.style.borderColor = 'var(--accent-color)';
        uploadCard.style.background = '#f0f9ff';
    });

    uploadCard.addEventListener('dragleave', (e) => {
        e.preventDefault();
        uploadCard.style.borderColor = '';
        uploadCard.style.background = '';
    });

    uploadCard.addEventListener('drop', (e) => {
        e.preventDefault();
        uploadCard.style.borderColor = '';
        uploadCard.style.background = '';

        const file = e.dataTransfer.files[0];
        if (file && file.type === 'application/pdf') {
            fileInput.files = e.dataTransfer.files;
            handleFileSelect({ target: fileInput });
        } else {
            showNotification('Por favor, sube un archivo PDF válido', 'warning');
        }
    });
}

function handleFileSelect(event) {
    const file = event.target.files[0];
    if (file) {
        const fileInfo = document.getElementById('fileInfo');
        const fileName = document.getElementById('fileName');

        fileName.textContent = file.name;
        fileInfo.style.display = 'flex';
    }
}

async function uploadFile() {
    const fileInput = document.getElementById('fileInput');
    const file = fileInput.files[0];

    if (!file) {
        showNotification('Por favor selecciona un archivo PDF', 'warning');
        return;
    }

    // Mostrar loading
    document.getElementById('uploadSection').style.display = 'none';
    document.getElementById('loading').style.display = 'block';

    const formData = new FormData();
    formData.append('file', file);

    try {
        const response = await fetch('/upload', {
            method: 'POST',
            body: formData
        });

        const payload = await response.json().catch(() => ({}));

        if (!response.ok) {
            const backendError = payload?.error || `Error HTTP ${response.status}`;
            throw new Error(backendError);
        }

        const data = payload;
        data.filename = file.name;
        currentData = data;

        // Mostrar resultados
        displayResults(data);

    } catch (error) {
        console.error('Error:', error);
        showNotification('Error al procesar el PDF: ' + error.message, 'error');
        resetApp();
    }
}

/**
 * Distribuye automáticamente el Seguro Desgravamen entre todas las personas configuradas
 * @param {Object} data - Datos del PDF procesado
 */
function distributeSeguroDesgravamen(data) {
    if (!data || !data.transacciones || !data.resumen) {
        console.log('⚠️ No hay datos válidos para distribuir seguro');
        return;
    }

    // Verificar si existe el seguro de desgravamen en el resumen
    const seguroDesgravamen = data.resumen.seguro_desgravamen;
    if (!seguroDesgravamen || seguroDesgravamen <= 0) {
        console.log('ℹ️ No se encontró Seguro Desgravamen para distribuir');
        return;
    }

    const numeroPersonas = personas.length;
    if (numeroPersonas === 0) {
        console.log('⚠️ No hay personas configuradas para distribuir');
        return;
    }

    // Calcular el monto que le corresponde a cada persona
    const montoPorPersona = seguroDesgravamen / numeroPersonas;

    console.log(`💰 Distribuyendo Seguro Desgravamen:`);
    console.log(`   Total: S/ ${seguroDesgravamen.toFixed(2)}`);
    console.log(`   Personas: ${numeroPersonas}`);
    console.log(`   Por persona: S/ ${montoPorPersona.toFixed(2)}`);

    // Obtener la fecha del periodo de facturación para usar en las transacciones
    let fechaSeguro = new Date().toLocaleDateString('es-PE');
    if (data.info_general && data.info_general.periodo) {
        // Intentar extraer la primera fecha del periodo
        const fechaMatch = data.info_general.periodo.match(/(\d{2}\/\d{2}\/\d{4})/);
        if (fechaMatch) {
            fechaSeguro = fechaMatch[1];
        }
    }

    // Crear transacciones del seguro para cada persona directamente
    const nuevasTransacciones = [];

    personas.forEach((persona, index) => {
        // Ajustar el último monto para que la suma sea exacta
        let montoFinal = parseFloat(montoPorPersona.toFixed(2));
        if (index === numeroPersonas - 1) {
            // Para la última persona, calcular el residuo
            const sumaAnteriores = parseFloat(montoPorPersona.toFixed(2)) * (numeroPersonas - 1);
            montoFinal = parseFloat((seguroDesgravamen - sumaAnteriores).toFixed(2));
        }

        const transaccionPersona = {
            fecha: fechaSeguro,
            descripcion: `Seguro Desgravamen - ${persona.nombre}`,
            monto: montoFinal,
            tipo: 'cargo',
            asignado_a: persona.id,
            es_division_seguro: true, // Marcador para identificar estas transacciones
            pagina: 1
        };
        nuevasTransacciones.push(transaccionPersona);
        console.log(`   ✓ ${persona.icono} ${persona.nombre}: S/ ${montoFinal.toFixed(2)}`);
    });

    // Agregar las nuevas transacciones al inicio del array
    data.transacciones.unshift(...nuevasTransacciones);

    console.log(`✅ Se agregaron ${nuevasTransacciones.length} transacciones del seguro`);
    showNotification(`Seguro Desgravamen distribuido: S/ ${montoPorPersona.toFixed(2)} por persona`, 'success');
}

async function displayResults(data) {
    // Ocultar loading
    document.getElementById('loading').style.display = 'none';

    // Mostrar sección de resultados
    document.getElementById('resultsSection').style.display = 'block';

    // Generar ID único para este PDF
    currentPdfId = generatePdfId(data.info_general);
    console.log(`📄 PDF identificado: ${currentPdfId}`);

    // Limpiar asignaciones antiguas (una vez al cargar)
    await cleanOldAssignments();

    // PRIMERO: Distribuir el Seguro Desgravamen automáticamente entre todas las personas
    distributeSeguroDesgravamen(data);

    // DESPUÉS: Intentar cargar asignaciones guardadas (esto sobrescribirá las del seguro si existen)
    await loadAssignments();

    // Llenar información general
    displayGeneralInfo(data.info_general);

    // Llenar resumen financiero
    displaySummary(data.resumen);

    // Llenar tabla de transacciones
    displayTransactions(data.transacciones);

    // Calcular totales iniciales
    calculateTotals();

    // Scroll suave a resultados
    document.getElementById('resultsSection').scrollIntoView({ behavior: 'smooth' });
}

function displayGeneralInfo(info) {
    const container = document.getElementById('infoGeneral');
    container.innerHTML = '';

    const fields = [
        { key: 'titular', label: 'Titular', icon: '👤' },
        { key: 'tarjeta', label: 'Tarjeta', icon: '💳' },
        { key: 'oficina', label: 'Oficina', icon: '🏢' },
        { key: 'periodo', label: 'Periodo de Facturación', icon: '📅' },
        { key: 'fecha_cierre', label: 'Fecha de Cierre', icon: '📅' },
        { key: 'fecha_pago', label: 'Último Día de Pago', icon: '⏰' }
    ];

    fields.forEach(field => {
        if (info[field.key]) {
            const div = document.createElement('div');
            div.className = 'info-item';
            div.innerHTML = `
                <label>${field.icon} ${field.label}</label>
                <span>${escapeHtml(info[field.key])}</span>
            `;
            container.appendChild(div);
        }
    });
}

function displaySummary(summary) {
    const container = document.getElementById('summaryGrid');
    container.innerHTML = '';

    const fields = [
        { key: 'linea_credito', label: 'Línea de Crédito', type: 'neutral', icon: '💰' },
        { key: 'periodo_facturacion', label: 'Periodo Facturación', type: 'info', icon: '🗓️', isText: true },
        { key: 'total_pagar_mes', label: 'Total a Pagar este mes', type: 'negative', icon: '💸' },
        { key: 'seguro_desgravamen', label: 'Seguro Desgravamen', type: 'negative', icon: '🛡️' },
        { key: 'pago_minimo', label: 'Pago Mínimo', type: 'neutral', icon: '📉' },
        { key: 'pago_total', label: 'Deuda Total', type: 'negative', icon: '💰' },
        { key: 'tea', label: 'TEA', type: 'info', icon: '📊', suffix: '%' }
    ];

    fields.forEach(field => {
        if (summary[field.key] !== undefined && summary[field.key] !== null) {
            const div = document.createElement('div');
            div.className = `summary-item ${field.type}`;

            let valueDisplay = '';
            if (field.isText) {
                // Para campos de texto como el periodo
                valueDisplay = summary[field.key];
            } else if (field.suffix === '%') {
                valueDisplay = `${summary[field.key]}%`;
            } else {
                valueDisplay = `S/ ${formatMoney(summary[field.key])}`;
            }

            div.innerHTML = `
                <label>${field.icon || ''} ${field.label}</label>
                <span class="amount">${escapeHtml(valueDisplay)}</span>
            `;
            container.appendChild(div);
        }
    });
}

function displayTransactions(transactions) {
    const tbody = document.getElementById('transactionsTable');
    tbody.innerHTML = '';

    transactions.forEach((trans, index) => {
        const tr = document.createElement('tr');
        tr.dataset.index = index;
        tr.dataset.assignedTo = trans.asignado_a || 'sin_asignar';

        // Determinar la descripción a mostrar y si tiene reemplazo
        const hasReplacement = trans.descripcion_original ? true : false;
        const displayDescription = trans.descripcion;
        const originalDescription = trans.descripcion_original || trans.descripcion;

        tr.innerHTML = `
            <td>${escapeHtml(trans.fecha)}</td>
            <td>
                <div class="description-cell">
                    <span class="description-text ${hasReplacement ? 'has-replacement' : ''}" 
                          title="${hasReplacement ? 'Original: ' + escapeHtml(originalDescription) : ''}">
                        ${escapeHtml(displayDescription)}
                    </span>
                    <button class="btn-edit-description" 
                            onclick="openEditDescriptionModal(${index})" 
                            title="Editar descripción">
                        ✏️
                    </button>
                </div>
            </td>
            <td class="font-weight-bold text-danger">
                S/ ${formatMoney(trans.monto)}
            </td>
            <td>
                <span class="cuota-badge ${trans.cuota_info ? '' : 'directa'}">
                    ${escapeHtml(trans.cuota_info || (trans.es_division_seguro ? 'Seguro' : 'Directa'))}
                </span>
            </td>
            <td>
                <select class="assign-select" onchange="assignTransaction(${index}, this.value)">
                    <option value="sin_asignar" ${trans.asignado_a === 'sin_asignar' ? 'selected' : ''}>Sin Asignar</option>
                    ${generatePersonasOptions(trans.asignado_a)}
                </select>
            </td>
        `;

        tbody.appendChild(tr);
    });

    updateCounts();
}

// Generar opciones de personas dinámicamente
function generatePersonasOptions(selectedValue) {
    return personas.map(persona =>
        `<option value="${escapeHtml(persona.id)}" ${selectedValue === persona.id ? 'selected' : ''}>
            ${escapeHtml(persona.icono)} ${escapeHtml(persona.nombre)}
        </option>`
    ).join('');
}

function assignTransaction(index, assignedTo) {
    if (currentData && currentData.transacciones[index]) {
        currentData.transacciones[index].asignado_a = assignedTo;

        // Actualizar el atributo data del tr
        const tr = document.querySelector(`tr[data-index="${index}"]`);
        if (tr) {
            tr.dataset.assignedTo = assignedTo;
        }

        // Guardar asignaciones automáticamente
        saveAssignments();

        // Recalcular totales
        calculateTotals();

        // Actualizar contadores
        updateCounts();
    }
}

function updateCounts() {
    // Inicializar contadores dinámicamente
    const counts = { todas: 0, sin_asignar: 0 };
    personas.forEach(p => counts[p.id] = 0);

    if (currentData && currentData.transacciones) {
        counts.todas = currentData.transacciones.length;

        currentData.transacciones.forEach(trans => {
            const assignedTo = trans.asignado_a || 'sin_asignar';
            if (counts[assignedTo] !== undefined) {
                counts[assignedTo]++;
            }
        });
    }

    // Actualizar los contadores en la UI
    Object.keys(counts).forEach(key => {
        const span = document.getElementById(`count-${key}`);
        if (span) {
            span.textContent = counts[key];
        }
    });
}

function filterTransactions(filter, event = null) {
    currentFilter = filter;

    // Actualizar botones activos
    document.querySelectorAll('.filter-btn').forEach(btn => {
        btn.classList.remove('active');
    });

    // Si tenemos el evento, usar event.target; si no, buscar el botón por data-filter
    if (event && event.target) {
        event.target.classList.add('active');
    } else {
        const targetBtn = document.querySelector(`.filter-btn[data-filter="${filter}"]`);
        if (targetBtn) targetBtn.classList.add('active');
    }

    // Filtrar filas
    const rows = document.querySelectorAll('#transactionsTable tr');
    rows.forEach(row => {
        if (filter === 'todas') {
            row.classList.remove('hidden');
        } else {
            const assignedTo = row.dataset.assignedTo;
            if (assignedTo === filter) {
                row.classList.remove('hidden');
            } else {
                row.classList.add('hidden');
            }
        }
    });
}

async function calculateTotals() {
    if (!currentData || !currentData.transacciones) {
        return;
    }

    try {
        const response = await fetch('/calculate', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                transacciones: currentData.transacciones
            })
        });

        if (!response.ok) {
            throw new Error('Error al calcular totales');
        }

        const totales = await response.json();
        displayTotals(totales);

    } catch (error) {
        console.error('Error al calcular totales:', error);
    }
}

function displayTotals(totales) {
    const container = document.getElementById('totalsGrid');
    container.innerHTML = '';

    // Generar tarjetas dinámicamente según personas configuradas
    personas.forEach(persona => {
        const data = totales[persona.id];
        if (data) {
            const div = document.createElement('div');
            div.className = `person-total`;
            div.style.borderTop = `4px solid ${persona.color}`;
            div.innerHTML = `
                <h3>${escapeHtml(persona.icono)} ${escapeHtml(persona.nombre)}</h3>
                
                <div class="total-detail">
                    <label>Cargos (Gastos)</label>
                    <div class="value" style="color: var(--danger-color);">
                        S/ ${formatMoney(data.cargos)}
                    </div>
                </div>
                
                <div class="total-detail">
                    <label>Abonos (Pagos)</label>
                    <div class="value" style="color: var(--success-color);">
                        S/ ${formatMoney(data.abonos)}
                    </div>
                </div>
                
                <div class="total-amount">
                    <label>Total a Pagar</label>
                    <div class="value" style="color: ${data.total > 0 ? 'var(--danger-color)' : 'var(--success-color)'};">
                        S/ ${formatMoney(data.total)}
                    </div>
                </div>
            `;
            container.appendChild(div);
        }
    });

    // Agregar resumen de sin asignar si hay
    const sinAsignar = totales.sin_asignar;
    if (sinAsignar && (sinAsignar.cargos > 0 || sinAsignar.abonos > 0)) {
        const div = document.createElement('div');
        div.className = 'person-total';
        div.style.borderColor = 'var(--warning-color)';
        div.innerHTML = `
            <h3>⚠️ Sin Asignar</h3>
            
            <div class="total-detail">
                <label>Cargos</label>
                <div class="value" style="color: var(--danger-color);">
                    S/ ${formatMoney(sinAsignar.cargos)}
                </div>
            </div>
            
            <div class="total-detail">
                <label>Abonos</label>
                <div class="value" style="color: var(--success-color);">
                    S/ ${formatMoney(sinAsignar.abonos)}
                </div>
            </div>
            
            <div class="total-amount">
                <label>Total</label>
                <div class="value" style="color: var(--warning-color);">
                    S/ ${formatMoney(sinAsignar.total)}
                </div>
            </div>
            
            <p style="margin-top: 15px; font-size: 0.85rem; color: var(--text-secondary); font-style: italic;">
                Hay transacciones sin asignar. Asígnalas para un cálculo más preciso.
            </p>
        `;
        container.appendChild(div);
    }
}

function formatMoney(amount) {
    if (amount === undefined || amount === null) {
        return '0.00';
    }
    return Math.abs(amount).toFixed(2).replace(/\B(?=(\d{3})+(?!\d))/g, ',');
}

function resetApp() {
    currentData = null;
    currentFilter = 'todas';
    currentPdfId = null; // Limpiar ID del PDF

    document.getElementById('resultsSection').style.display = 'none';
    document.getElementById('loading').style.display = 'none';
    document.getElementById('uploadSection').style.display = 'block';
    document.getElementById('fileInfo').style.display = 'none';
    document.getElementById('fileInput').value = '';

    // Scroll al inicio
    window.scrollTo({ top: 0, behavior: 'smooth' });
}

/* ===================================
   GESTIÓN DE PERSONAS - MODAL
   =================================== */

function openPersonasModal() {
    const modal = document.getElementById('personasModal');
    modal.classList.add('show');
    loadPersonasList();
}

function closePersonasModal() {
    const modal = document.getElementById('personasModal');
    modal.classList.remove('show');
}

// Cerrar modal al hacer clic fuera de él
window.onclick = function (event) {
    const modal = document.getElementById('personasModal');
    if (event.target === modal) {
        closePersonasModal();
    }
    const editModal = document.getElementById('editDescriptionModal');
    if (event.target === editModal) {
        closeEditDescriptionModal();
    }
}

// Cargar lista de personas en el modal
async function loadPersonasList() {
    const container = document.getElementById('personasListContainer');
    container.innerHTML = '<p style="text-align: center; color: #666;">Cargando...</p>';

    try {
        const response = await fetch('/personas');
        const personasData = await response.json();

        if (personasData.length === 0) {
            container.innerHTML = '<p style="text-align: center; color: #666;">No hay personas registradas</p>';
            return;
        }

        container.innerHTML = '';
        personasData.forEach(persona => {
            const card = document.createElement('div');
            card.className = 'persona-card';
            card.innerHTML = `
                <div class="persona-icon"></div>
                <div class="persona-info">
                    <h4></h4>
                    <span class="persona-id"></span>
                </div>
                <div class="persona-actions">
                    <button class="btn-delete">
                        🗑️ Eliminar
                    </button>
                </div>
            `;
            const iconEl = card.querySelector('.persona-icon');
            iconEl.style.backgroundColor = `${persona.color}20`;
            iconEl.style.color = persona.color;
            iconEl.textContent = persona.icono;
            card.querySelector('h4').textContent = persona.nombre;
            card.querySelector('.persona-id').textContent = `ID: ${persona.id}`;
            const deleteBtn = card.querySelector('.btn-delete');
            deleteBtn.addEventListener('click', () => deletePersona(persona.id, persona.nombre));
            container.appendChild(card);
        });
    } catch (error) {
        console.error('Error cargando personas:', error);
        container.innerHTML = '<p style="text-align: center; color: red;">Error al cargar personas</p>';
    }
}

// Agregar nueva persona
async function addNewPersona(event) {
    event.preventDefault();

    const nombre = document.getElementById('personaNombre').value.trim();
    const icono = document.getElementById('personaIcono').value;
    const color = document.getElementById('personaColor').value;

    if (!nombre) {
        showNotification('Por favor ingresa un nombre', 'warning');
        return;
    }

    // Generar ID único basado en el nombre (minúsculas, sin espacios)
    const id = nombre.toLowerCase().replace(/\s+/g, '_').replace(/[^a-z0-9_]/g, '');

    const nuevaPersona = { id, nombre, icono, color };

    try {
        const response = await fetch('/personas', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(nuevaPersona)
        });

        const result = await response.json();

        if (response.ok) {
            // Limpiar formulario
            document.getElementById('addPersonaForm').reset();
            document.getElementById('personaColor').value = '#1e88e5';

            // Recargar lista de personas
            await loadPersonas();
            loadPersonasList();

            // Actualizar transacciones si hay datos cargados
            if (currentData && currentData.transacciones) {
                displayTransactions(currentData.transacciones);
                calculateTotals();
            }

            showNotification(`Persona "${nombre}" agregada exitosamente`, 'success');
        } else {
            showNotification(`Error: ${result.error || 'No se pudo agregar la persona'}`, 'error');
        }
    } catch (error) {
        console.error('Error agregando persona:', error);
        showNotification('Error al agregar persona', 'error');
    }
}

// Eliminar persona
async function deletePersona(id, nombre) {
    const confirmar = await showConfirm(
        `Las transacciones asignadas a esta persona quedarán sin asignar.`,
        `¿Estás seguro de eliminar a "${nombre}"?`
    );

    if (!confirmar) return;

    try {
        const response = await fetch(`/personas/${id}`, {
            method: 'DELETE'
        });

        const result = await response.json();

        if (response.ok) {
            // Recargar lista de personas
            await loadPersonas();
            loadPersonasList();

            // Actualizar transacciones si hay datos cargados
            if (currentData && currentData.transacciones) {
                // Desasignar transacciones de esta persona
                currentData.transacciones.forEach(trans => {
                    if (trans.asignado_a === id) {
                        trans.asignado_a = 'sin_asignar';
                    }
                });

                displayTransactions(currentData.transacciones);
                calculateTotals();
            }

            showNotification(`Persona "${nombre}" eliminada exitosamente`, 'success');
        } else {
            showNotification(`Error: ${result.error || 'No se pudo eliminar la persona'}`, 'error');
        }
    } catch (error) {
        console.error('Error eliminando persona:', error);
        showNotification('Error al eliminar persona', 'error');
    }
}

/* ===================================
   GENERAR PAGOS - IMÁGENES INDIVIDUALES
   =================================== */

async function generarPagos() {
    // Verificar si hay datos
    if (!currentData || !currentData.transacciones || currentData.transacciones.length === 0) {
        showNotification('No hay transacciones para generar pagos', 'warning');
        return;
    }

    try {
        // Calcular totales primero
        const responseTotales = await fetch('/calculate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ transacciones: currentData.transacciones })
        });

        if (!responseTotales.ok) {
            throw new Error('Error al calcular totales');
        }

        const totales = await responseTotales.json();

        // Verificar si hay personas con montos a pagar
        const personasConPago = Object.keys(totales).filter(
            id => id !== 'sin_asignar' && totales[id].total > 0
        );

        if (personasConPago.length === 0) {
            showNotification('No hay pagos para generar. Todas las personas tienen saldo S/ 0.00', 'info');
            return;
        }

        // Mostrar mensaje de procesamiento
        showNotification(`Generando ${personasConPago.length} imagen(es) de pago...`, 'info');

        // Generar las imágenes
        const responseGenerar = await fetch('/generar-pagos', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                totales: totales,
                personas: personas
            })
        });

        if (!responseGenerar.ok) {
            throw new Error('Error al generar las imágenes');
        }

        const result = await responseGenerar.json();

        if (!result.success || !result.imagenes || result.imagenes.length === 0) {
            showNotification('No se pudieron generar las imágenes de pago', 'error');
            return;
        }

        // Descargar todas las imágenes
        result.imagenes.forEach(img => {
            descargarImagenBase64(img.imagen_base64, img.nombre_archivo);
        });

        // Mostrar mensaje de éxito
        setTimeout(() => {
            showNotification(
                `¡Éxito! Se han generado y descargado ${result.total_generadas} imagen(es) de pago.`,
                'success'
            );
        }, 500);

    } catch (error) {
        console.error('Error generando pagos:', error);
        showNotification('Error al generar las imágenes de pago: ' + error.message, 'error');
    }
}

function descargarImagenBase64(base64Data, nombreArchivo) {
    // Crear un enlace de descarga
    const link = document.createElement('a');
    link.href = 'data:image/jpeg;base64,' + base64Data;
    link.download = nombreArchivo;

    // Simular click para descargar
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
}

/* ===================================
   SISTEMA DE NOTIFICACIONES PERSONALIZADAS
   =================================== */

// Reemplazo de alert() - Muestra notificación personalizada
function showNotification(message, type = 'info') {
    const modal = document.getElementById('notificationModal');
    const icon = document.getElementById('notificationIcon');
    const messageEl = document.getElementById('notificationMessage');

    // Determinar ícono según el tipo
    const icons = {
        success: '✅',
        error: '❌',
        warning: '⚠️',
        info: 'ℹ️'
    };

    icon.textContent = icons[type] || icons.info;
    messageEl.textContent = message;

    modal.classList.add('show');
}

// Cerrar notificación
function closeNotification() {
    const modal = document.getElementById('notificationModal');
    modal.classList.remove('show');
}

// Cerrar con tecla Escape
document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') {
        closeNotification();
        closeConfirmation();
        closePersonasModal();
        closeEditDescriptionModal();
    }
});

// Reemplazo de confirm() - Muestra confirmación personalizada
let confirmCallback = null;

function showConfirm(message, title = '¿Estás seguro?') {
    return new Promise((resolve) => {
        const modal = document.getElementById('confirmModal');
        const titleEl = document.getElementById('confirmTitle');
        const messageEl = document.getElementById('confirmMessage');

        titleEl.textContent = title;
        messageEl.textContent = message;

        modal.classList.add('show');

        confirmCallback = resolve;
    });
}

// Aceptar confirmación
function acceptConfirm() {
    const modal = document.getElementById('confirmModal');
    modal.classList.remove('show');
    if (confirmCallback) {
        confirmCallback(true);
        confirmCallback = null;
    }
}

// Cancelar confirmación
function cancelConfirm() {
    const modal = document.getElementById('confirmModal');
    modal.classList.remove('show');
    if (confirmCallback) {
        confirmCallback(false);
        confirmCallback = null;
    }
}

// Cerrar confirmación
function closeConfirmation() {
    cancelConfirm();
}

// ===== FUNCIONES PARA EDITAR DESCRIPCIONES =====

let currentEditingTransactionIndex = null;

// Abrir modal para editar descripción
function openEditDescriptionModal(transactionIndex) {
    if (!currentData || !currentData.transacciones[transactionIndex]) {
        showNotification('Error: Transacción no encontrada', 'error');
        return;
    }

    currentEditingTransactionIndex = transactionIndex;
    const transaction = currentData.transacciones[transactionIndex];

    // La descripción original es la que se guardó del PDF
    const originalDescription = transaction.descripcion_original || transaction.descripcion;

    // Mostrar en el modal
    document.getElementById('originalDescription').value = originalDescription;
    document.getElementById('newDescription').value = transaction.descripcion;

    // Mostrar modal
    const modal = document.getElementById('editDescriptionModal');
    modal.classList.add('show');

    // Enfocar el campo de nueva descripción
    setTimeout(() => {
        document.getElementById('newDescription').focus();
        document.getElementById('newDescription').select();
    }, 100);
}

// Cerrar modal de edición de descripción
function closeEditDescriptionModal() {
    const modal = document.getElementById('editDescriptionModal');
    modal.classList.remove('show');
    currentEditingTransactionIndex = null;

    // Limpiar campos
    document.getElementById('originalDescription').value = '';
    document.getElementById('newDescription').value = '';
}

// Guardar reemplazo de descripción
async function saveDescriptionReplacement() {
    if (currentEditingTransactionIndex === null) {
        showNotification('Error: No hay transacción seleccionada', 'error');
        return;
    }

    const transaction = currentData.transacciones[currentEditingTransactionIndex];
    const originalDescription = transaction.descripcion_original || transaction.descripcion;
    const newDescription = document.getElementById('newDescription').value.trim();

    if (!newDescription) {
        showNotification('Por favor ingresa una descripción', 'warning');
        return;
    }

    try {
        // Guardar en el servidor
        const response = await fetch('/description-replacements', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                original: originalDescription,
                replacement: newDescription
            })
        });

        const result = await response.json();

        if (result.success) {
            // Actualizar la transacción actual
            transaction.descripcion_original = originalDescription;
            transaction.descripcion = newDescription;

            // Actualizar todas las transacciones con la misma descripción original
            currentData.transacciones.forEach(trans => {
                const transOriginal = trans.descripcion_original || trans.descripcion;
                if (transOriginal === originalDescription) {
                    trans.descripcion_original = originalDescription;
                    trans.descripcion = newDescription;
                }
            });

            // Actualizar la vista
            displayTransactions(currentData.transacciones);

            // Cerrar modal
            closeEditDescriptionModal();

            showNotification('Descripción actualizada correctamente. Se aplicará a todas las transacciones con la misma descripción original.', 'success');
        } else {
            showNotification('Error al guardar: ' + (result.error || 'Error desconocido'), 'error');
        }
    } catch (error) {
        console.error('Error guardando reemplazo:', error);
        showNotification('Error al guardar la descripción', 'error');
    }
}

// Hacer disponibles las funciones globalmente
window.uploadFile = uploadFile;
window.assignTransaction = assignTransaction;
window.filterTransactions = filterTransactions;
window.resetApp = resetApp;
window.openPersonasModal = openPersonasModal;
window.closePersonasModal = closePersonasModal;
window.addNewPersona = addNewPersona;
window.deletePersona = deletePersona;
window.closeNotification = closeNotification;
window.acceptConfirm = acceptConfirm;
window.cancelConfirm = cancelConfirm;
window.generarPagos = generarPagos;
window.openEditDescriptionModal = openEditDescriptionModal;
window.closeEditDescriptionModal = closeEditDescriptionModal;
window.saveDescriptionReplacement = saveDescriptionReplacement;
window.clearSavedAssignments = clearSavedAssignments;
