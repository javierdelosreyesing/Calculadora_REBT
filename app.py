import math
import os
from flask import Flask, request, jsonify, render_template_string, send_file
from weasyprint import HTML

app = Flask(__name__)

# --- TABLAS OFICIALES REBT (Cables XLPE de Cobre bajo Tubo Empotrado) ---
TABLA_IZ_XLPE_mono = {1.5: 15.0, 2.5: 21.0, 4.0: 27.0, 6.0: 36.0, 10.0: 49.0, 16.0: 66.0, 25.0: 87.0, 32.0: 107.0, 50.0: 129.0}
TABLA_IZ_XLPE_tri =  {1.5: 13.0, 2.5: 18.5, 4.0: 24.0, 6.0: 32.0, 10.0: 43.0, 16.0: 57.0, 25.0: 75.0, 32.0: 92.0, 50.0: 110.0}

cuadro_circuitos = []
historial_cc = []  # Mantenemos el orden global en memoria

def ejecutar_formulas_rebt(potencia, longitud, sistema, seccion, magneto, limite_cdt):
    gamma = 48.47  # Conductividad del cobre a temperatura de servicio (90°C)
    
    if "Mono" in str(sistema) or "230" in str(sistema):
        v_linea = 230.0
        intensidad = potencia / v_linea
        caida_v = (2 * potencia * longitud) / (gamma * seccion * v_linea)
        hilos = 3
        iz_cable = TABLA_IZ_XLPE_mono.get(seccion, 0.0)
    else:
        v_linea = 400.0
        intensidad = potencia / (math.sqrt(3) * v_linea)
        caida_v = (potencia * longitud) / (gamma * seccion * v_linea)
        hilos = 5
        iz_cable = TABLA_IZ_XLPE_tri.get(seccion, 0.0)
        
    caida_porcentaje = (caida_v / v_linea) * 100
    
    # Asignación de tubos protectores
    if seccion <= 2.5: tubo = 16 if hilos == 3 else 20
    elif seccion <= 6.0: tubo = 20 if hilos == 3 else 25
    elif seccion <= 16.0: tubo = 25 if hilos == 3 else 32
    elif seccion <= 25.0: tubo = 32 if hilos == 3 else 40
    elif seccion <= 50.0: tubo = 40 if hilos == 3 else 50
    else: tubo = 63

    cumple_sobrecarga = "SÍ" if (intensidad <= magneto <= iz_cable) else "NO"
    cumple_cdt = "SÍ" if (caida_porcentaje <= limite_cdt) else "NO"
    
    return {
        "intensidad": round(intensidad, 2),
        "caida_porcentaje": round(caida_porcentaje, 2),
        "iz_admisible": iz_cable,
        "tubo": tubo,
        "cumple_sobrecarga": cumple_sobrecarga,
        "cumple_cdt": cumple_cdt
    }

def calcular_totales_cuadro():
    p_tot = sum(c['potencia'] for c in cuadro_circuitos)
    p_coinc = 0
    if cuadro_circuitos:
        potencias = [c['potencia'] for c in cuadro_circuitos]
        p_coinc = max(potencias) + 0.7 * (sum(potencias) - max(potencias))
    return round(p_tot, 2), round(p_coinc, 2)
    
# ==========================================
# RUTAS DE LA VISTA 1: CUADRO GENERAL
# ==========================================
@app.route('/')
def home():
    try:
        with open('index.html', 'r', encoding='utf-8') as f:
            html_content = f.read()
        return render_template_string(html_content)
    except Exception as e:
        return "Error en index.html"

@app.route('/calcular', methods=['POST'])
def calcular():
    try:
        data = request.get_json() or {}
        potencia = float(data.get('potencia', 0))
        longitud = float(data.get('longitud', 0))
        sistema = data.get('sistema', 'Monofásico')
        seccion = float(data.get('seccion', 1.5))
        magneto = float(data.get('magneto', 10))
        limite_cdt = float(data.get('limite_cdt', 3.0))
        commit = data.get('commit', False)
        linea_id = data.get('id', 'Línea')
        edit_index = int(data.get('edit_index', -1))

        # 1. Calcular parámetros REBT del conductor
        res = ejecutar_formulas_rebt(potencia, longitud, sistema, seccion, magneto, limite_cdt)

        if commit:
            nueva_linea = {
                "id": linea_id,
                "potencia": potencia,
                "longitud": longitud,
                "sistema": sistema,
                "seccion": seccion,
                "magneto": magneto,
                "limite_cdt": limite_cdt,
                "res_calculados": res
            }
            
            if 0 <= edit_index < len(cuadro_circuitos):
                cuadro_circuitos[edit_index] = nueva_linea
            else:
                cuadro_circuitos.append(nueva_linea)

            # ================================================================
            # 🔄 AUTOMATIZACIÓN: GENERAR ENTRADA EN CORTOCIRCUITOS
            # ================================================================
            # Valores por defecto reglamentarios/coherentes para la aparamenta
            icc_origen_defecto = 6000.0  
            poder_corte_defecto = 6.0 if magneto <= 16 else 10.0 # Curva típica residencial/industrial

            rho_cobre = 0.028  
            x_metro = 0.00008  

            if "Mono" in str(sistema):
                r_linea = (2.0 * rho_cobre * longitud) / seccion
                x_linea = 2.0 * x_metro * longitud
                v_calculo = 230.0
                z_origen = v_calculo / icc_origen_defecto
            else:
                r_linea = (rho_cobre * longitud) / seccion
                x_linea = x_metro * longitud
                v_calculo = 400.0 / math.sqrt(3)
                z_origen = v_calculo / icc_origen_defecto

            z_cable = math.sqrt(r_linea**2 + x_linea**2)
            z_total = z_origen + z_cable

            icc_f_max = v_calculo / z_total if z_total > 0 else icc_origen_defecto
            icc_f_min = icc_f_max * 0.85
            verificacion = "CUMPLE" if (poder_corte_defecto * 1000.0 >= icc_origen_defecto) else "NO CUMPLE"

            res_cc = {
                "resistencia_linea": round(r_linea, 4),
                "icc_final_max": round(icc_f_max, 1),
                "icc_final_min": round(icc_f_min, 1),
                "verificacion_segura": verificacion
            }

            nueva_linea_cc = {
                "id": f"CC - {linea_id}", # Se le añade el prefijo para identificar de dónde vino
                "icc_origen": icc_origen_defecto,
                "longitud": longitud,
                "seccion": seccion,
                "sistema": sistema,
                "poder_corte": poder_corte_defecto,
                "res_calculados": res_cc
            }

            # Si se está editando una línea existente del cuadro, modificamos su CC homólogo
            if 0 <= edit_index < len(historial_cc):
                historial_cc[edit_index] = nueva_linea_cc
            else:
                historial_cc.append(nueva_linea_cc)
            # ================================================================

        p_tot, p_coinc = calcular_totales_cuadro()

        return jsonify({
            "status": "success",
            "res": res,
            "cuadro": cuadro_circuitos,
            "p_tot": p_tot,
            "p_coinc": p_coinc
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400

# ==========================================
# RUTAS DE LA VISTA 2: CORTOCIRCUITO
# ==========================================
@app.route('/cortocircuito')
def vista_cortocircuito():
    try:
        with open('cortocircuito.html', 'r', encoding='utf-8') as f:
            return render_template_string(f.read())
    except Exception as e:
        return "Error cortocircuito.html no encontrado en el directorio raíz", 500

@app.route('/api/calcular_cc', methods=['POST'])
def api_calcular_cc():
    try:
        data = request.get_json() or {}
        linea_id = data.get('id', 'Circuito').strip() or 'Circuito'
        
        icc_origen = float(data.get('icc_origen') or 6000)
        longitud = float(data.get('longitud') or 10)
        seccion = float(data.get('seccion') or 2.5)
        poder_corte_ka = float(data.get('poder_corte') or 6.0)
        sistema = str(data.get('sistema', 'Monofásico'))
        commit = bool(data.get('commit', False))
        
        try:
            edit_index = int(data.get('edit_index', -1))
        except:
            edit_index = -1

        rho_cobre = 0.028  
        x_metro = 0.00008  

        if "Mono" in sistema:
            r_linea = (2.0 * rho_cobre * longitud) / seccion
            x_linea = 2.0 * x_metro * longitud
            v_calculo = 230.0
            z_origen = v_calculo / icc_origen if icc_origen > 0 else 0.038
        else:
            r_linea = (rho_cobre * longitud) / seccion
            x_linea = x_metro * longitud
            v_calculo = 400.0 / math.sqrt(3)
            z_origen = v_calculo / icc_origen if icc_origen > 0 else 0.038

        z_cable = math.sqrt(r_linea**2 + x_linea**2)
        z_total = z_origen + z_cable

        icc_f_max = v_calculo / z_total if z_total > 0 else icc_origen
        icc_f_min = icc_f_max * 0.85

        verificacion = "CUMPLE" if (poder_corte_ka * 1000.0 >= icc_origen) else "NO CUMPLE"

        res_cc = {
            "resistencia_linea": round(r_linea, 4),
            "icc_final_max": round(icc_f_max, 1),
            "icc_final_min": round(icc_f_min, 1),
            "verificacion_segura": verificacion
        }

        if commit:
            nueva_linea = {
                "id": linea_id,
                "icc_origen": icc_origen,
                "longitud": longitud,
                "seccion": seccion,
                "sistema": sistema,
                "poder_corte": poder_corte_ka,
                "res_calculados": res_cc # Sincronizado exactamente con el Frontend
            }
            if 0 <= edit_index < len(historial_cc):
                historial_cc[edit_index] = nueva_linea
            else:
                historial_cc.append(nueva_linea)

        return jsonify({
            "status": "success", 
            "res": res_cc, 
            "historial": historial_cc
        })

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/eliminar', methods=['POST'])
def eliminar():
    try:
        data = request.get_json() or {}
        index_a_borrar = int(data.get('index', -1))
        
        # 1. Borramos de forma segura en la lista de conductores
        if 0 <= index_a_borrar < len(cuadro_circuitos):
            # Guardamos el ID antes de borrar para buscarlo en la otra lista
            id_a_borrar = cuadro_circuitos[index_a_borrar]['id']
            cuadro_circuitos.pop(index_a_borrar)
            
            # 2. Borrado inteligente en cortocircuitos: buscamos por coincidencia de nombre
            # Así evitamos errores si los índices no coinciden exactamente
            id_cc_buscar = f"CC - {id_a_borrar}"
            for i, elemento in enumerate(historial_cc):
                if elemento.get('id') == id_cc_buscar or elemento.get('id') == id_a_borrar:
                    historial_cc.pop(i)
                    break # Salimos del bucle una vez encontrado y eliminado

        p_tot, p_coinc = calcular_totales_cuadro()
        
        return jsonify({
            "status": "success", 
            "cuadro": cuadro_circuitos, 
            "p_tot": p_tot, 
            "p_coinc": p_coinc
        })
    except Exception as e:
        # En caso de cualquier error, devolvemos un estado 400 estructurado
        return jsonify({"status": "error", "message": str(e)}), 400

# ==========================================
# REPORTES E IMPRESIÓN DE MEMORIAS EN PDF
# ==========================================
# ==============================================================================
# 1. REPORTE GENERAL DE CONDUCTORES (VISTA INDEX - VERTICAL Y LIMPIO)
# ==============================================================================
@app.route('/descargar_reporte', methods=['GET'])
def descargar_reporte():
    if not cuadro_circuitos: 
        return "Cuadro vacío", 400
        
    p_tot, p_coinc = calcular_totales_cuadro()
    
    # Construcción de filas mapeando de forma segura tus claves del diccionario
    filas = ""
    for c in cuadro_circuitos:
        res = c.get('res_calculados', {})
        filas += f"""
        <tr>
            <td><strong>{c['id']}</strong></td>
            <td>{c['potencia']:.0f} W</td>
            <td>{c['longitud']:.1f} m</td>
            <td>{c['sistema']}</td>
            <td>{res.get('intensidad', 0.0)} A</td>
            <td><strong>{c['magneto']} A</strong></td>
            <td>{c['seccion']} mm²</td>
            <td>{res.get('iz_admisible', 0.0)} A</td>
            <td>{res.get('caida_porcentaje', 0.0)}%</td>
            <td>Ø {res.get('tubo', 16)} mm</td>
        </tr>
        """
        
    # HTML dedicado y limpio para el Reporte Estándar (A4 Vertical)
    html_reporte = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <style>
            @page {{
                size: A4 portrait;
                margin: 20mm 15mm;
                @bottom-right {{
                    content: "Página " counter(page) " de " counter(pages);
                    font-family: Arial, sans-serif; font-size: 8.5pt; color: #64748b;
                }}
            </style>
            <style>
            body {{ font-family: Arial, sans-serif; color: #1e293b; line-height: 1.5; font-size: 10pt; }}
            .header-banner {{ background-color: #1e293b; color: white; padding: 20px; border-bottom: 4px solid #0f766e; margin-bottom: 25px; }}
            .header-banner h1 {{ margin: 0; font-size: 18pt; }}
            h2 {{ font-size: 13pt; color: #1e293b; border-left: 4px solid #0f766e; padding-left: 8px; margin-top: 20px; }}
            table {{ width: 100%; border-collapse: collapse; margin-top: 12px; font-size: 9pt; }}
            th {{ background-color: #0f766e; color: white; padding: 8px 6px; font-weight: bold; border: 1px solid #0d5c56; text-align: center; }}
            td {{ padding: 7px 6px; border: 1px solid #cbd5e1; text-align: center; }}
            tr:nth-child(even) td {{ background-color: #f8fafc; }}
            .resumen-cajas {{ background-color: #f1f5f9; border-left: 5px solid #1e293b; padding: 12px; margin-top: 20px; }}
        </style>
    </head>
    <body>
        <div class="header-banner">
            <h1>INFORME TÉCNICO DE CONDUCTORES Y CÁLCULOS</h1>
            <p style="margin:4px 0 0 0; font-size:9.5pt; color:#94a3b8;">Resumen Justificativo del Cuadro de Cargas - REBT</p>
        </div>

        <h2>1. Resumen Eléctrico del Cuadro</h2>
        <table>
            <thead>
                <tr>
                    <th>Línea</th>
                    <th>Potencia</th>
                    <th>Longitud</th>
                    <th>Sistema</th>
                    <th>I_b (Carga)</th>
                    <th>PIA</th>
                    <th>Sección</th>
                    <th>I_z (Adm)</th>
                    <th>ΔU (%)</th>
                    <th>Canalización</th>
                </tr>
            </thead>
            <tbody>
                {filas}
            </tbody>
        </table>

        <div class="resumen-cajas">
            <p style="margin: 4px 0;">💡 <strong>Potencia Total Instalada:</strong> {p_tot:,.2f} W</p>
            <p style="margin: 4px 0;">⚡ <strong>Potencia Coincidente Estimada (ITC-BT-25):</strong> <strong>{p_coinc = :,.2f} W</strong></p>
        </div>
    </body>
    </html>
    """
    
    HTML(string=html_reporte).write_pdf("Cuadro_Cargas.pdf")
    return send_file("Cuadro_Cargas.pdf", as_attachment=True)


@app.route('/descargar_reporte_cc', methods=['GET'])
def descargar_reporte_cc():
    if not historial_cc:
        return "<h3>Error: No hay datos de cortocircuito para exportar</h3>", 400

    filas_tabla = ""
    detalles = ""
    for l in historial_cc:
        color_status = '#2ecc71' if l['res_calculados']['verificacion_segura'] == 'CUMPLE' else '#e74c3c'
        filas_tabla += f"""
        <tr>
            <td><strong>{l['id']}</strong></td>
            <td>{l['sistema']}</td>
            <td>{l['seccion']} mm²</td>
            <td>{l['longitud']} m</td>
            <td>{l['icc_origen']:.0f} A</td>
            <td><strong>{l['res_calculados']['icc_final_max']:.0f} A</strong></td>
            <td>{l['res_calculados']['icc_final_min']:.0f} A</td>
            <td>{l['poder_corte']} kA</td>
            <td><strong style="color: {color_status}">{l['res_calculados']['verificacion_segura']}</strong></td>
        </tr>
        """
        detalles += f"""
        <div style="border: 1px solid #cbd5e1; padding: 12px; margin-bottom: 15px; page-break-inside: avoid; border-radius: 4px;">
            <div style="font-weight: bold; color: #e67e22; font-size: 11pt; border-bottom: 1px solid #cbd5e1; padding-bottom: 4px; margin-bottom: 6px;">Línea Evaluada: {l['id']}</div>
            <p style="margin: 3px 0; font-size: 9.5pt;"><strong>Características Físicas:</strong> Conductor de cobre, sección {l['seccion']} mm² | Distribución {l['sistema']} | Longitud de trayecto: {l['longitud']} m.</p>
            <p style="margin: 3px 0; font-size: 9.5pt;"><strong>Parámetros de Impedancia:</strong> Resistencia calculada de la línea: {l['res_calculados']['resistencia_linea']} &Omega;.</p>
            <p style="margin: 3px 0; font-size: 9.5pt;"><strong>Evaluación de Seguridad (ITC-BT-22):</strong> Corriente máxima presunta en origen: {l['icc_origen']:.0f} A. El dispositivo de protección cuenta con un Poder de Corte de <strong>{l['poder_corte']} kA</strong> ({l['poder_corte']*1000:.0f} A).</p>
            <p style="margin: 3px 0; font-size: 9.5pt;"><strong>Resultado Térmico:</strong> Capacidad de interrupción segura ante cortocircuito: <strong>{l['res_calculados']['verificacion_segura']}</strong>.</p>
        </div>
        """

    html_reporte_cc = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <style>
            @page {{ size: A4; margin: 20mm 15mm; }}
            body {{ font-family: Arial, sans-serif; font-size: 10pt; line-height: 1.4; color: #1e293b; }}
            .header {{ background-color: #2c3e50; color: white; padding: 20px; text-align: center; border-bottom: 4px solid #e67e22; margin-bottom: 25px; }}
            h2 {{ color: #2c3e50; border-left: 4px solid #e67e22; padding-left: 8px; margin-top: 20px; }}
            table {{ width: 100%; border-collapse: collapse; margin-top: 10px; margin-bottom: 20px; font-size: 8.5pt; }}
            th {{ background-color: #334155; color: white; padding: 8px; border: 1px solid #475569; }}
            td {{ padding: 8px; border: 1px solid #cbd5e1; text-align: center; }}
            tr:nth-child(even) td {{ background-color: #f8fafc; }}
        </style>
    </head>
    <body>
        <div class="header">
            <h1 style="margin:0; font-size:18pt;">MEMORIA TÉCNICA DE CORTOCIRCUITO</h1>
            <p style="margin:5px 0 0 0; font-size:10pt; color:#cbd5e1;">Justificación de Poder de Corte de Aparamenta - ITC-BT-22 REBT</p>
        </div>
        <h2>1. Resumen de Intensidades de Cortocircuito Calculadas</h2>
        <table>
            <thead>
                <tr>
                    <th>Circuito</th>
                    <th>Red</th>
                    <th>Sección</th>
                    <th>Longitud</th>
                    <th>Icc Origen</th>
                    <th>Icc Final (Máx)</th>
                    <th>Icc Final (Mín)</th>
                    <th>Poder Corte Disp.</th>
                    <th>Resultado</th>
                </tr>
            </thead>
            <tbody>{filas_tabla}</tbody>
        </table>
        <h2>2. Justificación de Impedancias y Cálculos Detallados</h2>
        {detalles}
    </body>
    </html>
    """

    pdf_filename = "Memoria_Cortocircuitos_REBT.pdf"
    try:
        with open("temp_cc.html", "w", encoding="utf-8") as f:
            f.write(html_reporte_cc)
        HTML("temp_cc.html").write_pdf(pdf_filename)
        if os.path.exists("temp_cc.html"):
            os.remove("temp_cc.html")
        return send_file(pdf_filename, as_attachment=True, download_name="Memoria_Cortocircuitos_REBT.pdf")
    except Exception as e:
        return f"<h3>Error al generar PDF:</h3><p>{str(e)}</p>", 500
        
# ==========================================
# BORRAR TODOS LAS ENTRADAS A LA VEZ
# ==========================================

@app.route('/vaciar_cuadro', methods=['POST'])
def vaciar_cuadro():
    try:
        global cuadro_circuitos, historial_cc
        cuadro_circuitos.clear()  # Limpia la lista de conductores
        historial_cc.clear()      # Limpia la lista de cortocircuitos
        
        return jsonify({
            "status": "success", 
            "cuadro": [], 
            "p_tot": 0, 
            "p_coinc": 0
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400


# ==========================================
# VISTA DEL CUADRO UNIFILAR
# ==========================================
@app.route('/unifilar')
def vista_unifilar():
    try:
        # Busca y lee el archivo unifilar.html en la raíz del proyecto
        with open('unifilar.html', 'r', encoding='utf-8') as f:
            html_content = f.read()
        return render_template_string(html_content)
    except Exception as e:
        return f"<h3>Error al cargar el módulo unifilar:</h3><p>{str(e)}</p>", 500
# ==========================================
# EXPORTAR UNIFILAR EN PDF
# ==========================================
import json

@app.route('/exportar_unifilar_pdf', methods=['POST'])
def exportar_unifilar_pdf():
    try:
        # Recuperar los datos enviados desde el cliente
        payload = json.loads(request.form.get('datos', '{}'))
        di = payload.get('di', {})
        iga = payload.get('iga', {})
        lista_diferenciales = payload.get('diferenciales', [])
        mapeo = payload.get('mapeo', {})

        # Calcular potencia coincidente actual del cuadro
        p_total = sum(c["potencia"] for c in cuadro_circuitos) if cuadro_circuitos else 0
        p_coincidente = 0
        if cuadro_circuitos:
            potencias = [c["potencia"] for c in cuadro_circuitos]
            p_coincidente = max(potencias) + 0.7 * (sum(potencias) - max(potencias))

        # Cálculos de la Derivación Individual (ITC-BT-15)
        mat = di.get('material', 'Cu')
        sec = float(di.get('seccion', 10))
        lon = float(di.get('longitud', 15))
        sis = di.get('sistema', 'monofasico')
        
        gamma = 48.47 if mat == "Cu" else 29.56
        v_trabajo = 230 if sis == "monofasico" else 400
        
        if sis == "monofasico":
            cdt_di = (2 * p_coincidente * lon) / (gamma * sec * (v_trabajo ** 2))
        else:
            cdt_di = (p_coincidente * lon) / (gamma * sec * (v_trabajo ** 2))
        cdt_di_porcentaje = cdt_di * 100

        # Construcción del HTML especializado para impresión limpia en PDF (A4)
        html_pdf = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <style>
                @page {{
                    size: A4;
                    margin: 18mm 15mm;
                    @bottom-right {{
                        content: "Página " counter(page) " de " counter(pages);
                        font-family: Arial, sans-serif; font-size: 8pt; color: #64748b;
                    }}
                }}
                body {{ font-family: Arial, sans-serif; color: #1e293b; font-size: 10pt; line-height: 1.5; }}
                .header {{ border-bottom: 3px solid #0f766e; padding-bottom: 10px; margin-bottom: 20px; }}
                .header h1 {{ margin: 0; font-size: 18pt; color: #1e293b; }}
                .section-title {{ font-size: 13pt; color: #0f766e; border-left: 4px solid #0f766e; padding-left: 8px; margin-top: 20px; margin-bottom: 10px; page-break-after: avoid; }}
                .grid-tech {{ width: 100%; border-collapse: collapse; margin-bottom: 15px; }}
                .grid-tech th {{ background: #1e293b; color: white; padding: 6px; font-size: 9pt; border: 1px solid #334155; }}
                .grid-tech td {{ padding: 6px; text-align: center; font-size: 9pt; border: 1px solid #e2e8f0; }}
                .card-di {{ background: #f0fdf4; border: 1px solid #bbf7d0; padding: 12px; margin-bottom: 20px; border-radius: 4px; page-break-inside: avoid; }}
                .bloque-id {{ border: 1px solid #cbd5e1; background: #f8fafc; padding: 12px; margin-bottom: 15px; page-break-inside: avoid; border-radius: 6px; }}
                .bloque-id-title {{ font-weight: bold; font-size: 11pt; color: #1e293b; border-bottom: 1px solid #cbd5e1; padding-bottom: 4px; margin-bottom: 10px; }}
                .table-circuitos {{ width: 100%; border-collapse: collapse; }}
                .table-circuitos th {{ background: #475569; color: white; padding: 5px; font-size: 8.5pt; }}
                .table-circuitos td {{ padding: 5px; font-size: 8.5pt; border: 1px solid #e2e8f0; text-align: center; }}
            </style>
        </head>
        <body>
            <div class="header">
                <h1>MEMORIA TÉCNICA DEL CUADRO UNIFILAR</h1>
                <p style="margin: 3px 0 0 0; font-size: 9pt; color: #64748b;">Justificación Reglamentaria y Despliegue de Circuitos - REBT</p>
            </div>

            <div class="section-title">1. Derivación Individual e Interruptor General (IGA)</div>
            <div class="card-di">
                <strong>Línea de Derivación Individual (ITC-BT-15):</strong> Conductores de {mat} de <strong>{sec} mm²</strong>, Longitud: {lon}m.<br>
                Caída de tensión calculada para la línea: <strong>{cdt_di_porcentaje:.2f}%</strong> 
                ({ '✔ Cumple normativa (< 1.5%)' if cdt_di_porcentaje <= 1.5 else '❌ Excede el límite reglamentario' }).<br>
                <strong>Interruptor General Automático (IGA):</strong> Calibre nominal de <strong>{iga.get('calibre', '40A')}</strong> con Poder de Corte mínimo de {iga.get('poderCorte', '10 kA')}.
            </div>

            <div class="section-title">2. Despliegue de Protecciones Diferenciales y Circuitos Asociados</div>
        """

        # Agrupar los circuitos reales del backend según el ID asignado desde el Front-end
        for diff in lista_diferenciales:
            id_diff = diff['id']
            # Encontrar qué circuitos están asignados a este diferencial en el frontend
            circuitos_hijos = [c for c in cuadro_circuitos if mapeo.get(c['id']) == id_diff or (not mapeo.get(c['id']) and id_diff == lista_diferenciales[0]['id'])]
            
            if not circuitos_hijos:
                continue # Evita imprimir cuadros vacíos en el informe

            html_pdf += f"""
            <div class="bloque-id">
                <div class="bloque-id-title">🛡️ {diff['nombre'].upper()} ({diff['valores']})</div>
                <table class="table-circuitos">
                    <thead>
                        <tr>
                            <th>ID</th>
                            <th>Potencia (W)</th>
                            <th>Sección (mm²)</th>
                            <th>Longitud (m)</th>
                            <th>Ib (A)</th>
                            <th>PIA (A)</th>
                            <th>ΔU (%)</th>
                            <th>Tubo Ø</th>
                        </tr>
                    </thead>
                    <tbody>
            """
            for h in circuitos_hijos:
                res = h.get('res_calculados', {})
                html_pdf += f"""
                        <tr>
                            <td><strong>{h['id']}</strong></td>
                            <td>{h['potencia']} W</td>
                            <td>{h['seccion']} mm²</td>
                            <td>{h['longitud']} m</td>
                            <td>{res.get('intensidad_bajada', 0.0)} A</td>
                            <td><strong>{h['magneto']} A</strong></td>
                            <td>{res.get('caida_porcentaje', 0.0)}%</td>
                            <td>Ø {res.get('diametro_tubo', 16)}</td>
                        </tr>
                """
            html_pdf += """
                    </tbody>
                </table>
            </div>
            """

        html_pdf += f"""
            <div class="section-title">3. Resumen General de Cargas</div>
            <table class="grid-tech">
                <tr>
                    <td><strong>Potencia Total Instalada:</strong> {p_total:,.2f} W</td>
                    <td><strong>Potencia Coincidente (Simultaneada REBT):</strong> {p_coincidente:,.2f} W</td>
                </tr>
            </table>
        </body>
        </html>
        """

        # Compilar usando WeasyPrint de forma directa en memoria
        pdf_filename = "Memoria_Unifilar_Avanzada.pdf"
        HTML(string=html_pdf).write_pdf(pdf_filename)
        
        return send_file(pdf_filename, as_attachment=True, download_name="Memoria_Unifilar_REBT.pdf")
    except Exception as e:
        return f"<h3>Error al exportar diagrama unifilar a PDF:</h3><p>{str(e)}</p>", 500
# ==========================================
# CALCULO DE TIERRAS
# ==========================================
# NUEVA RUTA PARA RENDERIZAR LA PÁGINA DE TIERRA
@app.route('/tierra', methods=['GET'])
def pagina_tierra():
    # Buscamos el archivo tierra.html en la misma carpeta que app.py
    ruta_archivo = os.path.join(os.path.dirname(__file__), 'tierra.html')
    
    # Si por algún motivo no se encuentra el archivo en la carpeta, te avisará con este mensaje
    if not os.path.exists(ruta_archivo):
        return f"<h3>Error: No se encuentra el archivo 'tierra.html' en la carpeta raíz.</h3><p>Ruta buscada: {ruta_archivo}</p>", 404
        
    # Lee el archivo HTML y lo sirve directamente al navegador igual que los anteriores
    with open(ruta_archivo, 'r', encoding='utf-8') as f:
        html_contenido = f.read()
        
    return html_contenido
    
@app.route('/calcular_tierra', methods=['POST'])
def calcular_tierra():
    data = request.json
    tipo_electrodo = data.get('tipo', 'pica') # 'pica' o 'conductor'
    resistividad = float(data.get('resistividad', 100)) # ohm-m
    longitud = float(data.get('longitud', 2)) # metros (largo pica o cable)
    num_picas = int(data.get('num_picas', 1))
    
    # Fórmulas oficiales del REBT / Guía Técnica
    if tipo_electrodo == 'pica':
        # Resistencia de una pica estándar: R = ρ / L
        # Si hay varias picas en paralelo (simplificado separadas una distancia idónea): R = ρ / (N * L)
        resistencia = resistividad / (num_picas * longitud)
    else:
        # Resistencia de conductor horizontal enterrado: R = 2 * ρ / L
        resistencia = (2 * resistividad) / longitud
        
    # Verificación de seguridad (Para viviendas habitualmente se busca R < 15 o 37 Ohmios según el ID)
    cumple = resistencia <= 37.0 
    
    return jsonify({
        'resistencia': round(resistencia, 2),
        'cumple': cumple,
        'mensaje': "✔ Resistencia óptima" if cumple else "⚠ Resistencia alta: Añade más picas o longitud"
    })

if __name__ == '__main__':
    # Captura el puerto que le asigne el servidor en internet, por defecto usa el 5000 si estás en local
    puerto = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=puerto)
