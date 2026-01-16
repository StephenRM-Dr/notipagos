import psycopg2
import re
import json
import os
import pandas as pd
from flask import Flask, request, jsonify, render_template_string, redirect, url_for, session, send_file
from datetime import datetime
from io import BytesIO

# --- CONFIGURACIÓN DE ENTORNO ---
os.environ['PGCLIENTENCODING'] = 'utf-8'

app = Flask(__name__)
app.secret_key = "clave_secreta_sistemas_mv_2024" 

# --- CONFIGURACIÓN DE BASE DE DATOS ---
DB_CONFIG = {
    "host": "localhost",
    "database": "pagos",
    "user": "admin",
    "password": "sistemasmv",
    "port": "5432"
}
ADMIN_PASSWORD = "admin123"

def get_db_connection():
    return psycopg2.connect(**DB_CONFIG, client_encoding='utf8')

def inicializar_db():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
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
        conn.commit()
        cursor.close()
        conn.close()
        print("✅ Base de Datos lista.")
    except Exception as e:
        print(f"❌ Error DB: {e}")

# --- ESTILOS CSS ---
CSS_COMUN = '''
:root { --primary: #004481; --secondary: #f4f7f9; --accent: #00b1ea; --danger: #d9534f; --success: #28a745; --warning: #ffc107; }
body { font-family: 'Segoe UI', Arial, sans-serif; background-color: var(--secondary); margin: 0; color: #333; }
.btn { border: none; border-radius: 6px; padding: 10px 20px; font-weight: 600; cursor: pointer; transition: 0.3s; text-decoration: none; display: inline-block; text-align: center; }
.btn-primary { background: var(--primary); color: white; }
.btn-success { background: var(--success); color: white; }
.btn-danger { background: var(--danger); color: white; }
.card { background: white; border-radius: 12px; box-shadow: 0 8px 24px rgba(0,0,0,0.08); padding: 25px; }
.logo-container { margin-bottom: 20px; text-align: center; }
.logo-img { max-width: 180px; height: auto; }
'''

# --- VISTAS HTML ---

HTML_LOGIN = '''
<!DOCTYPE html>
<html>
<head>
    <title>Login - Sistemas MV</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>''' + CSS_COMUN + '''
    body { display: flex; justify-content: center; align-items: center; height: 100vh; }
    .login-card { width: 100%; max-width: 350px; text-align: center; }
    input { width: 100%; padding: 12px; margin: 15px 0; border: 1px solid #ddd; border-radius: 8px; box-sizing: border-box; }</style>
</head>
<body>
    <div class="card login-card">
        <div class="logo-container"><img src="/static/logo.png" class="logo-img" onerror="this.style.display='none';"></div>
        {% if error %}<p style="color: var(--danger)">{{ error }}</p>{% endif %}
        <form method="POST">
            <input type="password" name="password" placeholder="Clave Administrativa" required autofocus>
            <button type="submit" class="btn btn-primary" style="width: 100%;">Entrar</button>
        </form>
    </div>
</body>
</html>
'''

HTML_PORTAL = '''
<!DOCTYPE html>
<html>
<head>
    <title>Verificador de Pagos</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>''' + CSS_COMUN + '''
    .wrapper { max-width: 500px; margin: 40px auto; padding: 0 15px; }
    .nav-bar { display: flex; justify-content: space-between; margin-bottom: 20px; }
    .input-ref { width: 100%; padding: 15px; font-size: 24px; border: 2px solid #eee; border-radius: 10px; text-align: center; margin-bottom: 15px; }
    .alert { border-radius: 10px; padding: 20px; margin-top: 20px; text-align: left; }
    .success { background: #e7f4e8; color: #1e4620; border-left: 5px solid var(--success); }
    .danger { background: #fdecea; color: #611a15; border-left: 5px solid var(--danger); }
    .warning { background: #fff3cd; color: #856404; border-left: 5px solid var(--warning); }</style>
</head>
<body>
    <div class="wrapper">
        <div class="nav-bar">
            <a href="/" class="btn" style="background: #ddd;">🔄 Recargar</a>
            <a href="/admin" class="btn btn-primary">⚙️ Panel Admin</a>
        </div>
        <div class="card" style="text-align: center;">
            <div class="logo-container"><img src="/static/logo.png" class="logo-img" onerror="this.style.display='none';"></div>
            <form method="POST" action="/verificar">
                <input type="text" name="ref" class="input-ref" placeholder="Referencia" required autocomplete="off" inputmode="numeric">
                <button type="submit" class="btn btn-primary" style="width: 100%; font-size: 18px; padding: 15px;">VERIFICAR</button>
            </form>
            {% if resultado %}
                <div class="alert {{ resultado.clase }}">
                    <h3>{{ resultado.mensaje }}</h3>
                    {% if resultado.datos %}
                        <b>👤 Emisor:</b> {{ resultado.datos[0] }}<br>
                        <b>💰 Monto:</b> Bs. {{ resultado.datos[1] }}<br>
                        <b>🔢 Ref:</b> {{ resultado.datos[3] }}
                    {% endif %}
                </div>
                <script>
                    var audio = new Audio('/static/{{ "success.mp3" if resultado.clase == "success" else "error.mp3" }}');
                    audio.play().catch(e => console.log("Audio bloqueado por navegador"));
                </script>
            {% endif %}
        </div>
    </div>
</body>
</html>
'''

HTML_ADMIN = '''
<!DOCTYPE html>
<html>
<head>
    <title>Admin - Panel</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>''' + CSS_COMUN + '''
    .container { max-width: 1100px; margin: 30px auto; padding: 0 20px; }
    .header-actions { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; flex-wrap: wrap; gap: 10px; }
    table { width: 100%; border-collapse: collapse; background: white; border-radius: 10px; overflow: hidden; }
    th { background: var(--primary); color: white; padding: 15px; text-align: left; }
    td { padding: 12px 15px; border-bottom: 1px solid #eee; }
    .badge { padding: 4px 10px; border-radius: 20px; font-size: 11px; font-weight: bold; }
    .LIBRE { background: #e7f4e8; color: #2e7d32; }
    .CANJEADO { background: #fdecea; color: #c62828; }
    .resumen { background: var(--primary); color: white; padding: 20px; border-radius: 10px; margin-top: 20px; text-align: right; }</style>
</head>
<body>
    <div class="container">
        <div class="header-actions">
            <div style="display:flex; align-items:center; gap:15px;">
                <img src="/static/logo.png" style="height: 50px;" onerror="this.style.display='none';">
                <h1 style="color: var(--primary); margin:0;">Panel Administrativo</h1>
            </div>
            <div>
                <a href="/admin/exportar" class="btn btn-success">📊 Descargar Excel</a>
                <a href="/" class="btn" style="background:#eee;">Verificador</a>
                <a href="/logout" class="btn btn-danger">Salir</a>
            </div>
        </div>
        
        <form method="GET" action="/admin" style="display:flex; gap:10px; margin-bottom:20px;">
            <input type="text" name="q" placeholder="Buscar por emisor o referencia..." style="flex-grow:1; padding:10px; border-radius:6px; border:1px solid #ddd;" value="{{ query }}">
            <button type="submit" class="btn btn-primary">🔍 Buscar</button>
            {% if query %}<a href="/admin" style="padding:10px; color:#666;">Limpiar</a>{% endif %}
        </form>

        <div style="overflow-x: auto;">
            <table>
                <thead><tr><th>Fecha</th><th>Emisor</th><th>Monto</th><th>Ref</th><th>Estado</th><th>Acción</th></tr></thead>
                <tbody>
                    {% for p in pagos %}
                    <tr>
                        <td>{{p[1]}}<br><small style="color:#999">{{p[2]}}</small></td>
                        <td>{{p[3]}}</td>
                        <td style="font-weight: bold;">Bs. {{p[4]}}</td>
                        <td><code>{{p[5]}}</code></td>
                        <td><span class="badge {{p[7]}}">{{p[7]}}</span></td>
                        <td>
                            {% if p[7] == 'CANJEADO' %}
                            <form method="POST" action="/admin/liberar" style="display:flex; gap:5px;">
                                <input type="hidden" name="ref" value="{{p[5]}}">
                                <input type="password" name="pw" placeholder="PIN" style="width:40px; border:1px solid #ddd;" required>
                                <button type="submit" class="btn" style="background:var(--warning); padding:5px; font-size:11px;">Liberar</button>
                            </form>
                            {% endif %}
                        </td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
        <div class="resumen"><b>Suma en Pantalla:</b> Bs. {{ total }}</div>
    </div>
</body>
</html>
'''

# --- LÓGICA DE PROCESAMIENTO ---

def limpiar_mensaje_bdv(texto):
    texto_limpio = texto.replace('"', '').replace('\n', ' ').strip()
    regex_emisor = r"de\s+(.*?)\s+por"
    regex_monto = r"Bs\.?\s?([\d.]+,\d{2})"
    regex_ref = r"(?:operaci[óo]n\s+)(\d+)"
    emisor = re.search(regex_emisor, texto_limpio)
    monto = re.search(regex_monto, texto_limpio)
    ref = re.search(regex_ref, texto_limpio)
    referencia_final = ref.group(1) if ref else (re.findall(r"\d{6,}", texto_limpio)[-1] if re.findall(r"\d{6,}", texto_limpio) else None)
    return {"emisor": emisor.group(1).strip() if emisor else "Desconocido", "monto": monto.group(1) if monto else "0,00", "referencia": referencia_final}

# --- RUTAS FLASK ---

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
        cursor.execute("INSERT INTO pagos (fecha_recepcion, hora_recepcion, emisor, monto, referencia, mensaje_completo) VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (referencia) DO NOTHING",
            (datetime.now().strftime("%d/%m/%Y"), datetime.now().strftime("%I:%M %p"), datos['emisor'], datos['monto'], datos['referencia'], mensaje))
        conn.commit(); cursor.close(); conn.close()
        return jsonify({"status": "success"}), 200
    except: return jsonify({"status": "error"}), 200

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        if request.form.get('password') == ADMIN_PASSWORD:
            session['logged_in'] = True
            return redirect(url_for('admin'))
        error = "Contraseña incorrecta"
    return render_template_string(HTML_LOGIN, error=error)

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('login'))

@app.route('/')
def index():
    return render_template_string(HTML_PORTAL)

@app.route('/verificar', methods=['POST'])
def verificar():
    busqueda = request.form.get('ref', '').strip()
    if len(busqueda) < 4: return render_template_string(HTML_PORTAL, resultado={"clase": "danger", "mensaje": "❌ Mínimo 4 dígitos"})
    try:
        conn = get_db_connection(); cursor = conn.cursor()
        cursor.execute("SELECT emisor, monto, estado, referencia, fecha_canje FROM pagos WHERE referencia LIKE %s ORDER BY id DESC LIMIT 1", ('%' + busqueda,))
        pago = cursor.fetchone()
        if not pago: res = {"clase": "danger", "mensaje": "❌ PAGO NO ENCONTRADO"}
        elif pago[2] == 'CANJEADO': res = {"clase": "warning", "mensaje": "⚠️ YA FUE USADO", "datos": pago}
        else:
            ahora = datetime.now().strftime("%d/%m/%Y %I:%M:%S %p")
            cursor.execute("UPDATE pagos SET estado = 'CANJEADO', fecha_canje = %s WHERE referencia = %s", (ahora, pago[3]))
            conn.commit()
            pago_lista = list(pago); pago_lista[4] = ahora
            res = {"clase": "success", "mensaje": "✅ PAGO VÁLIDO", "datos": pago_lista}
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
    cursor.close(); conn.close()
    total_f = f"{total:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')
    return render_template_string(HTML_ADMIN, pagos=pagos, total=total_f, query=query)

@app.route('/admin/liberar', methods=['POST'])
def liberar():
    if not session.get('logged_in'): return redirect(url_for('login'))
    if request.form.get('pw') == ADMIN_PASSWORD:
        conn = get_db_connection(); cursor = conn.cursor()
        cursor.execute("UPDATE pagos SET estado = 'LIBRE', fecha_canje = NULL WHERE referencia = %s", (request.form.get('ref'),))
        conn.commit(); cursor.close(); conn.close()
    return redirect(url_for('admin'))

@app.route('/admin/exportar')
def exportar():
    if not session.get('logged_in'): return redirect(url_for('login'))
    try:
        conn = get_db_connection(); cursor = conn.cursor()
        cursor.execute("SELECT fecha_recepcion, hora_recepcion, emisor, monto, referencia, estado, fecha_canje FROM pagos ORDER BY id DESC")
        datos = cursor.fetchall()
        cursor.close(); conn.close()
        
        df = pd.DataFrame(datos, columns=['Fecha Recibido', 'Hora', 'Emisor', 'Monto (Bs)', 'Referencia', 'Estado', 'Fecha Canje'])
        output = BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='Pagos')
        output.seek(0)
        
        nombre_archivo = f"Reporte_Pagos_{datetime.now().strftime('%d_%m_%Y')}.xlsx"
        return send_file(output, as_attachment=True, download_name=nombre_archivo, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    except Exception as e:
        return f"Error al generar Excel: {e}"

if __name__ == '__main__':
    inicializar_db()
    app.run(host='0.0.0.0', port=5000)