import psycopg2
import re
import json
import os
import pandas as pd
from flask import Flask, request, jsonify, render_template_string, redirect, url_for, session, send_file, make_response
from datetime import datetime, timedelta
from io import BytesIO
from dotenv import load_dotenv

# --- CARGAR CONFIGURACIÓN ---
load_dotenv(override=True)

app = Flask(__name__)
# Prioriza la clave del .env, si no existe usa la de respaldo
app.secret_key = os.getenv("SECRET_KEY", "clave_sistemas_mv_2026")

# Seguridad de sesión
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    PERMANENT_SESSION_LIFETIME=timedelta(minutes=30)
)

# --- CONFIGURACIÓN DE BASE DE DATOS ---
def get_db_connection():
    load_dotenv(override=True)
    return psycopg2.connect(
        host=os.getenv("DB_HOST"),
        database=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASS"),
        port=os.getenv("DB_PORT", "5432"),
        sslmode="require" if "neon.tech" in (os.getenv("DB_HOST") or "") else "disable",
        client_encoding='utf8'
    )

def inicializar_db():
    try:
        conn = get_db_connection(); cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS pagos (
                id SERIAL PRIMARY KEY,
                fecha_recepcion VARCHAR(20),
                hora_recepcion VARCHAR(20),
                emisor VARCHAR(255),
                monto VARCHAR(50),
                referencia VARCHAR(100) UNIQUE, 
                mensaje_completo TEXT,
                estado VARCHAR(20) DEFAULT 'LIBRE',
                fecha_canje TEXT
            )
        ''')
        conn.commit(); cursor.close(); conn.close()
        print("✅ Base de Datos operativa y lista.")
    except Exception as e: print(f"❌ Error DB: {e}")

# --- NUEVA LÓGICA DE EXTRACCIÓN MULTI-BANCO ---
def extractor_inteligente(texto):
    """Identifica el banco/plataforma y extrae datos usando patrones específicos"""
    # Limpieza inicial
    texto_limpio = texto.replace('"', '').replace('\\n', ' ').replace('\n', ' ').strip()
    
    patrones_plataformas = {
        "BDV": {
            "keywords": ["bdv", "venezuela"],
            "regex_emisor": r"de\s+(.*?)\s+por",
            "regex_monto": r"Bs\.?\s?([\d.]+,\d{2})",
            "regex_ref": r"(?:operaci[óo]n\s+)(\d+)"
        },
        "BANESCO": {
            "keywords": ["banesco"],
            "regex_emisor": r"de\s+(.*?)\s+por",
            "regex_monto": r"monto\s+Bs\.\s?([\d.]+,\d{2})",
            "regex_ref": r"Recibo\s+(\d+)"
        },
        "PLAZA": {
            "keywords": ["plaza"],
            "regex_emisor": r"desde\s+(.*?)\s+por",
            "regex_monto": r"Bs\.\s?([\d.]+,\d{2})",
            "regex_ref": r"Ref\.\s?(\d+)"
        },
        "SOFITASA": {
            "keywords": ["sofitasa"],
            "regex_emisor": r"de\s+(.*?)\s+por",
            "regex_monto": r"Bs\.\s?([\d.]+,\d{2})",
            "regex_ref": r"Referencia\s?(\d+)"
        },
        "BINANCE": {
            "keywords": ["binance", "pay"],
            "regex_emisor": r"(?:from|de)\s+(.*?)\s+(?:received|recibido)",
            "regex_monto": r"([\d.]+)\s?(?:USDT|FDUSD|USDC)",
            "regex_ref": r"(?:ID|Order)\s?(\d{8,})"
        },
        "BANCOLOMBIA": {
            "keywords": ["bancolombia", "compra", "recepcion"],
            "regex_emisor": r"en\s+(.*?)\s+por",
            "regex_monto": r"\$(\d[\d.,]*)",
            "regex_ref": r"Ref\.\s?(\d+)"
        },
        "NEQUI": {
            "keywords": ["nequi"],
            "regex_emisor": r"(?:de|De)\s+(.*?)\s?te",
            "regex_monto": r"(?:envio|envió)\s+\$(\d[\d.,]*)",
            "regex_ref": r"referencia\s?(\d+)"
        }
    }

    for plataforma, reglas in patrones_plataformas.items():
        if any(key in texto_limpio.lower() for key in reglas["keywords"]):
            emisor = re.search(reglas["regex_emisor"], texto_limpio)
            monto = re.search(reglas["regex_monto"], texto_limpio)
            ref = re.search(reglas["regex_ref"], texto_limpio)
            
            # Fallback para referencia si el regex falla (busca cualquier número largo)
            referencia_final = ref.group(1) if ref else (re.findall(r"\d{6,}", texto_limpio)[-1] if re.findall(r"\d{6,}", texto_limpio) else None)
            
            return {
                "banco": plataforma,
                "emisor": emisor.group(1).strip() if emisor else "Titular Desconocido",
                "monto": monto.group(1) if monto else "0.00",
                "referencia": referencia_final
            }
    
    # Fallback si no reconoce la plataforma
    ref_gen = re.findall(r"\d{6,}", texto_limpio)
    return {
        "banco": "OTRO/DESCONOCIDO",
        "emisor": "Verificar Manual",
        "monto": "0.00",
        "referencia": ref_gen[-1] if ref_gen else None
    }
# --- ESTILOS CSS ---
CSS_COMUN = '''
:root { --primary: #004481; --secondary: #f4f7f9; --accent: #00b1ea; --danger: #d9534f; --success: #28a745; --warning: #ffc107; }
body { font-family: 'Segoe UI', Arial, sans-serif; background-color: var(--secondary); margin: 0; color: #333; line-height: 1.5; }

/* Contenedores Responsivos */
.wrapper, .container { width: 100%; max-width: 1150px; margin: auto; padding: 10px; box-sizing: border-box; }

.btn { border: none; border-radius: 8px; padding: 10px 15px; font-weight: 600; cursor: pointer; transition: 0.3s; text-decoration: none; display: inline-flex; align-items: center; justify-content: center; font-size: 14px; gap: 5px; }
.btn-primary { background: var(--primary); color: white; }
.btn-success { background: var(--success); color: white; }
.btn-danger { background: var(--danger); color: white; }

.card { background: white; border-radius: 15px; box-shadow: 0 5px 15px rgba(0,0,0,0.05); padding: 20px; border: 1px solid #eee; margin-bottom: 20px; }
.logo-img { max-width: 150px; height: auto; margin-bottom: 15px; }

/* Tabla Responsiva */
.table-container { overflow-x: auto; -webkit-overflow-scrolling: touch; border-radius: 12px; border: 1px solid #eee; }
table { width: 100%; border-collapse: collapse; background: white; min-width: 600px; }
th { background: var(--primary); color: white; padding: 12px; text-align: left; font-size: 13px; }
td { padding: 10px; border-bottom: 1px solid #eee; font-size: 13px; }

/* Badges y Resumen */
.badge { padding: 4px 10px; border-radius: 50px; font-size: 10px; font-weight: bold; }
.LIBRE { background: #e7f4e8; color: #2e7d32; }
.CANJEADO { background: #fdecea; color: #c62828; }
.resumen { background: var(--primary); color: white; padding: 15px; border-radius: 12px; text-align: right; font-size: 16px; margin-top: 10px; }

/* Ajustes para Celulares */
@media (max-width: 600px) {
    .header-admin { flex-direction: column; text-align: center; gap: 15px; }
    .btn { padding: 12px; width: 100%; }
    .card { padding: 15px; }
    h2 { font-size: 1.2rem; }
    .resumen { text-align: center; font-size: 14px; }
}
/* Colores de Bancos */
.badge-bdv { background: #d9534f; color: white; } /* Rojo */
.badge-banesco { background: #28a745; color: white; } /* Verde */
.badge-mercantil { background: #004481; color: white; } /* Azul */
.badge-desconocido { background: #6c757d; color: white; } /* Gris */
'''

# --- VISTAS HTML CORREGIDAS ---
HTML_LOGIN = '''<!DOCTYPE html><html><head><title>Login Admin</title><style>''' + CSS_COMUN + '''body{display:flex;justify-content:center;align-items:center;height:100vh;background:linear-gradient(135deg, #004481 0%, #00b1ea 100%);}</style></head><body><div class="card" style="width:350px;text-align:center;"><img src="/static/logo.png" class="logo-img" onerror="this.style.display='none';"><h3 style="margin-top:0;">Acceso Administrativo</h3><form method="POST"><input type="password" name="password" placeholder="Clave de Seguridad" style="width:100%;padding:12px;margin-bottom:15px;border:1px solid #ddd;border-radius:8px;box-sizing:border-box;" required autofocus><button type="submit" class="btn btn-primary" style="width: 100%;">ENTRAR AL PANEL</button></form><br><a href="/" style="color:white; text-decoration:none; font-size:14px; opacity:0.8;">← Volver al Verificador</a></div></body></html>'''

HTML_PORTAL = '''<!DOCTYPE html><html><head><title>Verificador de Pagos</title><meta name="viewport" content="width=device-width, initial-scale=1"><style>''' + CSS_COMUN + '''.wrapper{max-width:500px;margin:40px auto;padding:0 15px;}</style></head><body><div class="wrapper"><div style="display:flex;justify-content:space-between;margin-bottom:20px;"><a href="/" class="btn" style="background:#ddd; color:#333;">🔄 Limpiar</a><a href="/admin" class="btn btn-primary">⚙️ Acceso Admin</a></div><div class="card" style="text-align: center;"><img src="/static/logo.png" class="logo-img" onerror="this.style.display='none';"><h2>Verificar Referencia</h2><form method="POST" action="/verificar"><input type="text" name="ref" placeholder="Ej: 123456" style="width:100%;padding:15px;font-size:24px;border:2px solid #eee;border-radius:12px;text-align:center;margin-bottom:15px;box-sizing:border-box;" required autocomplete="off" inputmode="numeric"><button type="submit" class="btn btn-primary" style="width: 100%; font-size: 18px; padding: 15px;">CONSULTAR PAGO</button></form>{% if resultado %}<div style="margin-top:20px;padding:20px;border-radius:10px;text-align:left; border: 1px solid #ddd;" class="{{ resultado.clase }}"><h3>{{ resultado.mensaje }}</h3>{% if resultado.datos %}<b>👤 Emisor:</b> {{ resultado.datos[0] }}<br><b>💰 Monto:</b> Bs. {{ resultado.datos[1] }}<br><b>🔢 Ref:</b> {{ resultado.datos[3] }}{% endif %}</div><script>new Audio('/static/{{ "success.mp3" if resultado.clase == "success" else "error.mp3" }}').play().catch(e => console.log("Audio bloqueado por navegador"));</script>{% endif %}</div></div></body></html>'''

HTML_ADMIN = '''<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Panel de Control | Verificador Multibanco</title>
    <style>
        ''' + CSS_COMUN + '''
        .container { max-width: 1250px; margin: 20px auto; padding: 0 15px; }
        .header-admin { display: flex; justify-content: space-between; align-items: center; margin-bottom: 25px; flex-wrap: wrap; gap: 15px; }
        
        /* Filtros */
        .filter-group { display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 20px; background: #fff; padding: 15px; border-radius: 12px; box-shadow: 0 2px 10px rgba(0,0,0,0.05); }
        .filter-input { padding: 12px; border: 1px solid #ddd; border-radius: 8px; font-size: 14px; }
        .search-main { flex-grow: 2; min-width: 250px; }
        .select-banco { flex-grow: 1; min-width: 180px; background: white; cursor: pointer; }
        
        /* Estilos de tabla */
        .table-container { background: white; border-radius: 12px; overflow-x: auto; border: 1px solid #eee; }
        table { width: 100%; border-collapse: collapse; min-width: 900px; }
        th { background: #f8f9fa; color: #555; font-size: 11px; text-transform: uppercase; padding: 15px; border-bottom: 2px solid #eee; text-align: left; }
        td { padding: 12px 15px; font-size: 14px; border-bottom: 1px solid #f1f1f1; vertical-align: middle; }
        
        /* Badges de Bancos */
        .badge-banco { padding: 4px 10px; border-radius: 6px; font-size: 11px; font-weight: bold; display: inline-block; }
        .badge-bdv { background: #ffebee; color: #c62828; border: 1px solid #ffcdd2; }
        .badge-banesco { background: #e8f5e9; color: #2e7d32; border: 1px solid #c8e6c9; }
        .badge-mercantil { background: #e3f2fd; color: #1565c0; border: 1px solid #bbdefb; }
        .badge-plaza { background: #fff3e0; color: #ef6c00; border: 1px solid #ffe0b2; }
        .badge-sofitasa { background: #f3e5f5; color: #7b1fa2; border: 1px solid #e1bee7; }
        .badge-binance { background: #fffde7; color: #fbc02d; border: 1px solid #fbc02d; }
        .badge-bancolombia { background: #eceff1; color: #455a64; border: 1px solid #cfd8dc; }
        .badge-nequi { background: #fce4ec; color: #c2185b; border: 1px solid #f8bbd0; }
        .badge-desconocido { background: #f5f5f5; color: #616161; }

        /* Cuadrícula de Totales */
        .resumen-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 15px; margin-top: 25px; }
        .resumen-card { background: white; padding: 20px; border-radius: 15px; box-shadow: 0 4px 15px rgba(0,0,0,0.05); border-left: 5px solid var(--primary); }
        .resumen-card small { display: block; color: #777; font-size: 12px; margin-bottom: 5px; font-weight: bold; }
        .resumen-card b { font-size: 22px; color: #333; font-family: 'Courier New', Courier, monospace; }
        .card-bs { border-color: #c62828; }
        .card-usd { border-color: #fbc02d; }
        .card-cop { border-color: #c2185b; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header-admin">
            <div style="display: flex; align-items: center; gap: 15px;">
                <img src="/static/logo.png" style="height: 45px;" onerror="this.style.display='none'">
                <h2 style="margin:0; color: var(--primary);">Gestión de Pagos Multibanco</h2>
            </div>
            <div style="display: flex; gap: 10px;">
                <a href="/" class="btn" style="background:#eee; color:#444;">🔍 Verificador</a>
                <a href="/admin/exportar" class="btn btn-success">📊 Exportar Excel</a>
                <a href="/logout" class="btn btn-danger">Cerrar Sesión</a>
            </div>
        </div>

        <form method="GET" class="filter-group">
            <input type="text" name="q" placeholder="Buscar por emisor o referencia..." 
                   class="filter-input search-main" value="{{ query }}">
            
            <select name="banco" class="filter-input select-banco">
                <option value="">🏦 Todas las plataformas</option>
                <option value="BDV" {% if banco_sel == 'BDV' %}selected{% endif %}>Banco de Venezuela</option>
                <option value="BANESCO" {% if banco_sel == 'BANESCO' %}selected{% endif %}>Banesco</option>
                <option value="PLAZA" {% if banco_sel == 'PLAZA' %}selected{% endif %}>Banco Plaza</option>
                <option value="SOFITASA" {% if banco_sel == 'SOFITASA' %}selected{% endif %}>Sofitasa</option>
                <option value="BINANCE" {% if banco_sel == 'BINANCE' %}selected{% endif %}>Binance Pay</option>
                <option value="BANCOLOMBIA" {% if banco_sel == 'BANCOLOMBIA' %}selected{% endif %}>Bancolombia</option>
                <option value="NEQUI" {% if banco_sel == 'NEQUI' %}selected{% endif %}>Nequi</option>
            </select>
            
            <button type="submit" class="btn btn-primary" style="min-width: 120px;">Filtrar</button>
        </form>

        <div class="card" style="padding: 0; overflow: hidden; border: none;">
            <div class="table-container">
                <table>
                    <thead>
                        <tr>
                            <th>Fecha/Hora</th>
                            <th>Entidad</th>
                            <th>Emisor</th>
                            <th>Monto</th>
                            <th>Referencia</th>
                            <th>Estado</th>
                            <th>Acciones</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for p in pagos %}
                        <tr>
                            <td>
                                <b>{{p[1]}}</b><br>
                                <small style="color: #888;">{{p[2]}}</small>
                            </td>
                            <td>
                                <span class="badge-banco badge-{{ p[9]|lower if p[9] else 'desconocido' }}">
                                    {{ p[9] if p[9] else 'BDV' }}
                                </span>
                            </td>
                            <td>{{p[3]}}</td>
                            <td style="font-weight: 700; color: var(--primary); font-size: 15px;">
                                {% if p[9] == 'BINANCE' %} $ 
                                {% elif p[9] in ['BANCOLOMBIA', 'NEQUI'] %} $ (COP) 
                                {% else %} Bs. {% endif %}
                                {{p[4]}}
                            </td>
                            <td><code>{{p[5]}}</code></td>
                            <td>
                                <span class="badge {{p[7]}}">{{p[7]}}</span>
                                {% if p[8] %}<br><small style="font-size: 10px; color: #999;">{{p[8]}}</small>{% endif %}
                            </td>
                            <td>
                                {% if p[7] == 'CANJEADO' %}
                                <form method="POST" action="/admin/liberar" style="display:flex; gap:5px;">
                                    <input type="hidden" name="ref" value="{{p[5]}}">
                                    <input type="password" name="pw" placeholder="PIN" 
                                           style="width:45px; padding:4px; border:1px solid #ddd; border-radius:4px;" required>
                                    <button type="submit" class="btn" 
                                            style="background:var(--warning); padding:4px 8px; font-size:10px; color:#333;">Reset</button>
                                </form>
                                {% endif %}
                            </td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>

        <div class="resumen-grid">
            <div class="resumen-card card-bs">
                <small>ACUMULADO BOLÍVARES</small>
                <b>Bs. {{ totales.bs }}</b>
            </div>
            <div class="resumen-card card-usd">
                <small>ACUMULADO BINANCE (USDT)</small>
                <b>$ {{ totales.usd }}</b>
            </div>
            <div class="resumen-card card-cop">
                <small>ACUMULADO COLOMBIA (COP)</small>
                <b>$ {{ totales.cop }}</b>
            </div>
        </div>
    </div>
</body>
</html>'''
# --- RUTAS ---

# --- WEBHOOK ACTUALIZADO ---
@app.route('/webhook-bdv', methods=['POST'])
def webhook():
    raw_data = request.get_data(as_text=True).strip()
    
    # Intento 1: Extraer mensaje mediante Regex (útil si MacroDroid envía JSON mal formado)
    match = re.search(r'"mensaje":\s*"(.*)"', raw_data, re.DOTALL)
    mensaje = match.group(1).replace('\\"', '"').replace('\"', '"') if match else None
    
    # Intento 2: JSON Estándar
    if not mensaje:
        try:
            mensaje = json.loads(raw_data).get("mensaje", "")
        except:
            return jsonify({"status": "error_json"}), 200
        
    # Validaciones básicas
    if not mensaje or "{not_text_big}" in mensaje or "[notificacion_text]" in mensaje:
        return jsonify({"status": "ignored_empty"}), 200
    
    try:
        # Usar el nuevo extractor inteligente
        datos = extractor_inteligente(mensaje)
        
        if not datos['referencia']:
            return jsonify({"status": "no_ref_detected"}), 200
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Insertar con la nueva columna 'banco'
        cursor.execute("""
            INSERT INTO pagos (fecha_recepcion, hora_recepcion, emisor, monto, referencia, mensaje_completo, banco) 
            VALUES (%s, %s, %s, %s, %s, %s, %s) 
            ON CONFLICT (referencia) DO NOTHING
        """, (
            datetime.now().strftime("%d/%m/%Y"),
            datetime.now().strftime("%I:%M %p"),
            datos['emisor'],
            datos['monto'],
            datos['referencia'],
            mensaje,
            datos['banco']
        ))
        
        conn.commit()
        cursor.close()
        conn.close()
        
        return jsonify({
            "status": "success", 
            "banco": datos['banco'], 
            "ref": datos['referencia']
        }), 200
        
    except Exception as e:
        print(f"Error en Webhook: {e}")
        return jsonify({"status": "error_db", "details": str(e)}), 200

@app.route('/verificar', methods=['POST'])
def verificar():
    busqueda = request.form.get('ref', '').strip()
    if len(busqueda) < 4: 
        return render_template_string(HTML_PORTAL, resultado={"clase": "danger", "mensaje": "❌ Mínimo 4 dígitos"})
    
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 1. BUSCAR Y BLOQUEAR la fila (FOR UPDATE) para evitar que otra consulta la toque
        # Buscamos la referencia exacta o que coincida con los últimos dígitos
        cursor.execute("""
            SELECT id, emisor, monto, estado, referencia 
            FROM pagos 
            WHERE referencia LIKE %s 
            ORDER BY id DESC 
            LIMIT 1 
            FOR UPDATE
        """, ('%' + busqueda,))
        
        pago = cursor.fetchone()
        
        if not pago:
            res = {"clase": "danger", "mensaje": "❌ PAGO NO ENCONTRADO"}
        elif pago[3] == 'CANJEADO':
            res = {"clase": "warning", "mensaje": "⚠️ YA FUE USADO", "datos": [pago[1], pago[2], pago[3], pago[4]]}
        else:
            # 2. MARCAR COMO CANJEADO inmediatamente dentro de la misma transacción bloqueada
            ahora = datetime.now().strftime("%d/%m/%Y %I:%M:%S %p")
            cursor.execute("UPDATE pagos SET estado = 'CANJEADO', fecha_canje = %s WHERE id = %s", (ahora, pago[0]))
            
            # 3. GUARDAR CAMBIOS (COMMIT) y liberar el bloqueo
            conn.commit()
            res = {"clase": "success", "mensaje": "✅ PAGO VÁLIDO", "datos": [pago[1], pago[2], pago[3], pago[4]]}
            
        cursor.close()
    except Exception as e:
        if conn: conn.rollback() # Si algo falla, deshacer cambios
        res = {"clase": "danger", "mensaje": f"❌ Error de Sistema: {e}"}
    finally:
        if conn: conn.close()
        
    return render_template_string(HTML_PORTAL, resultado=res)

@app.route('/admin')
def admin():
    if not session.get('logged_in'): return redirect(url_for('login'))
    
    query = request.args.get('q', '').strip()
    banco_sel = request.args.get('banco', '').strip()
    
    conn = get_db_connection(); cursor = conn.cursor()
    
    sql = "SELECT * FROM pagos WHERE 1=1"
    params = []
    if query:
        sql += " AND (emisor ILIKE %s OR referencia LIKE %s)"
        params.extend([f"%{query}%", f"%{query}%"])
    if banco_sel:
        sql += " AND banco = %s"
        params.append(banco_sel)
    sql += " ORDER BY id DESC"
    
    cursor.execute(sql, tuple(params))
    pagos = cursor.fetchall()
    
    # --- NUEVA LÓGICA DE TOTALES SEPARADOS ---
    t_bs = 0.0
    t_usd = 0.0
    t_cop = 0.0

    for p in pagos:
        try:
            # Limpiamos el formato de moneda (ej: 1.250,50 -> 1250.50)
            valor = float(p[4].replace('.', '').replace(',', '.'))
            banco = p[9]
            
            if banco == 'BINANCE':
                t_usd += valor
            elif banco in ['BANCOLOMBIA', 'NEQUI']:
                t_cop += valor
            else:
                t_bs += valor
        except:
            pass

    # Formatear totales para el HTML
    def fmt(n): return f"{n:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')
    
    totales = {
        "bs": fmt(t_bs),
        "usd": f"{t_usd:,.2f}",
        "cop": f"{t_cop:,.0f}".replace(',', '.') # Pesos usualmente no llevan decimales
    }
    
    cursor.close(); conn.close()
    return render_template_string(HTML_ADMIN, pagos=pagos, totales=totales, query=query, banco_sel=banco_sel)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if request.form.get('password') == os.getenv("ADMIN_PASSWORD", "admin123"):
            session.clear(); session['logged_in'] = True
            return redirect(url_for('admin'))
    return render_template_string(HTML_LOGIN)

@app.route('/logout')
def logout():
    session.clear()
    resp = make_response(redirect(url_for('login')))
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    return resp

@app.route('/admin/exportar')
def exportar():
    if not session.get('logged_in'): return redirect(url_for('login'))
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute("SELECT fecha_recepcion, emisor, monto, referencia, estado, fecha_canje FROM pagos ORDER BY id DESC")
    df = pd.DataFrame(cursor.fetchall(), columns=['Fecha', 'Emisor', 'Monto', 'Ref', 'Estado', 'Canjeado'])
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer: df.to_excel(writer, index=False)
    output.seek(0); cursor.close(); conn.close()
    return send_file(output, as_attachment=True, download_name="Reporte_Pagos.xlsx")

@app.route('/admin/liberar', methods=['POST'])
def liberar():
    if not session.get('logged_in'): return redirect(url_for('login'))
    if request.form.get('pw') == os.getenv("ADMIN_PASSWORD"):
        conn = get_db_connection(); cursor = conn.cursor()
        cursor.execute("UPDATE pagos SET estado = 'LIBRE', fecha_canje = NULL WHERE referencia = %s", (request.form.get('ref'),))
        conn.commit(); cursor.close(); conn.close()
    return redirect(url_for('admin'))

@app.route('/')
def index(): return render_template_string(HTML_PORTAL)

if __name__ == '__main__':
    inicializar_db()
    # Koyeb usa el puerto 5000 según tu configuración actual
    app.run(host='0.0.0.0', port=5000)