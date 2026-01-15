import psycopg2
from psycopg2 import extras
import re
import json
import os
from flask import Flask, request, jsonify, render_template_string, redirect, url_for
from datetime import datetime

# --- SOLUCIÓN AL ERROR DE UNICODE ---
os.environ['PGCLIENTENCODING'] = 'utf-8'

app = Flask(__name__)

# --- CONFIGURACIÓN ---
DB_CONFIG = {
    "host": "localhost",
    "database": "pagos",
    "user": "admin",
    "password": "sistemasmv",
    "port": "5432"
}
ADMIN_PASSWORD = "admin123"  # Cambia esto por tu seguridad

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
        print("✅ Base de Datos Postgres lista.")
    except Exception as e:
        print(f"❌ Error DB: {e}")

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

# --- RUTAS DE WEBHOOK ---
@app.route('/webhook-bdv', methods=['POST'])
def webhook():
    raw_data = request.get_data(as_text=True).strip()
    mensaje = None
    match = re.search(r'"mensaje":\s*"(.*)"', raw_data, re.DOTALL)
    
    if match:
        mensaje = match.group(1).replace('\\"', '"').replace('\"', '"')
    else:
        try:
            data = json.loads(raw_data)
            mensaje = data.get("mensaje", "")
        except:
            return jsonify({"status": "error", "reason": "invalid_format"}), 200

    if not mensaje or "{not_text_big}" in mensaje:
        return jsonify({"status": "ignored"}), 200

    try:
        datos = limpiar_mensaje_bdv(mensaje)
        if not datos['referencia']: return jsonify({"status": "no_ref"}), 200

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO pagos (fecha_recepcion, hora_recepcion, emisor, monto, referencia, mensaje_completo) 
            VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (referencia) DO NOTHING
        ''', (datetime.now().strftime("%d/%m/%Y"), datetime.now().strftime("%I:%M %p"), 
              datos['emisor'], datos['monto'], datos['referencia'], mensaje))
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({"status": "success"}), 200
    except Exception as e:
        return jsonify({"status": "error"}), 200

# --- PORTALES (HTML) ---
HTML_PORTAL = '''
<!DOCTYPE html>
<html>
<head>
    <title>Verificador Oficial</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body { font-family: 'Segoe UI', sans-serif; text-align: center; padding: 20px; background: #eef2f7; color: #333; }
        .nav-bar { margin-bottom: 20px; display: flex; justify-content: center; gap: 10px; }
        .btn-nav { background: #6c757d; color: white; padding: 8px 15px; border-radius: 5px; text-decoration: none; font-size: 14px; font-weight: bold; }
        .btn-admin { background: #004481; }
        .card { background: white; padding: 30px; border-radius: 15px; box-shadow: 0 10px 25px rgba(0,0,0,0.1); max-width: 450px; margin: auto; }
        h2 { color: #004481; margin-top: 10px; }
        input { width: 90%; padding: 12px; margin: 10px 0; border: 2px solid #ddd; border-radius: 8px; font-size: 18px; text-align: center; }
        .btn-validar { width: 95%; padding: 12px; background: #004481; color: white; border: none; border-radius: 8px; font-weight: bold; cursor: pointer; font-size: 16px; }
        .alert { margin-top: 25px; padding: 20px; border-radius: 10px; font-weight: bold; }
        .success { background: #d4edda; color: #155724; }
        .warning { background: #fff3cd; color: #856404; }
        .danger { background: #f8d7da; color: #721c24; }
        .info-pago { font-size: 0.9em; margin-top: 10px; border-top: 1px solid #eee; padding-top: 10px; text-align: left; }
        .fecha-canje { color: #d9534f; font-weight: bold; display: block; margin-top: 5px; }
    </style>
</head>
<body>
    <div class="nav-bar">
        <a href="/" class="btn-nav">🔄 Recargar Inicio</a>
        <a href="/admin" class="btn-nav btn-admin">⚙️ Panel Admin</a>
    </div>

    <div class="card">
        <h2>Verificador de Pagos</h2>
        <form method="POST" action="/verificar">
            <input type="text" name="ref" placeholder="Últimos 6 dígitos" required autocomplete="off">
            <button type="submit" class="btn-validar">VALIDAR PAGO</button>
        </form>

        {% if resultado %}
            <div class="alert {{ resultado.clase }}">
                {{ resultado.mensaje }}
                {% if resultado.datos %}
                    <div class="info-pago">
                        👤 <b>Emisor:</b> {{ resultado.datos[0] }}<br>
                        💰 <b>Monto:</b> Bs. {{ resultado.datos[1] }}<br>
                        🔢 <b>Ref:</b> {{ resultado.datos[3] }}
                        {% if resultado.datos[4] %}
                            <span class="fecha-canje">📌 Canjeado el: {{ resultado.datos[4] }}</span>
                        {% endif %}
                    </div>
                {% endif %}
            </div>
        {% endif %}
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
    <style>
        body { font-family: sans-serif; background: #f4f7f9; padding: 20px; }
        .container { max-width: 1000px; margin: auto; background: white; padding: 20px; border-radius: 10px; box-shadow: 0 4px 10px rgba(0,0,0,0.1); }
        table { width: 100%; border-collapse: collapse; margin-top: 20px; }
        th, td { padding: 10px; border-bottom: 1px solid #ddd; text-align: left; }
        th { background: #004481; color: white; }
        .status { padding: 4px 8px; border-radius: 4px; font-weight: bold; font-size: 0.8em; }
        .LIBRE { background: #d4edda; color: #155724; }
        .CANJEADO { background: #f8d7da; color: #721c24; }
        .resumen { margin-top: 20px; padding: 15px; background: #eee; border-radius: 8px; text-align: right; font-size: 1.2em; }
    </style>
</head>
<body>
    <div class="container">
        <h2>Panel Administrativo <small><a href="/">Verificador</a></small></h2>
        <table>
            <tr>
                <th>Fecha</th><th>Emisor</th><th>Monto</th><th>Referencia</th><th>Estado</th><th>Acción</th>
            </tr>
            {% for p in pagos %}
            <tr>
                <td>{{p[1]}}</td><td>{{p[3]}}</td><td>{{p[4]}}</td><td>{{p[5]}}</td>
                <td><span class="status {{p[7]}}">{{p[7]}}</span></td>
                <td>
                    {% if p[7] == 'CANJEADO' %}
                    <form method="POST" action="/admin/liberar" style="display:flex; gap:5px;">
                        <input type="hidden" name="ref" value="{{p[5]}}">
                        <input type="password" name="pw" placeholder="PIN" style="width:50px" required>
                        <button type="submit" style="background:orange; border:none; border-radius:4px; cursor:pointer">Liberar</button>
                    </form>
                    {% endif %}
                </td>
            </tr>
            {% endfor %}
        </table>
        <div class="resumen">
            <b>Total Recaudado (Hoy):</b> Bs. {{ total }}
        </div>
    </div>
</body>
</html>
'''

@app.route('/')
def index():
    return render_template_string(HTML_PORTAL)

@app.route('/verificar', methods=['POST'])
def verificar():
    busqueda = request.form.get('ref', '').strip()
    if len(busqueda) < 4: return render_template_string(HTML_PORTAL, resultado={"clase": "danger", "mensaje": "❌ Mínimo 4 dígitos"})
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
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
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM pagos ORDER BY id DESC")
    pagos = cursor.fetchall()
    
    # Cálculo de total del día (opcionalmente puedes filtrar por fecha actual en el SQL)
    total = 0.0
    for p in pagos:
        try:
            # Limpiamos el monto (ej: "1.250,50" -> 1250.50)
            valor = float(p[4].replace('.', '').replace(',', '.'))
            total += valor
        except: pass
    
    cursor.close(); conn.close()
    return render_template_string(HTML_ADMIN, pagos=pagos, total=f"{total:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.'))

@app.route('/admin/liberar', methods=['POST'])
def liberar():
    if request.form.get('pw') == ADMIN_PASSWORD:
        conn = get_db_connection(); cursor = conn.cursor()
        cursor.execute("UPDATE pagos SET estado = 'LIBRE', fecha_canje = NULL WHERE referencia = %s", (request.form.get('ref'),))
        conn.commit(); cursor.close(); conn.close()
    return redirect(url_for('admin'))

if __name__ == '__main__':
    inicializar_db()
    app.run(host='0.0.0.0', port=5000)