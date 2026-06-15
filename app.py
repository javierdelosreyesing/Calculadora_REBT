import math
import os
import json
import datetime
from flask import Flask, request, jsonify, render_template_string, send_file
from flask import session, redirect, url_for
from flask_cors import CORS
from weasyprint import HTML
from docxtpl import DocxTemplate
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from werkzeug.security import generate_password_hash, check_password_hash


app = Flask(__name__)

# --- TABLAS OFICIALES REBT (Cables XLPE de Cobre bajo Tubo Empotrado) ---
TABLA_IZ_XLPE_mono = {1.5: 15.0, 2.5: 21.0, 4.0: 27.0, 6.0: 36.0, 10.0: 49.0, 16.0: 66.0, 25.0: 87.0, 35.0: 107.0, 50.0: 129.0}
TABLA_IZ_XLPE_tri =  {1.5: 13.0, 2.5: 18.5, 4.0: 24.0, 6.0: 32.0, 10.0: 43.0, 16.0: 57.0, 25.0: 75.0, 35.0: 92.0, 50.0: 110.0}

cuadro_circuitos = []
historial_cc = []  # Mantenemos el orden global en memoria

# Estilos CSS unificados de alta calidad para WeasyPrint (Impresión Corporativa)
CSS_ESTILO_REPORTE = """
@page {
    size: A4 portrait;
    margin: 20mm 15mm 20mm 15mm;
    @bottom-right {
        content: "Página " counter(page) " de " counter(pages);
        font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
        font-size: 8.5pt;
        color: #64748b;
    }
}
body {
    font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
    color: #1e293b;
    line-height: 1.5;
    font-size: 10pt;
}
.header-banner {
    background-color: #1e293b;
    color: white;
    padding: 24px;
    border-bottom: 5px solid #0f766e;
    margin-bottom: 25px;
    border-radius: 4px;
}
.header-banner h1 {
    margin: 0;
    font-size: 18pt;
    letter-spacing: 0.5px;
    text-transform: uppercase;
}
.header-banner p {
    margin: 6px 0 0 0;
    font-size: 10pt;
    color: #94a3b8;
}
h2 {
    font-size: 13pt;
    color: #0f766e;
    border-left: 4.5px solid #0f766e;
    padding-left: 10px;
    margin-top: 25px;
    margin-bottom: 12px;
    page-break-after: avoid;
}
.ficha {
    background-color: #f8fafc;
    border: 1px solid #e2e8f0;
    border-left: 4px solid #1e293b;
    padding: 14px;
    margin-bottom: 20px;
    border-radius: 4px;
    page-break-inside: avoid;
}
.ficha p {
    margin: 5px 0;
    font-size: 9.5pt;
}
table {
    width: 100%;
    border-collapse: collapse;
    margin-top: 10px;
    margin-bottom: 20px;
    font-size: 9pt;
    page-break-inside: auto;
}
tr {
    page-break-inside: avoid;
    page-break-after: auto;
}
th {
    background-color: #0f766e;
    color: white;
    padding: 9px 6px;
    font-weight: bold;
    border: 1px solid #0d5c56;
    text-align: center;
    font-size: 8.5pt;
    text-transform: uppercase;
}
td {
    padding: 8px 6px;
    border: 1px solid #cbd5e1;
    text-align: center;
}
tr:nth-child(even) td {
    background-color: #f8fafc;
}
.badge-cumple {
    color: #16a34a;
    font-weight: bold;
}
.badge-nocumple {
    color: #dc2626;
    font-weight: bold;
}
.resumen-cajas {
    background-color: #f1f5f9;
    border: 1px solid #cbd5e1;
    border-left: 5px solid #0f766e;
    padding: 14px;
    margin-top: 20px;
    border-radius: 4px;
    page-break-inside: avoid;
}
"""
# ==========================================================================
# ENLAZADO DE MÓDULOS Y PÁGINA INDICE (LOGIN & DASHBOARD)
# ==========================================================================

@app.route('/')
def inicio_plataforma():
    """Ruta raíz que despacha el portal de bienvenida e inicio"""
    try:
        ruta_archivo = os.path.join(os.path.dirname(__file__), 'indice.html')
        with open(ruta_archivo, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        return f"<h3>Error crítico al cargar el archivo 'indice.html':</h3><p>{str(e)}</p>", 500

# 1. CLAVE SECRETA DEL SERVIDOR (Crucial para encriptar las cookies de sesión)
# En producción, usa algo indescifrable como: os.urandom(24)
app.secret_key = 'super_secreto_codigo_ingenieria_rebt_2026'

# 2. CONFIGURACIÓN DE SEGURIDAD MÍNIMA PARA LAS COOKIES
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,  # Impide que scripts maliciosos (XSS) roben la sesión
    SESSION_COOKIE_SAMESITE='Lax', # Protección básica contra ataques CSRF
)

# 3. FILTRO / TOKEN DE REGISTRO (Solo quien conozca este código puede crear cuentas)
CLAVE_REGISTRO_CORPORATIVA = "REBT_2026_PRO"

USUARIOS_FILE = os.path.join(os.path.dirname(__file__), 'usuarios.json')

USUARIOS_FILE = os.path.join(os.path.dirname(__file__), 'usuarios.json')

def cargar_usuarios():
    """Lee el JSON de usuarios y fuerza el hasheo si detecta texto plano"""
    if not os.path.exists(USUARIOS_FILE):
        default = {"admin": generate_password_hash("1234")}
        with open(USUARIOS_FILE, 'w', encoding='utf-8') as f:
            json.dump(default, f, indent=4)
        return default
    
    with open(USUARIOS_FILE, 'r', encoding='utf-8') as f:
        try:
            datos = json.load(f)
        except Exception:
            datos = {"admin": "1234"} # Fallback si el JSON quedó corrupto

    # AUTO-REPARACIÓN CRUCIAL:
    # Si la contraseña no empieza con el prefijo de hash oficial de Werkzeug, 
    # significa que está en texto plano. La hasheamos y guardamos en caliente.
    cambios = False
    for usuario, clave in datos.items():
        if not (clave.startswith("scrypt:") or clave.startswith("pbkdf2:") or clave.startswith("sha256:")):
            datos[usuario] = generate_password_hash(clave)
            cambios = True
            
    if cambios:
        with open(USUARIOS_FILE, 'w', encoding='utf-8') as f:
            json.dump(datos, f, indent=4)
            
    return datos


# === API DE LOGIN BLINDADA Y REPARADA ===
@app.route('/api/login', methods=['POST'])
def api_autenticacion():
    try:
        datos = request.get_json()
        if not datos:
            return jsonify({"status": "error", "message": "No se recibieron datos JSON"}), 400
            
        usuario_ingresado = datos.get("usuario", "").strip()
        clave_ingresada = datos.get("clave", "").strip()

        if not usuario_ingresado or not clave_ingresada:
            return jsonify({"status": "error", "message": "Campos incompletos"}), 400

        # Al llamar a cargar_usuarios() garantizamos que todo en el archivo .json esté hasheado correctamente
        lista_usuarios = cargar_usuarios()

        if usuario_ingresado in lista_usuarios:
            hash_almacenado = lista_usuarios[usuario_ingresado]
            # Verificación criptográfica oficial
            if check_password_hash(hash_almacenado, clave_ingresada):
                session['usuario'] = usuario_ingresado # Sesión segura en servidor
                return jsonify({"status": "success", "message": "Acceso autorizado"}), 200

        return jsonify({"status": "error", "message": "Usuario o contraseña incorrectos"}), 401
            
    except Exception as e:
        return jsonify({"status": "error", "message": f"Error interno en login: {str(e)}"}), 500

# === API 2: REGISTRO SEGURO CON FILTRO CORPORATIVO Y HASHING ===
@app.route('/api/registrar-usuario', methods=['POST'])
def api_registrar_usuario():
    """API para registrar nuevos usuarios ingenieros con hash seguro y JSON limpio"""
    try:
        datos = request.get_json()
        if not datos:
            return jsonify({"status": "error", "message": "No se recibieron datos"}), 400

        nuevo_usuario = datos.get("usuario", "").strip()
        nueva_clave = datos.get("clave", "").strip()
        token_verificacion = datos.get("token_corporativo", "").strip()

        # 1. Validación del token corporativo privado
        if token_verificacion != CLAVE_REGISTRO_CORPORATIVA:
            return jsonify({"status": "error", "message": "Código corporativo incorrecto."}), 403

        # 2. Validación de longitudes
        if not nuevo_usuario or len(nueva_clave) < 6:
            return jsonify({"status": "error", "message": "El usuario no puede estar vacío y la clave debe tener mínimo 6 caracteres."}), 400

        # 3. Cargar usuarios existentes de forma segura
        usuarios = cargar_usuarios()

        # 4. Evitar duplicados
        if nuevo_usuario in usuarios:
            return jsonify({"status": "error", "message": "Este nombre de usuario ya está registrado."}), 400

        # 5. Hashear la contraseña nueva antes de guardarla
        usuarios[nuevo_usuario] = generate_password_hash(nueva_clave)

        # 6. ESCRITURA ESTRICTA Y LIMPIA EN EL JSON (Evita el error de comillas)
        with open(USUARIOS_FILE, 'w', encoding='utf-8') as f:
            json.dump(usuarios, f, indent=4, ensure_ascii=False)

        return jsonify({"status": "success", "message": "Usuario registrado con éxito."}), 200

    except Exception as e:
        return jsonify({"status": "error", "message": f"Error en el registro: {str(e)}"}), 500

# === API 3: LOGOUT SEGURO EN SERVIDOR ===
@app.route('/api/logout', methods=['POST'])
def api_logout():
    session.pop('usuario', None) # Destruye la sesión del servidor
    return jsonify({"status": "success"}), 200

# === PROTECCIÓN DE RUTAS INTERNAS (MIDDLEWARE DE SEGURIDAD) ===
# Modifica tus rutas existentes para que verifiquen si hay una sesión activa en el servidor:


@app.route('/configurador')
def abrir_modulo_mtd():
    if 'usuario' not in session:
        return redirect(url_for('inicio_plataforma'))
    try:
        # 1. Capturamos el ID del proyecto desde la URL (?id=proy_xxxx)
        id_proyecto = request.args.get('id', '').strip()

        ruta_archivo = os.path.join(os.path.dirname(__file__), 'memoria.html')
        with open(ruta_archivo, 'r', encoding='utf-8') as f:
            contenido = f.read()
        
        # 2. Inyectamos tanto el usuario como el id_proyecto en el HTML
        return render_template_string(
            contenido, 
            usuario=session['usuario'], 
            id_proyecto=id_proyecto
        )
    except Exception as e:
        return f"<h3>Error:</h3><p>{str(e)}</p>", 500

@app.route('/calculos')
def abrir_modulo_calculos():
    if 'usuario' not in session:
        return redirect(url_for('inicio_plataforma'))
    try:
    # 1. Capturamos el ID del proyecto desde la URL (?id=proy_xxxx)
        id_proyecto = request.args.get('id', '').strip()
        
        ruta_archivo = os.path.join(os.path.dirname(__file__), 'calculos.html')
        with open(ruta_archivo, 'r', encoding='utf-8') as f:
            contenido = f.read()
            
        return render_template_string(
                contenido, 
                usuario=session['usuario'],
                id_proyecto=id_proyecto
                )
    except Exception as e:
        return f"<h3>Error:</h3><p>{str(e)}</p>", 500

@app.route('/seguridad_salud')
def abrir_modulo_seguridad():
    if 'usuario' not in session:
        return redirect(url_for('inicio_plataforma'))
    try:
        ruta_archivo = os.path.join(os.path.dirname(__file__), 'seguridad.html')
        with open(ruta_archivo, 'r', encoding='utf-8') as f:
            contenido = f.read()
        return render_template_string(contenido, usuario=session['usuario'])
    except Exception as e:
        return f"<h3>Error:</h3><p>{str(e)}</p>", 500

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
        edit_calculos = int(data.get('edit_calculos', -1))

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
            
            if 0 <= edit_calculos < len(cuadro_circuitos):
                cuadro_circuitos[edit_calculos] = nueva_linea
            else:
                cuadro_circuitos.append(nueva_linea)

            # ================================================================
            # 🔄 AUTOMATIZACIÓN: GENERAR ENTRADA EN CORTOCIRCUITOS
            # ================================================================
            icc_origen_defecto = 6000.0  
            poder_corte_defecto = 6.0 if magneto <= 16 else 10.0

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
                "id": f"CC - {linea_id}",
                "icc_origen": icc_origen_defecto,
                "longitud": longitud,
                "seccion": seccion,
                "sistema": sistema,
                "poder_corte": poder_corte_defecto,
                "res_calculados": res_cc
            }

            if 0 <= edit_calculos < len(historial_cc):
                historial_cc[edit_calculos] = nueva_linea_cc
            else:
                historial_cc.append(nueva_linea_cc)

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
    # 🔒 CORTAFUEGOS: Si no hay sesión activa en el servidor, rebota al inicio
    if 'usuario' not in session:
        return redirect(url_for('inicio_plataforma'))
        
    try:
        # Usamos os.path.join para evitar fallos de rutas según dónde ejecutes el script
        ruta_archivo = os.path.join(os.path.dirname(__file__), 'cortocircuito.html')
        
        with open(ruta_archivo, 'r', encoding='utf-8') as f:
            contenido = f.read()
            
        # 🌟 SEGURA Y DINÁMICA: Enviamos el HTML procesando el usuario de la sesión
        return render_template_string(contenido, usuario=session['usuario'])
        
    except Exception as e:
        return "Error: cortocircuito.html no encontrado o ilegible en el servidor", 500

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
            edit_calculos = int(data.get('edit_calculos', -1))
        except:
            edit_calculos = -1

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
                "res_calculados": res_cc
            }
            if 0 <= edit_calculos < len(historial_cc):
                historial_cc[edit_calculos] = nueva_linea
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
        calculos_a_borrar = int(data.get('calculos', -1))
        
        if 0 <= calculos_a_borrar < len(cuadro_circuitos):
            id_a_borrar = cuadro_circuitos[calculos_a_borrar]['id']
            cuadro_circuitos.pop(calculos_a_borrar)
            
            id_cc_buscar = f"CC - {id_a_borrar}"
            for i, elemento in enumerate(historial_cc):
                if elemento.get('id') == id_cc_buscar or elemento.get('id') == id_a_borrar:
                    historial_cc.pop(i)
                    break

        p_tot, p_coinc = calcular_totales_cuadro()
        
        return jsonify({
            "status": "success", 
            "cuadro": cuadro_circuitos, 
            "p_tot": p_tot, 
            "p_coinc": p_coinc
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400

# ==============================================================================
# 1. REPORTE GENERAL DE CONDUCTORES (VISTA calculos)
# ==============================================================================
@app.route('/descargar_reporte', methods=['GET'])
def descargar_reporte():
    if not cuadro_circuitos: 
        return "Cuadro vacío", 400
        
    p_tot, p_coinc = calcular_totales_cuadro()
    
    filas = ""
    for c in cuadro_circuitos:
        res = c.get('res_calculados', {})
        cls_sobrecarga = "badge-cumple" if res.get('cumple_sobrecarga') == "SÍ" else "badge-nocumple"
        cls_cdt = "badge-cumple" if res.get('cumple_cdt') == "SÍ" else "badge-nocumple"
        
        filas += f"""
        <tr>
            <td><strong>{c['id']}</strong></td>
            <td>{c['potencia']:.0f} W</td>
            <td>{c['longitud']:.1f} m</td>
            <td>{c['sistema']}</td>
            <td>{res.get('intensidad', 0.0)} A</td>
            <td><strong>{c['magneto']} A</strong></td>
            <td>{c['seccion']} mm²</td>
            <td>{res.get('iz_admisible', 0.0)} A <br><span class="{cls_sobrecarga}">({res.get('cumple_sobrecarga')})</span></td>
            <td>{res.get('caida_porcentaje', 0.0)}% <br><span class="{cls_cdt}">({res.get('cumple_cdt')})</span></td>
            <td>Ø {res.get('tubo', 16)} mm</td>
        </tr>
        """
        
    html_reporte = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <style>{CSS_ESTILO_REPORTE}</style>
    </head>
    <body>
        <div class="header-banner">
            <h1>Informe Técnico de Conductores y Carga</h1>
            <p>Resumen Justificativo del Cuadro Eléctrico General de Distribución - REBT</p>
        </div>

        <h2>1. Resumen Eléctrico del Cuadro</h2>
        <table>
            <thead>
                <tr>
                    <th>Línea ID</th>
                    <th>Potencia</th>
                    <th>Longitud</th>
                    <th>Sistema</th>
                    <th>Ib (Carga)</th>
                    <th>PIA Protec.</th>
                    <th>Sección</th>
                    <th>Iz (Admisible)</th>
                    <th>ΔU Caída (%)</th>
                    <th>Canalización</th>
                </tr>
            </thead>
            <tbody>
                {filas}
            </tbody>
        </table>

        <h2>2. Totales Simultaneados</h2>
        <div class="resumen-cajas">
            <p>💡 <strong>Potencia Total Instalada:</strong> {p_tot:,.2f} W</p>
            <p>⚡ <strong>Potencia Coincidente Estimada (ITC-BT-25):</strong> <strong>{p_coinc:,.2f} W</strong></p>
        </div>
    </body>
    </html>
    """
    
    HTML(string=html_reporte).write_pdf("Cuadro_Cargas.pdf")
    return send_file("Cuadro_Cargas.pdf", as_attachment=True)

# ==============================================================================
# 2. REPORTE DE CORTOCIRCUITO (VISTA CORTOCIRCUITO)
# ==============================================================================
@app.route('/descargar_reporte_cc', methods=['GET'])
def descargar_reporte_cc():
    if not historial_cc:
        return "<h3>Error: No hay datos de cortocircuito para exportar</h3>", 400

    filas_tabla = ""
    detalles = ""
    for l in historial_cc:
        res = l.get('res_calculados', {})
        cumple_seguro = res.get('verificacion_segura', 'NO CUMPLE')
        cls_status = 'badge-cumple' if cumple_seguro == 'CUMPLE' else 'badge-nocumple'
        
        filas_tabla += f"""
        <tr>
            <td><strong>{l['id']}</strong></td>
            <td>{l['sistema']}</td>
            <td>{l['seccion']} mm²</td>
            <td>{l['longitud']} m</td>
            <td>{l['icc_origen']:.0f} A</td>
            <td><strong>{res.get('icc_final_max', 0.0):.0f} A</strong></td>
            <td>{res.get('icc_final_min', 0.0):.0f} A</td>
            <td>{l['poder_corte']} kA</td>
            <td><strong class="{cls_status}">{cumple_seguro}</strong></td>
        </tr>
        """
        detalles += f"""
        <div class="ficha">
            <div style="font-weight: bold; color: #0f766e; font-size: 11pt; border-bottom: 1px solid #cbd5e1; padding-bottom: 4px; margin-bottom: 6px;">Circuito: {l['id']}</div>
            <p><strong>Configuración Física:</strong> Conductor de Cobre | Sección {l['seccion']} mm² | Distribución {l['sistema']} | Longitud total: {l['longitud']} m.</p>
            <p><strong>Parámetros de Impedancia:</strong> Resistencia calculada de la línea: {res.get('resistencia_linea', 0.0)} &Omega;.</p>
            <p><strong>Evaluación de Seguridad (ITC-BT-22):</strong> Corriente máxima presunta en origen: {l['icc_origen']:.0f} A. El dispositivo dispone de un Poder de Corte de <strong>{l['poder_corte']} kA</strong> ({l['poder_corte']*1000:.0f} A).</p>
            <p><strong>Resultado Técnico:</strong> Capacidad de interrupción de cortocircuito garantizada de manera segura: <strong class="{cls_status}">{cumple_seguro}</strong>.</p>
        </div>
        """

    html_reporte_cc = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <style>{CSS_ESTILO_REPORTE}</style>
    </head>
    <body>
        <div class="header-banner" style="background-color: #2c3e50; border-bottom: 5px solid #e67e22;">
            <h1>Memoria Técnica de Cortocircuito</h1>
            <p>Verificación Reglamentaria del Poder de Corte de la Aparamenta - ITC-BT-22 REBT</p>
        </div>
        
        <h2>1. Resumen de Intensidades de Cortocircuito Calculadas</h2>
        <table>
            <thead>
                <tr>
                    <th>Circuito ID</th>
                    <th>Red</th>
                    <th>Sección</th>
                    <th>Longitud</th>
                    <th>Icc Origen</th>
                    <th>Icc Final (Máx)</th>
                    <th>Icc Final (Mín)</th>
                    <th>Poder Corte PIA</th>
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

@app.route('/vaciar_cuadro', methods=['POST'])
def vaciar_cuadro():
    try:
        global cuadro_circuitos, historial_cc
        cuadro_circuitos.clear()
        historial_cc.clear()
        return jsonify({"status": "success", "cuadro": [], "p_tot": 0, "p_coinc": 0})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400

@app.route('/unifilar')
def vista_unifilar():
    # 🔒 CORTAFUEGOS: Si no hay una sesión abierta en el servidor, rebota al inicio
    if 'usuario' not in session:
        return redirect(url_for('inicio_plataforma'))
        
    try:
        # Usamos os.path.join para que la ruta sea robusta en cualquier entorno
        ruta_archivo = os.path.join(os.path.dirname(__file__), 'unifilar.html')
        
        with open(ruta_archivo, 'r', encoding='utf-8') as f:
            html_content = f.read()
            
        # 🌟 DINÁMICA Y PROTEGIDA: Mandamos el HTML procesando el {{ usuario }} de la sesión
        return render_template_string(html_content, usuario=session['usuario'])
        
    except Exception as e:
        return f"<h3>Error al cargar el módulo unifilar:</h3><p>{str(e)}</p>", 500

# ==============================================================================
# 3. REPORTE DEL DIAGRAMA UNIFILAR (VISTA UNIFILAR - CORREGIDAS CLAVES)
# ==============================================================================
@app.route('/exportar_unifilar_pdf', methods=['POST'])
def exportar_unifilar_pdf():
    try:
        payload = json.loads(request.form.get('datos', '{}'))
        di = payload.get('di', {})
        iga = payload.get('iga', {})
        lista_diferenciales = payload.get('diferenciales', [])
        mapeo = payload.get('mapeo', {})

        p_total = sum(c["potencia"] for c in cuadro_circuitos) if cuadro_circuitos else 0
        p_coincidente = 0
        if cuadro_circuitos:
            potencias = [c["potencia"] for c in cuadro_circuitos]
            p_coincidente = max(potencias) + 0.7 * (sum(potencias) - max(potencias))

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

        html_pdf = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <style>{CSS_ESTILO_REPORTE}</style>
        </head>
        <body>
            <div class="header-banner">
                <h1>Memoria Técnica del Cuadro Unifilar</h1>
                <p>Configuración Estructural de Protecciones y Despliegue de Líneas Interiores - REBT</p>
            </div>

            <h2>1. Derivación Individual e Interruptor General (IGA)</h2>
            <div class="ficha">
                <p>⚡ <strong>Línea de Derivación Individual (ITC-BT-15):</strong> Conductores de {mat} de <strong>{sec} mm²</strong>, Longitud de trayecto: {lon} m.</p>
                <p>📉 <strong>Caída de tensión calculada en DI:</strong> <strong>{cdt_di_porcentaje:.2f}%</strong> 
                ({ '✔ Cumple normativa (< 1.5%)' if cdt_di_porcentaje <= 1.5 else '❌ Excede el límite reglamentario' }).</p>
                <p>🛡️ <strong>Interruptor General Automático (IGA):</strong> Calibre nominal de <strong>{iga.get('calibre', '40A')}</strong> con Poder de Corte mínimo de {iga.get('poderCorte', '10 kA')}.</p>
            </div>

            <h2>2. Despliegue de Protecciones Diferenciales y Circuitos</h2>
        """

        for diff in lista_diferenciales:
            id_diff = diff['id']
            circuitos_hijos = [c for c in cuadro_circuitos if mapeo.get(c['id']) == id_diff or (not mapeo.get(c['id']) and id_diff == lista_diferenciales[0]['id'])]
            
            if not circuitos_hijos:
                continue

            html_pdf += f"""
            <div style="background: #fdfdfd; border: 1px solid #cbd5e1; padding: 12px; margin-bottom: 15px; page-break-inside: avoid; border-radius: 4px;">
                <div style="font-weight: bold; font-size: 11pt; color: #1e293b; border-bottom: 2px solid #0f766e; padding-bottom: 4px; margin-bottom: 10px;">🛡️ INTERRUPTOR DIFERENCIAL: {diff['nombre'].upper()} ({diff['valores']})</div>
                <table style="margin-bottom:0px;">
                    <thead>
                        <tr>
                            <th>Línea ID</th>
                            <th>Potencia (W)</th>
                            <th>Sección (mm²)</th>
                            <th>Longitud (m)</th>
                            <th>Ib (Carga)</th>
                            <th>PIA (A)</th>
                            <th>ΔU Caída (%)</th>
                            <th>Canalización Ø</th>
                        </tr>
                    </thead>
                    <tbody>
            """
            for h in circuitos_hijos:
                res = h.get('res_calculados', {})
                html_pdf += f"""
                        <tr>
                            <td><strong>{h['id']}</strong></td>
                            <td>{h['potencia']:.0f} W</td>
                            <td>{h['seccion']} mm²</td>
                            <td>{h['longitud']:.1f} m</td>
                            <td>{res.get('intensidad', 0.0)} A</td>
                            <td><strong>{h['magneto']} A</strong></td>
                            <td>{res.get('caida_porcentaje', 0.0)}%</td>
                            <td>Ø {res.get('tubo', 16)} mm</td>
                        </tr>
                """
            html_pdf += """
                    </tbody>
                </table>
            </div>
            """

        html_pdf += f"""
            <h2>3. Balance General de Potencias del Cuadro</h2>
            <div class="resumen-cajas" style="background-color: #f8fafc;">
                <p>⚙️ <strong>Potencia Total Instalada en Bornes:</strong> {p_total:,.2f} W</p>
                <p>⚡ <strong>Potencia Coincidente Simultaneada (REBT):</strong> <strong>{p_coincidente:,.2f} W</strong></p>
            </div>
        </body>
        </html>
        """

        pdf_filename = "Memoria_Unifilar_Avanzada.pdf"
        HTML(string=html_pdf).write_pdf(pdf_filename)
        return send_file(pdf_filename, as_attachment=True, download_name="Memoria_Unifilar_REBT.pdf")
    except Exception as e:
        return f"<h3>Error al exportar unifilar a PDF:</h3><p>{str(e)}</p>", 500

# ==========================================
# CALCULO DE TIERRAS
# ==========================================
@app.route('/tierra', methods=['GET'])
def pagina_tierra():
    # 🔒 EL CORTAFUEGOS: Si no hay un usuario validado en el servidor, rebota al login
    if 'usuario' not in session:
        return redirect(url_for('inicio_plataforma'))
    
    try:
        ruta_archivo = os.path.join(os.path.dirname(__file__), 'tierra.html')
        if not os.path.exists(ruta_archivo):
            return f"<h3>Error: No se encuentra el archivo 'tierra.html'</h3>", 404
            
        with open(ruta_archivo, 'r', encoding='utf-8') as f:
            contenido = f.read()
            
        # 🌟 DINÁMICO: Procesamos la plantilla e inyectamos el usuario activo
        return render_template_string(contenido, usuario=session['usuario'])
        
    except Exception as e:
        return f"<h3>Error al abrir el módulo de puesta a tierra:</h3><p>{str(e)}</p>", 500
    
@app.route('/calcular_tierra', methods=['POST'])
def calcular_tierra():
    data = request.json
    tipo_electrodo = data.get('tipo', 'pica')
    resistividad = float(data.get('resistividad', 100))
    longitud = float(data.get('longitud', 2))
    num_picas = int(data.get('num_picas', 1))
    
    if tipo_electrodo == 'pica':
        resistencia = resistividad / (num_picas * longitud)
    else:
        resistencia = (2 * resistividad) / longitud
        
    cumple = resistencia <= 37.0 
    return jsonify({
        'resistencia': round(resistencia, 2),
        'cumple': cumple,
        'mensaje': "✔ Resistencia óptima (<37 Ω)" if cumple else "⚠ Resistencia alta: Añade más picas o longitud"
    })
@app.route('/api/obtener_circuitos', methods=['GET'])
def obtener_circuitos():
    global cuadro_circuitos
    # Devolvemos el array de circuitos directamente como JSON
    return jsonify({
        'status': 'success',
        'circuitos': cuadro_circuitos
    })
    
@app.route('/calcular_acometida', methods=['POST'])
def calcular_acometida():
    data = request.json
    potencia = float(data.get('potencia', 9200)) # W
    longitud = float(data.get('longitud', 10))   # metros
    sistema = data.get('sistema', 'monofasico')  # 'monofasico' o 'trifasico'
    
    tension = 230.0 if sistema == 'monofasico' else 400.0
    cos_phi = 1.0  # Habitual en cálculos de previsión de cargas generales
    conductividad = 56.0 # Cobre
    
    # 1. Cálculo de la Intensidad (Ib)
    if sistema == 'monofasico':
        intensidad = potencia / tension
        factor_cdt = 2.0
    else:
        intensidad = potencia / (math.sqrt(3) * tension * cos_phi)
        factor_cdt = 1.0

    # Límite normativo de caída de tensión (Por ejemplo, 1.5% para Derivación Individual)
    cdt_max_permitida = 1.5 
    v_limite_cdt = (cdt_max_permitida / 100.0) * tension

    # 2. Selección de sección comercial por Caída de Tensión mínima
    secciones_comerciales = [1.5, 2.5, 4.0, 6.0, 10.0, 16.0, 25.0, 35.0, 50.0, 70.0, 95.0]
    seccion_por_cdt = 1.5
    
    for s in secciones_comerciales:
        # ΔU = (K * P * L) / (γ * S * V)
        cdt_voltios = (factor_cdt * potencia * longitud) / (conductividad * s * tension)
        if cdt_voltios <= v_limite_cdt:
            seccion_por_cdt = s
            break
        seccion_por_cdt = s # Si supera todas, asigna la máxima por seguridad

    # 3. Validación por Intensidad Admisible (Iz) usando tus tablas de XLPE
    # Asumimos instalación bajo tubo empotrado (columna peor caso del REBT)
    tabla_iz = TABLA_IZ_XLPE_mono if sistema == 'monofasico' else TABLA_IZ_XLPE_tri
    seccion_final = seccion_por_cdt
    
    for s in secciones_comerciales:
        if s >= seccion_final:
            iz_admisible = tabla_iz.get(s, 0.0)
            if iz_admisible >= intensidad:
                seccion_final = s
                break

    # Recalculamos valores finales con la sección elegida
    cdt_final_voltios = (factor_cdt * potencia * longitud) / (conductividad * seccion_final * tension)
    cdt_final_porcentaje = (cdt_final_voltios / tension) * 100.0
    iz_final = tabla_iz.get(seccion_final, 0.0)

    # 4. Dimensionado del Tubo Protector (ITC-BT-21 / ITC-BT-15)
    if seccion_final <= 6: tubo = 25
    elif seccion_final <= 10: tubo = 32
    elif seccion_final <= 16: tubo = 40
    elif seccion_final <= 25: tubo = 50
    else: tubo = 63

    return jsonify({
        'status': 'success',
        'intensidad': round(intensidad, 2),
        'seccion': seccion_final,
        'iz_admisible': iz_final,
        'cdt_porcentaje': round(cdt_final_porcentaje, 2),
        'tubo': tubo
    })
# ==============================================================================
# 4. MEMORIA TÉCNICA DE DISEÑO (MTD - CORREGIDO UNIT LABEL)
# ==============================================================================
@app.route('/memoria')
def ruta_antigua_memoria():
    # 🔒 EL CORTAFUEGOS: Si no hay sesión activa en el servidor, lo expulsamos al login
    if 'usuario' not in session:
        return redirect(url_for('inicio_plataforma'))
    
    try:
        ruta_archivo = os.path.join(os.path.dirname(__file__), 'memoria.html')
        if not os.path.exists(ruta_archivo):
            return "<h3>Error: No se encuentra el archivo 'memoria.html'</h3>", 404
        with open(ruta_archivo, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        return f"<h3>Error al abrir el archivo:</h3><p>{str(e)}</p>", 500

datos_temporales = {}
# Archivo temporal para guardar el estado de la memoria
DATOS_FILE = "datos_memoria_atex.json"
# ==========================================
# MÓDULO INTERNO: CÁLCULO ATEX
# ==========================================
@app.route('/atex', methods=['GET'])
def vista_atex():
    # 🔒 CORTAFUEGOS: Si no hay sesión activa en el servidor, rebota de inmediato al inicio
    if 'usuario' not in session:
        return redirect(url_for('inicio_plataforma'))
        
    try:
        # Buscamos el archivo atex_calculator.html en el directorio raíz de la aplicación
        ruta_archivo = os.path.join(os.path.dirname(__file__), 'atex_calculator.html')
        if not os.path.exists(ruta_archivo):
            return "<h3>Error: No se encuentra el archivo 'atex_calculator.html' en el directorio raíz</h3>", 404
            
        with open(ruta_archivo, 'r', encoding='utf-8') as f:
            contenido = f.read()
            
        # 🌟 SEGURA Y DINÁMICA: Procesamos la plantilla inyectando el ingeniero de la sesión
        return render_template_string(contenido, usuario=session['usuario'])
        
    except Exception as e:
        return f"<h3>Error al cargar el módulo ATEX:</h3><p>{str(e)}</p>", 500

@app.route('/api/guardar-atex', methods=['POST'])
def guardar_atex():
    try:
        datos = request.get_json()
        # Guardamos el HTML/Texto recibido en un archivo local
        with open(DATOS_FILE, 'w', encoding='utf-8') as f:
            json.dump(datos, f, ensure_ascii=False, indent=4)
        return jsonify({"status": "success", "message": "Datos ATEX guardados en el servidor"}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/obtener-atex', methods=['GET'])
def obtener_atex():
    if not os.path.exists(DATOS_FILE):
        return jsonify({"alcance": "no", "contenido": ""}), 200
    
    with open(DATOS_FILE, 'r', encoding='utf-8') as f:
        datos = json.load(f)
    return jsonify(datos), 200

import time
import json
import os
from flask import Flask, request, jsonify, session, redirect, url_for, render_template_string

# Ruta automática al archivo de proyectos
PROYECTOS_FILE = os.path.join(os.path.dirname(__file__), 'proyectos.json')

def cargar_todos_los_proyectos():
    if not os.path.exists(PROYECTOS_FILE):
        return {"proyectos": []}
    try:
        with open(PROYECTOS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {"proyectos": []}

def guardar_todos_los_proyectos(datos):
    with open(PROYECTOS_FILE, 'w', encoding='utf-8') as f:
        json.dump(datos, f, indent=4, ensure_ascii=False)


# ==========================================
# 🚀 APIS DE GESTIÓN DE PROYECTOS
# ==========================================
@app.route('/api/proyectos/listar', methods=['GET'])
def listar_proyectos():
    if 'usuario' not in session:
        return jsonify({"status": "error", "message": "Sesión expirada"}), 401
    
    db = cargar_todos_los_proyectos()
    # Filtramos para enviar únicamente los proyectos que pertenecen al ingeniero actual
    mis_proyectos = [p for p in db.get('proyectos', []) if p.get('creador') == session['usuario']]
    
    return jsonify({"status": "success", "proyectos": mis_proyectos})

@app.route('/api/proyectos/crear', methods=['POST'])
def crear_proyecto():
    if 'usuario' not in session:
        return jsonify({"status": "error", "message": "Sesión expirada"}), 401
    
    try:
        datos_recibidos = request.get_json()
        nombre_proyecto = datos_recibidos.get('nombre', '').strip()
        
        if not nombre_proyecto:
            return jsonify({"status": "error", "message": "El nombre del proyecto no puede estar vacío"}), 400
            
        db = cargar_todos_los_proyectos()
        
        # Generamos una ID única e irrepetible usando el timestamp actual
        nuevo_id = f"proy_{int(time.time())}"
        
        nuevo_proyecto = {
            "id_proyecto": nuevo_id,
            "creador": session['usuario'],
            "nombre": nombre_proyecto,
            "fecha_creacion": datetime.datetime.now().strftime("%d/%m/%Y %H:%M"),
            "datos_cuadro": {},  # Aquí el frontend inyectará la lista de circuitos {'circuitos': [...]}
            "datos_memoria": {}, 
            "datos_seguridad": {},
            "datos_tierra": {},
            "datos_atex": {},
            "datos_cortocircuito": {},
            "datos_unifilar": {}
        }
        
        db['proyectos'].append(nuevo_proyecto)
        guardar_todos_los_proyectos(db)
        
        return jsonify({"status": "success", "message": "Proyecto creado", "id_proyecto": nuevo_id})
        
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/proyectos/eliminar/<id_proyecto>', methods=['DELETE'])
def eliminar_proyecto(id_proyecto):
    if 'usuario' not in session:
        return jsonify({"status": "error", "message": "Sesión expirada"}), 401
        
    usuario_activo = session['usuario']
    
    try:
        db = cargar_todos_los_proyectos()
        proyectos_iniciales = len(db.get('proyectos', []))
        
        # Filtramos la lista: dejamos todos los proyectos EXCEPTO el que coincide con la ID Y el creador
        db['proyectos'] = [
            p for p in db.get('proyectos', []) 
            if not (p.get('id_proyecto') == id_proyecto and p.get('creador') == usuario_activo)
        ]
        
        if len(db['proyectos']) == proyectos_iniciales:
            return jsonify({"status": "error", "message": "Proyecto no encontrado o acceso denegado"}), 403
            
        guardar_todos_los_proyectos(db)
        return jsonify({"status": "success", "message": "Proyecto eliminado correctamente"})
        
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# ==============================================================================
# 🔒 INTEGRACIÓN: APIS DE GUARDADO Y RECUPERACIÓN MULTI-PROYECTO (CON CIRCUITOS)
# ==============================================================================
@app.route('/api/proyectos/guardar_datos', methods=['POST'])
def guardar_datos_proyecto():
    if 'usuario' not in session:
        return jsonify({"status": "error", "message": "Sesión expirada"}), 401
        
    try:
        datos_recibidos = request.get_json()
        id_proyecto = datos_recibidos.get('id_proyecto')
        modulo = datos_recibidos.get('modulo')     # Ejemplo: 'datos_cuadro' o 'datos_memoria'
        payload = datos_recibidos.get('payload')   # Contiene los circuitos u otros objetos del formulario
        
        if not id_proyecto or not modulo:
            return jsonify({"status": "error", "message": "Faltan parámetros obligatorios"}), 400
            
        db = cargar_todos_los_proyectos()
        
        # Buscamos el proyecto en la base de datos JSON
        for p in db.get('proyectos', []):
            if p['id_proyecto'] == id_proyecto and p['creador'] == session['usuario']:
                
                # REGLA EXPLICATIVA:
                # Si desde tu JS mandas modulo="datos_cuadro", el payload (que contiene tu lista de circuitos)
                # se inyectará directamente sustituyendo o creando el diccionario correspondiente.
                p[modulo] = payload  
                
                guardar_todos_los_proyectos(db)
                return jsonify({"status": "success", "message": f"Datos de {modulo} guardados con éxito"})
                
        return jsonify({"status": "error", "message": "Proyecto no encontrado o acceso denegado"}), 403
        
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/proyectos/obtener/<id_proyecto>', methods=['GET'])
def obtener_proyecto(id_proyecto):
    if 'usuario' not in session:
        return jsonify({"status": "error", "message": "Sesión expirada"}), 401
        
    usuario_activo = session['usuario']
    db = cargar_todos_los_proyectos()
    
    for p in db.get('proyectos', []):
        if p.get('id_proyecto') == id_proyecto:
            if p.get('creador') == usuario_activo:
                return jsonify({"status": "success", "proyecto": p})
            else:
                return jsonify({"status": "error", "message": "Acceso denegado. Este proyecto no le pertenece."}), 403
                
    return jsonify({"status": "error", "message": "Proyecto no encontrado"}), 404

# Busca esto al final de tu app.py y cámbialo para que quede así:
if __name__ == '__main__':
    # Usamos el puerto que nos dé internet (por defecto 10000 en Render)
    puerto = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=puerto, debug=False)
