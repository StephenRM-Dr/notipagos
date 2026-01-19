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
app.secret_key = os.getenv("SECRET_KEY", "clave_sistemas_mv_2026")

# Seguridad de sesión
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    PERMANENT_SESSION_LIFETIME=timedelta(minutes=30)
)

# --- CONFIGURACIÓN DE BASE DE DATOS ---
def get_db_connection():
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
                fecha_canje TEXT,
                banco VARCHAR(50) DEFAULT 'BDV'
            )
        ''')
        cursor.execute('''
            DO $$ 
            BEGIN 
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='pagos' AND column_name='banco') THEN
                    ALTER TABLE pagos ADD COLUMN banco VARCHAR(50) DEFAULT 'BDV';
                END IF;
            END $$;
        ''')
        conn.commit(); cursor.close(); conn.close()
    except Exception as e: print(f"❌ Error DB: {e}")

# --- LÓGICA DE EXTRACCIÓN UNIVERSAL (SMS + NOTIFICACIONES) ---
def extractor_inteligente(texto):
    # El programa usa un limpiador de texto
    texto_limpio = texto.replace('"', '').replace('\\n', ' ').replace('\n', ' ').strip()
    pagos_detectados = []
    
    patrones = {
        "BDV": (r"BDV", r"(?:desde el tlf|de)\s+(\d+)", r"por\s+([\d.]+,\d{2})\s+Bs", r"Ref:\s?(\d+)"),
        "BANESCO": (r"Banesco", r"(?:de|desde)\s+(\d+)", r"Bs\.\s?([\d.]+,\d{2})", r"Ref:\s?(\d+)"),
        "BINANCE": (r"Binance", r"(?:from|de)\s+(.*?)\s+(?:received|el)", r"([\d.]+)\s?USDT", r"(?:ID|Order):\s?(\d+)"),
        "BANCOLOMBIA": (r"Bancolombia", r"en\s+(.*?)\s+por", r"\$\s?([\d.]+)", r"Ref\.\s?(\d+)"),
        "NEQUI": (r"Nequi", r"De\s+(.*?)\s?te", r"\$\s?([\d.]+)", r"referencia\s?(\d+)"),
        "PLAZA": (r"Plaza", r"desde\s+(.*?)\s+por", r"Bs\.\s?([\d.]+,\d{2})", r"Ref:\s?(\d+)|R\.\.\.\s?(\d+)")
    }

    for banco, (key, re_emi, re_mon, re_ref) in patrones.items():
        if re.search(key, texto_limpio, re.IGNORECASE):
            emisores = re.findall(re_emi, texto_limpio, re.IGNORECASE)
            montos = re.findall(re_mon, texto_limpio, re.IGNORECASE)
            refs_raw = re.findall(re_ref, texto_limpio, re.IGNORECASE)
            
            for i in range(len(refs_raw)):
                actual_ref = refs_raw[i]
                if isinstance(actual_ref, tuple):
                    actual_ref = next((x for x in actual_ref if x), None)

                pagos_detectados.append({
                    "banco": banco,
                    "emisor": emisores[i].strip() if i < len(emisores) else "Remitente Desconocido",
                    "monto": montos[i] if i < len(montos) else "0,00",
                    "referencia": actual_ref
                })
    return pagos_detectados

# --- ESTILOS CSS REESTABLECIDOS ---
CSS_COMUN = '''
:root { --primary: #004481; --secondary: #f4f7f9; --accent: #00b1ea; --danger: #d9534f; --success: #28a745; --warning: #ffc107; }
body { font-family: 'Segoe UI', Arial, sans-serif; background-color: var(--secondary); margin: 0; color: #333; line-height: 1.5; }
.container { width: 100%; max-width: 1200px; margin: auto; padding: 20px; box-sizing: border-box; }
.btn { border: none; border-radius: 8px; padding: 10px 20px; font-weight: 600; cursor: pointer; transition: 0.3s; text-decoration: none; display: inline-flex; align-items: center; gap: 8px; font-size: 14px; }
.btn-primary { background: var(--primary); color: white; }
.btn-success { background: var(--success); color: white; }
.btn-danger { background: var(--danger); color: white; }
.card { background: white; border-radius: 15px; box-shadow: 0 5px 15px rgba(0,0,0,0.05); padding: 25px; margin-bottom: 25px; border: 1px solid #eee; }
.table-container { overflow-x: auto; border-radius: 12px; border: 1px solid #eee; background: white; }
table { width: 100%; border-collapse: collapse; min-width: 900px; }
th { background: #f8f9fa; color: #555; padding: 15px; text-align: left; font-size: 12px; text-transform: uppercase; border-bottom: 2px solid #eee; }
td { padding: 15px; border-bottom: 1px solid #f1f1f1; font-size: 14px; }
.badge { padding: 5px 12px; border-radius: 50px; font-size: 11px; font-weight: bold; }
.LIBRE { background: #e7f4e8; color: #2e7d32; }
.CANJEADO { background: #fdecea; color: #c62828; }
.badge-banco { padding: 4px 10px; border-radius: 6px; font-size: 11px; font-weight: bold; }
.badge-bdv { background: #ffebee; color: #c62828; border: 1px solid #ffcdd2; }
.badge-banesco { background: #e8f5e9; color: #2e7d32; border: 1px solid #c8e6c9; }
.badge-binance { background: #fffde7; color: #856404; border: 1px solid #ffeeba; }
.resumen-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 20px; margin-top: 30px; }
.resumen-card { background: white; padding: 25px; border-radius: 15px; box-shadow: 0 4px 15px rgba(0,0,0,0.05); border-left: 6px solid var(--primary); }
.resumen-card small { display: block; color: #777; font-size: 12px; margin-bottom: 8px; font-weight: bold; }
.resumen-card b { font-size: 24px; color: #333; font-family: 'Courier New', monospace; }
'''

# --- VISTAS HTML ---
HTML_LOGIN = '''<!DOCTYPE html><html><head><title>Admin Login</title><style>''' + CSS_COMUN + '''body{display:flex;justify-content:center;align-items:center;height:100vh;background:var(--primary);}</style></head><body><div class="card" style="width:380px;text-align:center;"><h2>Panel Administrativo</h2><form method="POST"><input type="password" name="password" placeholder="Clave de seguridad" style="width:100%;padding:15px;margin-bottom:20px;border:1px solid #ddd;border-radius:10px;box-sizing:border-box;" required autofocus><button type="submit" class="btn btn-primary" style="width:100%;justify-content:center;">ENTRAR</button></form></div></body></html>'''
HTML_PORTAL = '''<!DOCTYPE html><html><head><title>Verificador</title><meta name="viewport" content="width=device-width, initial-scale=1"><style>''' + CSS_COMUN + '''</style></head><body><div class="container" style="max-width:500px;"><div style="display:flex;justify-content:space-between;margin-bottom:30px;"><a href="/" class="btn" style="background:#ddd;">🔄 Limpiar</a><a href="/admin" class="btn btn-primary">⚙️ Acceso Admin</a></div><div class="card" style="text-align:center;"><h2>Verificar Pago</h2><form method="POST" action="/verificar"><input type="text" name="ref" placeholder="Referencia" style="width:100%;padding:15px;font-size:24px;border:2px solid #eee;border-radius:12px;text-align:center;margin-bottom:20px;box-sizing:border-box;" required autocomplete="off"><button type="submit" class="btn btn-primary" style="width:100%;padding:18px;font-size:18px;justify-content:center;">CONSULTAR</button></form>{% if resultado %}<div style="margin-top:25px;padding:20px;border-radius:12px;text-align:left;border:1px solid #ddd;" class="{{ resultado.clase }}"><h3>{{ resultado.mensaje }}</h3>{% if resultado.datos %}<b>Emisor:</b> {{ resultado.datos[0] }}<br><b>Monto:</b> {{ resultado.datos[1] }}<br><b>Ref:</b> {{ resultado.datos[3] }}{% endif %}</div>{% endif %}</div></div></body></html>'''
HTML_ADMIN = '''<!DOCTYPE html><html><head><title>Panel Admin</title><style>''' + CSS_COMUN + '''</style></head><body><div class="container"><div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:30px;"><h2>Gestión de Pagos Multibanco</h2><div style="display:flex;gap:10px;"><a href="/admin/exportar" class="btn btn-success">📊 Excel</a><a href="/logout" class="btn btn-danger">Cerrar Sesión</a></div></div><div class="card"><form method="GET" style="display:flex;gap:15px;"><input type="text" name="q" placeholder="Buscar por emisor o referencia..." class="btn" style="background:white;border:1px solid #ddd;flex-grow:1;" value="{{ query }}"><button type="submit" class="btn btn-primary">🔍 Buscar</button></form></div><div class="table-container"><table><thead><tr><th>Fecha / Hora</th><th>Banco</th><th>Emisor</th><th>Monto</th><th>Referencia</th><th>Estado</th></tr></thead><tbody>{% for p in pagos %}<tr><td><b>{{p[1]}}</b><br><small style="color:#888;">{{p[2]}}</small></td><td><span class="badge-banco badge-{{p[9]|lower}}">{{p[9]}}</span></td><td>{{p[3]}}</td><td style="font-weight:bold; color:var(--primary);">{% if p[9] == 'BINANCE' %}$ {% elif p[9] in ['NEQUI','BANCOLOMBIA'] %}$ (COP) {% else %}Bs. {% endif %}{{p[4]}}</td><td><code>{{p[5]}}</code></td><td><span class="badge {{p[7]}}">{{p[7]}}</span></td></tr>{% endfor %}</tbody></table></div><div class="resumen-grid"><div class="resumen-card" style="border-color:#c62828;"><small>ACUMULADO BOLÍVARES</small><b>Bs. {{ totales.bs }}</b></div><div class="resumen-card" style="border-color:#fbc02d;"><small>ACUMULADO BINANCE (USDT)</small><b>$ {{ totales.usd }}</b></div><div class="resumen-card" style="border-color:#c2185b;"><small>ACUMULADO COLOMBIA (COP)</small><b>$ {{ totales.cop }}</b></div></div></div></body></html>'''

# --- RUTAS ---
@app.route('/')
def index(): return render_template_string(HTML_PORTAL)

@app.route('/webhook-bdv', methods=['POST'])
def webhook():
    try:
        raw_data = request.get_json(silent=True) or {"mensaje": request.get_data(as_text=True)}
        texto = str(raw_data.get('mensaje', ''))
        lista_pagos = extractor_inteligente(texto)
        if not lista_pagos: return "No detectado", 200
        conn = get_db_connection(); cursor = conn.cursor()
        for p in lista_pagos:
            cursor.execute("SELECT 1 FROM pagos WHERE referencia = %s", (p['referencia'],))
            if not cursor.fetchone():
                cursor.execute("INSERT INTO pagos (fecha_recepcion, hora_recepcion, emisor, monto, referencia, banco) VALUES (TO_CHAR(CURRENT_DATE, 'DD/MM/YYYY'), TO_CHAR(NOW(), 'HH12:MI AM'), %s, %s, %s, %s)", (p['emisor'], p['monto'], p['referencia'], p['banco']))
        conn.commit(); cursor.close(); conn.close()
        return "OK", 200
    except Exception as e: return str(e), 200

@app.route('/verificar', methods=['POST'])
def verificar():
    ref = request.form.get('ref', '').strip()
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute("SELECT id, emisor, monto, estado, referencia FROM pagos WHERE referencia LIKE %s LIMIT 1 FOR UPDATE", ('%' + ref,))
    pago = cursor.fetchone()
    if not pago: res = {"clase": "danger", "mensaje": "❌ PAGO NO ENCONTRADO"}
    elif pago[3] == 'CANJEADO': res = {"clase": "warning", "mensaje": "⚠️ YA FUE USADO", "datos": pago[1:]}
    else:
        cursor.execute("UPDATE pagos SET estado = 'CANJEADO', fecha_canje = %s WHERE id = %s", (datetime.now().strftime("%d/%m/%Y %H:%M"), pago[0]))
        conn.commit(); res = {"clase": "success", "mensaje": "✅ PAGO VÁLIDO", "datos": pago[1:]}
    conn.close(); return render_template_string(HTML_PORTAL, resultado=res)

@app.route('/admin')
def admin():
    if not session.get('logged_in'): return redirect(url_for('login'))
    q = request.args.get('q', '').strip()
    conn = get_db_connection(); cursor = conn.cursor()
    sql = "SELECT * FROM pagos WHERE emisor ILIKE %s OR referencia LIKE %s ORDER BY id DESC"
    cursor.execute(sql, (f"%{q}%", f"%{q}%"))
    pagos = cursor.fetchall()
    
    t_bs, t_usd, t_cop = 0.0, 0.0, 0.0
    for p in pagos:
        try:
            m_str, banco = str(p[4]), p[9]
            if banco == 'BINANCE': 
                t_usd += float(m_str)
            elif banco in ['BANCOLOMBIA', 'NEQUI']: 
                t_cop += float(m_str.replace('.', ''))
            else: 
                t_bs += float(m_str.replace('.', '').replace(',', '.'))
        except: continue

    totales = {
        "bs": f"{t_bs:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
        "usd": f"{t_usd:,.2f}",
        "cop": f"{t_cop:,.0f}".replace(",", ".")
    }
    cursor.close(); conn.close()
    return render_template_string(HTML_ADMIN, pagos=pagos, totales=totales, query=q)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if request.form.get('password') == os.getenv("ADMIN_PASSWORD", "admin123"):
            session['logged_in'] = True
            return redirect(url_for('admin'))
    return render_template_string(HTML_LOGIN)

@app.route('/logout')
def logout():
    session.clear(); return redirect(url_for('login'))

@app.route('/admin/exportar')
def exportar():
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute("SELECT fecha_recepcion, emisor, monto, referencia, banco, estado FROM pagos")
    df = pd.DataFrame(cursor.fetchall(), columns=['Fecha', 'Emisor', 'Monto', 'Ref', 'Banco', 'Estado'])
    out = BytesIO()
    with pd.ExcelWriter(out, engine='openpyxl') as w: df.to_excel(w, index=False)
    out.seek(0); return send_file(out, as_attachment=True, download_name="reporte_pagos.xlsx")

if __name__ == '__main__':
    inicializar_db()
    app.run(host='0.0.0.0', port=5000)