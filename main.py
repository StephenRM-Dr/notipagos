import psycopg2
import re
import os
import pandas as pd
from flask import Flask, request, render_template_string, redirect, url_for, session, send_file
from datetime import datetime, timedelta
from io import BytesIO
from dotenv import load_dotenv

# --- CONFIGURACIÓN ---
load_dotenv(override=True)
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "clave_sistemas_mv_2026")

# Configuración del Logo (Cambia esta URL por la de tu logo)
LOGO_URL = "https://imgur.com/a/w6jRX9S" 

# --- BASE DE DATOS ---
def get_db_connection():
    return psycopg2.connect(
        host=os.getenv("DB_HOST"),
        database=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASS"),
        port=os.getenv("DB_PORT", "5432"),
        sslmode="require" if "neon.tech" in (os.getenv("DB_HOST") or "") else "disable"
    )

# --- EXTRACTOR MEJORADO (Ignora Comisiones + BDV Comercio) ---
def extractor_inteligente(texto):
    # El programa usa un limpiador de texto
    texto_limpio = texto.replace('"', '').replace('\\n', ' ').replace('\n', ' ').strip()
    pagos_detectados = []
    
    patrones = {
        "BDV": (
            r"BDV|PagomovilBDV", 
            r"(?:del|tlf|de)\s?(\d{4}-\d+)", 
            r"por\s+Bs\.?\s?([\d.]+,\d{2})", # Solo captura lo que sigue a "por"
            r"Ref:\s?(\d+)"
        ),
        "BANESCO": (r"Banesco", r"(?:de|desde)\s+(\d+)", r"Bs\.\s?([\d.]+,\d{2})", r"Ref:\s?(\d+)"),
        "BINANCE": (r"Binance", r"(?:from|de)\s+(.*?)\s+(?:received|el)", r"([\d.]+)\s?USDT", r"(?:ID|Order):\s?(\d+)"),
        "BANCOLOMBIA": (r"Bancolombia", r"en\s+(.*?)\s+por", r"\$\s?([\d.]+)", r"Ref\.\s?(\d+)"),
        "NEQUI": (r"Nequi", r"De\s+(.*?)\s?te", r"\$\s?([\d.]+)", r"referencia\s?(\d+)"),
        "PLAZA": (r"Plaza", r"desde\s+(.*?)\s+por", r"Bs\.\s?([\d.]+,\d{2})", r"Ref:\s?(\d+)|R\.\.\.\s?(\d+)")
    }

    for banco, (key, re_emi, re_mon, re_ref) in patrones.items():
        if re.search(key, texto_limpio, re.IGNORECASE):
            # Para evitar comisiones en BDV, usamos search (toma solo la primera coincidencia)
            if banco == "BDV":
                m_emi = re.search(re_emi, texto_limpio, re.IGNORECASE)
                m_mon = re.search(re_mon, texto_limpio, re.IGNORECASE)
                m_ref = re.search(re_ref, texto_limpio, re.IGNORECASE)
                if m_ref:
                    pagos_detectados.append({
                        "banco": banco,
                        "emisor": m_emi.group(1) if m_emi else "Desconocido",
                        "monto": m_mon.group(1) if m_mon else "0,00",
                        "referencia": m_ref.group(1)
                    })
            else:
                # Otros bancos (lógica normal)
                emisores = re.findall(re_emi, texto_limpio, re.IGNORECASE)
                montos = re.findall(re_mon, texto_limpio, re.IGNORECASE)
                refs = re.findall(re_ref, texto_limpio, re.IGNORECASE)
                for i in range(len(refs)):
                    actual_ref = refs[i] if not isinstance(refs[i], tuple) else next(x for x in refs[i] if x)
                    pagos_detectados.append({
                        "banco": banco,
                        "emisor": emisores[i] if i < len(emisores) else "Desconocido",
                        "monto": montos[i] if i < len(montos) else "0,00",
                        "referencia": actual_ref
                    })
    return pagos_detectados

# --- CSS CON LOGO ---
CSS_FINAL = '''
:root { --primary: #004481; --secondary: #f4f7f9; --danger: #d9534f; --success: #28a745; --warning: #ffc107; }
body { font-family: 'Segoe UI', sans-serif; background: var(--secondary); margin: 0; padding-top: 20px; }
.logo-container { text-align: center; margin-bottom: 20px; }
.logo-container img { max-width: 180px; height: auto; }
.container { max-width: 1200px; margin: auto; padding: 20px; }
.card { background: white; border-radius: 12px; box-shadow: 0 4px 10px rgba(0,0,0,0.1); padding: 20px; margin-bottom: 20px; }
.btn { border: none; border-radius: 6px; padding: 10px 15px; font-weight: bold; cursor: pointer; text-decoration: none; display: inline-flex; align-items: center; gap: 5px; font-size: 13px; }
.btn-primary { background: var(--primary); color: white; }
.btn-danger { background: var(--danger); color: white; }
.btn-warning { background: var(--warning); color: #333; }
.btn-success { background: var(--success); color: white; }
table { width: 100%; border-collapse: collapse; background: white; border-radius: 8px; overflow: hidden; }
th { background: #f8f9fa; padding: 12px; text-align: left; font-size: 11px; border-bottom: 2px solid #eee; }
td { padding: 12px; border-bottom: 1px solid #eee; font-size: 13px; }
.badge { padding: 4px 8px; border-radius: 4px; font-weight: bold; font-size: 10px; }
.CANJEADO { background: #ffdce0; color: #af1f2c; }
.LIBRE { background: #dcffe4; color: #1a7f37; }
.badge-bdv { background: #ff000015; color: red; }
.badge-binance { background: #f3ba2f30; color: #856404; }
'''

# --- TEMPLATES ---
HTML_PORTAL = '''<!DOCTYPE html><html><head><title>Verificador</title><style>''' + CSS_FINAL + '''</style></head><body>
<div class="container" style="max-width:500px;">
    <div class="logo-container"><img src="''' + LOGO_URL + '''" alt="Logo"></div>
    <div class="card" style="text-align:center;">
        <h2>Verificar Referencia</h2>
        <form method="POST" action="/verificar">
            <input type="text" name="ref" placeholder="Ingrese Referencia" style="width:90%; padding:15px; font-size:20px; border:2px solid #ddd; border-radius:10px; text-align:center;" required>
            <br><br><button type="submit" class="btn btn-primary" style="width:100%; padding:15px; font-size:18px; justify-content:center;">VERIFICAR AHORA</button>
        </form>
        {% if resultado %}<div style="margin-top:20px; padding:15px; border-radius:10px;" class="{{ resultado.clase }}">
            <h3>{{ resultado.mensaje }}</h3>
            {% if resultado.datos %}<b>Emisor:</b> {{ resultado.datos[0] }}<br><b>Monto:</b> {{ resultado.datos[1] }}{% endif %}
        </div>{% endif %}
    </div>
</div></body></html>'''

HTML_ADMIN = '''<!DOCTYPE html><html><head><title>Admin</title><style>''' + CSS_FINAL + '''</style></head><body>
<div class="container">
    <div style="display:flex; justify-content:space-between; align-items:center;">
        <div style="display:flex; align-items:center; gap:15px;">
            <img src="''' + LOGO_URL + '''" style="height:50px;">
            <h2>Panel Administrativo</h2>
        </div>
        <div>
            <a href="/" class="btn" style="background:#ddd;">🔍 Ir al Verificador</a>
            <a href="/admin/exportar" class="btn btn-success">📊 Excel</a>
            <a href="/logout" class="btn btn-danger">Salir</a>
        </div>
    </div>
    <div class="card">
        <form method="GET" style="display:flex; gap:10px;">
            <input type="text" name="q" placeholder="Buscar..." value="{{ query }}" style="flex-grow:1; padding:10px; border:1px solid #ddd; border-radius:5px;">
            <button type="submit" class="btn btn-primary">Filtrar</button>
        </form>
    </div>
    <div class="card" style="padding:0; overflow:hidden;">
        <table>
            <thead><tr><th>Fecha</th><th>Banco</th><th>Emisor</th><th>Monto</th><th>Ref</th><th>Estado</th><th>Acción</th></tr></thead>
            <tbody>{% for p in pagos %}
            <tr>
                <td>{{p[1]}}<br><small>{{p[2]}}</small></td>
                <td><span class="badge badge-{{p[9]|lower}}">{{p[9]}}</span></td>
                <td>{{p[3]}}</td>
                <td style="font-weight:bold;">{{p[4]}}</td>
                <td><code>{{p[5]}}</code></td>
                <td><span class="badge {{p[7]}}">{{p[7]}}</span></td>
                <td>
                    {% if p[7] == 'CANJEADO' %}
                    <form method="POST" action="/admin/liberar" style="display:flex; gap:3px;">
                        <input type="hidden" name="ref" value="{{p[5]}}">
                        <input type="password" name="pw" placeholder="PIN" style="width:40px; border:1px solid #ddd;" required>
                        <button type="submit" class="btn btn-warning" style="padding:4px 8px;">Reset</button>
                    </form>
                    {% endif %}
                </td>
            </tr>{% endfor %}</tbody>
        </table>
    </div>
</div></body></html>'''

# --- RUTAS ---
@app.route('/')
def index(): return render_template_string(HTML_PORTAL)

@app.route('/verificar', methods=['POST'])
def verificar():
    ref = request.form.get('ref', '').strip()
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute("SELECT id, emisor, monto, estado, referencia FROM pagos WHERE referencia LIKE %s LIMIT 1", ('%' + ref,))
    pago = cursor.fetchone()
    if not pago: res = {"clase": "danger", "mensaje": "❌ NO ENCONTRADO"}
    elif pago[3] == 'CANJEADO': res = {"clase": "warning", "mensaje": "⚠️ YA USADO", "datos": pago[1:]}
    else:
        cursor.execute("UPDATE pagos SET estado = 'CANJEADO', fecha_canje = %s WHERE id = %s", (datetime.now().strftime("%d/%m/%Y %H:%M"), pago[0]))
        conn.commit(); res = {"clase": "success", "mensaje": "✅ PAGO VÁLIDO", "datos": pago[1:]}
    conn.close(); return render_template_string(HTML_PORTAL, resultado=res)

@app.route('/admin')
def admin():
    if not session.get('logged_in'): return redirect(url_for('login'))
    q = request.args.get('q', '').strip()
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute("SELECT * FROM pagos WHERE emisor ILIKE %s OR referencia LIKE %s ORDER BY id DESC", (f"%{q}%", f"%{q}%"))
    pagos = cursor.fetchall()
    conn.close(); return render_template_string(HTML_ADMIN, pagos=pagos, query=q)

@app.route('/admin/liberar', methods=['POST'])
def liberar():
    if session.get('logged_in') and request.form.get('pw') == os.getenv("ADMIN_PASSWORD"):
        conn = get_db_connection(); cursor = conn.cursor()
        cursor.execute("UPDATE pagos SET estado = 'LIBRE', fecha_canje = NULL WHERE referencia = %s", (request.form.get('ref'),))
        conn.commit(); conn.close()
    return redirect(url_for('admin'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST' and request.form.get('password') == os.getenv("ADMIN_PASSWORD"):
        session['logged_in'] = True; return redirect(url_for('admin'))
    return render_template_string('''<form method="POST" style="text-align:center; margin-top:100px;">
        <input type="password" name="password" placeholder="Clave Admin"><button type="submit">Entrar</button></form>''')

@app.route('/logout')
def logout(): session.clear(); return redirect(url_for('login'))

@app.route('/admin/exportar')
def exportar():
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute("SELECT fecha_recepcion, emisor, monto, referencia, banco, estado FROM pagos")
    df = pd.DataFrame(cursor.fetchall(), columns=['Fecha', 'Emisor', 'Monto', 'Ref', 'Banco', 'Estado'])
    out = BytesIO()
    with pd.ExcelWriter(out, engine='openpyxl') as w: df.to_excel(w, index=False)
    out.seek(0); return send_file(out, as_attachment=True, download_name="Reporte.xlsx")

@app.route('/webhook-bdv', methods=['POST'])
def webhook():
    try:
        raw_data = request.get_json(silent=True) or {"mensaje": request.get_data(as_text=True)}
        texto = str(raw_data.get('mensaje', ''))
        lista_pagos = extractor_inteligente(texto)
        conn = get_db_connection(); cursor = conn.cursor()
        for p in lista_pagos:
            cursor.execute("SELECT 1 FROM pagos WHERE referencia = %s", (p['referencia'],))
            if not cursor.fetchone():
                cursor.execute("INSERT INTO pagos (fecha_recepcion, hora_recepcion, emisor, monto, referencia, banco) VALUES (%s, %s, %s, %s, %s, %s)", 
                               (datetime.now().strftime("%d/%m/%Y"), datetime.now().strftime("%H:%M"), p['emisor'], p['monto'], p['referencia'], p['banco']))
        conn.commit(); conn.close(); return "OK", 200
    except Exception as e: return str(e), 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)