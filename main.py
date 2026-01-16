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

# --- LÓGICA DE LIMPIEZA BDV ---
def limpiar_mensaje_bdv(texto):
    texto_limpio = texto.replace('"', '').replace('\n', ' ').strip()
    
    regex_emisor = r"de\s+(.*?)\s+por"
    regex_monto = r"Bs\.?\s?([\d.]+,\d{2})"
    regex_ref = r"(?:operaci[óo]n\s+)(\d+)"
    
    emisor = re.search(regex_emisor, texto_limpio)
    monto = re.search(regex_monto, texto_limpio)
    ref = re.search(regex_ref, texto_limpio)
    
    referencia_final = ref.group(1) if ref else (re.findall(r"\d{6,}", texto_limpio)[-1] if re.findall(r"\d{6,}", texto_limpio) else None)
    
    return {
        "emisor": emisor.group(1).strip() if emisor else "Desconocido",
        "monto": monto.group(1) if monto else "0,00",
        "referencia": referencia_final
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
'''

# --- VISTAS HTML CORREGIDAS ---
HTML_LOGIN = '''<!DOCTYPE html><html><head><title>Login Admin</title><style>''' + CSS_COMUN + '''body{display:flex;justify-content:center;align-items:center;height:100vh;background:linear-gradient(135deg, #004481 0%, #00b1ea 100%);}</style></head><body><div class="card" style="width:350px;text-align:center;"><img src="/static/logo.png" class="logo-img" onerror="this.style.display='none';"><h3 style="margin-top:0;">Acceso Administrativo</h3><form method="POST"><input type="password" name="password" placeholder="Clave de Seguridad" style="width:100%;padding:12px;margin-bottom:15px;border:1px solid #ddd;border-radius:8px;box-sizing:border-box;" required autofocus><button type="submit" class="btn btn-primary" style="width: 100%;">ENTRAR AL PANEL</button></form><br><a href="/" style="color:white; text-decoration:none; font-size:14px; opacity:0.8;">← Volver al Verificador</a></div></body></html>'''

HTML_PORTAL = '''<!DOCTYPE html><html><head><title>Verificador de Pagos</title><meta name="viewport" content="width=device-width, initial-scale=1"><style>''' + CSS_COMUN + '''.wrapper{max-width:500px;margin:40px auto;padding:0 15px;}</style></head><body><div class="wrapper"><div style="display:flex;justify-content:space-between;margin-bottom:20px;"><a href="/" class="btn" style="background:#ddd; color:#333;">🔄 Limpiar</a><a href="/admin" class="btn btn-primary">⚙️ Acceso Admin</a></div><div class="card" style="text-align: center;"><img src="/static/logo.png" class="logo-img" onerror="this.style.display='none';"><h2>Verificar Referencia</h2><form method="POST" action="/verificar"><input type="text" name="ref" placeholder="Ej: 123456" style="width:100%;padding:15px;font-size:24px;border:2px solid #eee;border-radius:12px;text-align:center;margin-bottom:15px;box-sizing:border-box;" required autocomplete="off" inputmode="numeric"><button type="submit" class="btn btn-primary" style="width: 100%; font-size: 18px; padding: 15px;">CONSULTAR PAGO</button></form>{% if resultado %}<div style="margin-top:20px;padding:20px;border-radius:10px;text-align:left; border: 1px solid #ddd;" class="{{ resultado.clase }}"><h3>{{ resultado.mensaje }}</h3>{% if resultado.datos %}<b>👤 Emisor:</b> {{ resultado.datos[0] }}<br><b>💰 Monto:</b> Bs. {{ resultado.datos[1] }}<br><b>🔢 Ref:</b> {{ resultado.datos[3] }}{% endif %}</div><script>new Audio('/static/{{ "success.mp3" if resultado.clase == "success" else "error.mp3" }}').play().catch(e => console.log("Audio bloqueado por navegador"));</script>{% endif %}</div></div></body></html>'''

HTML_ADMIN = '''<!DOCTYPE html><html><head><title>Panel de Control</title><style>''' + CSS_COMUN + '''.container{max-width:1150px;margin:30px auto;padding:0 20px;}</style></head><body><div class="container"><div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:20px;"><div><img src="/static/logo.png" style="height:50px; vertical-align:middle; margin-right:10px;"><h2 style="display:inline; margin:0;color:var(--primary); vertical-align:middle;">Control de Pagos</h2></div><div style="display:flex; gap:10px;"><a href="/" class="btn" style="background:#ddd; color:#333;">🔍 Verificador</a><a href="/admin/exportar" class="btn btn-success">📊 Excel</a><a href="/logout" class="btn btn-danger">SALIR</a></div></div><div class="card"><form method="GET" style="display:flex;gap:10px;margin-bottom:20px;"><input type="text" name="q" placeholder="Buscar por emisor o referencia..." style="flex-grow:1;padding:12px;border-radius:8px;border:1px solid #ddd;" value="{{ query }}"><button type="submit" class="btn btn-primary">BUSCAR</button></form><div style="overflow-x:auto;"><table><thead><tr><th>Fecha/Hora</th><th>Emisor</th><th>Monto</th><th>Ref</th><th>Estado</th><th>Canjeado el</th><th>Acción</th></tr></thead><tbody>{% for p in pagos %}<tr><td>{{p[1]}}<br><small style="color:#999">{{p[2]}}</small></td><td>{{p[3]}}</td><td style="font-weight:bold;">Bs. {{p[4]}}</td><td><code>{{p[5]}}</code></td><td><span class="badge {{p[7]}}">{{p[7]}}</span></td><td style="color:var(--danger);font-size:12px;">{{p[8] if p[8] else '---'}}</td><td>{% if p[7] == 'CANJEADO' %}<form method="POST" action="/admin/liberar" style="display:flex;gap:5px;"><input type="hidden" name="ref" value="{{p[5]}}"><input type="password" name="pw" placeholder="PIN" style="width:50px; padding:5px; border-radius:4px; border:1px solid #ddd;" required><button type="submit" class="btn" style="background:var(--warning);padding:5px 10px; font-size:12px;">Reset</button></form>{% endif %}</td></tr>{% endfor %}</tbody></table></div><div class="resumen">Total en Pantalla: <b>Bs. {{ total }}</b></div></div></div></body></html>'''

# --- RUTAS ---

@app.route('/webhook-bdv', methods=['POST'])
def webhook():
    raw_data = request.get_data(as_text=True).strip()
    match = re.search(r'"mensaje":\s*"(.*)"', raw_data, re.DOTALL)
    mensaje = match.group(1).replace('\\"', '"').replace('\"', '"') if match else None
    
    if not mensaje:
        try: mensaje = json.loads(raw_data).get("mensaje", "")
        except: return jsonify({"status": "error"}), 200
        
    if not mensaje or "{not_text_big}" in mensaje: return jsonify({"status": "ignored"}), 200
    
    try:
        datos = limpiar_mensaje_bdv(mensaje)
        if not datos['referencia']: return jsonify({"status": "no_ref"}), 200
        
        conn = get_db_connection(); cursor = conn.cursor()
        cursor.execute("""INSERT INTO pagos (fecha_recepcion, hora_recepcion, emisor, monto, referencia, mensaje_completo) 
                          VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (referencia) DO NOTHING""",
            (datetime.now().strftime("%d/%m/%Y"), datetime.now().strftime("%I:%M %p"), 
             datos['emisor'], datos['monto'], datos['referencia'], mensaje))
        conn.commit(); cursor.close(); conn.close()
        return jsonify({"status": "success"}), 200
    except: return jsonify({"status": "error"}), 200

@app.route('/verificar', methods=['POST'])
def verificar():
    busqueda = request.form.get('ref', '').strip()
    if len(busqueda) < 4: return render_template_string(HTML_PORTAL, resultado={"clase": "danger", "mensaje": "❌ Mínimo 4 dígitos"})
    try:
        conn = get_db_connection(); cursor = conn.cursor()
        cursor.execute("SELECT emisor, monto, estado, referencia FROM pagos WHERE referencia LIKE %s ORDER BY id DESC LIMIT 1", ('%' + busqueda,))
        pago = cursor.fetchone()
        if not pago: res = {"clase": "danger", "mensaje": "❌ PAGO NO ENCONTRADO"}
        elif pago[2] == 'CANJEADO': res = {"clase": "warning", "mensaje": "⚠️ YA FUE USADO", "datos": pago}
        else:
            ahora = datetime.now().strftime("%d/%m/%Y %I:%M:%S %p")
            cursor.execute("UPDATE pagos SET estado = 'CANJEADO', fecha_canje = %s WHERE referencia = %s", (ahora, pago[3]))
            conn.commit(); res = {"clase": "success", "mensaje": "✅ PAGO VÁLIDO", "datos": pago}
        cursor.close(); conn.close()
    except Exception as e: res = {"clase": "danger", "mensaje": f"❌ Error: {e}"}
    return render_template_string(HTML_PORTAL, resultado=res)

@app.route('/admin')
def admin():
    if not session.get('logged_in'): return redirect(url_for('login'))
    query = request.args.get('q', '').strip()
    conn = get_db_connection(); cursor = conn.cursor()
    if query:
        search = f"%{query}%"
        cursor.execute("SELECT * FROM pagos WHERE emisor ILIKE %s OR referencia LIKE %s ORDER BY id DESC", (search, search))
    else:
        cursor.execute("SELECT * FROM pagos ORDER BY id DESC")
    pagos = cursor.fetchall(); total = 0.0
    for p in pagos:
        try: total += float(p[4].replace('.', '').replace(',', '.'))
        except: pass
    total_f = f"{total:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')
    cursor.close(); conn.close()
    resp = make_response(render_template_string(HTML_ADMIN, pagos=pagos, total=total_f, query=query))
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    return resp

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