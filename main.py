import sqlite3
import re
import json
from flask import Flask, request, jsonify, render_template_string
from datetime import datetime

app = Flask(__name__)
DB_NAME = "pagos_bdv.db"

# --- CONFIGURACIÓN DE BASE DE DATOS ---
def inicializar_db():
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS pagos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fecha_recepcion TEXT,
                hora_recepcion TEXT,
                emisor TEXT,
                monto TEXT,
                referencia TEXT UNIQUE, 
                mensaje_completo TEXT,
                estado TEXT DEFAULT 'LIBRE'
            )
        ''')
        conn.commit()

def limpiar_mensaje_bdv(texto):
    texto_limpio = texto.replace('"', '').replace('\n', ' ').strip()
    regex_emisor = r"de\s+(.*?)\s+por"
    regex_monto = r"Bs\.?\s?([\d.]+,\d{2})"
    regex_ref = r"(?:operaci[óo]n\s+)(\d+)"

    emisor = re.search(regex_emisor, texto_limpio)
    monto = re.search(regex_monto, texto_limpio)
    ref = re.search(regex_ref, texto_limpio)

    referencia_final = None
    if ref: referencia_final = ref.group(1)
    else:
        nums = re.findall(r"\d{6,}", texto_limpio)
        if nums: referencia_final = nums[-1]

    return {
        "emisor": emisor.group(1).strip() if emisor else "Desconocido",
        "monto": monto.group(1) if monto else "0,00",
        "referencia": referencia_final
    }

# --- RUTA PARA RECIBIR PAGOS (WEBHOOK) ---
@app.route('/webhook-bdv', methods=['POST'])
def webhook():
    try:
        raw_data = request.get_data(as_text=True).strip().replace('""', '"').rstrip(',')
        data = json.loads(raw_data)
        mensaje = data.get("mensaje", "")
        
        if not mensaje or "{not_text_big}" in mensaje:
            return jsonify({"status": "ignored"}), 200

        datos = limpiar_mensaje_bdv(mensaje)
        if not datos['referencia']: return jsonify({"status": "no_ref"}), 200

        try:
            with sqlite3.connect(DB_NAME) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO pagos (fecha_recepcion, hora_recepcion, emisor, monto, referencia, mensaje_completo) 
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (datetime.now().strftime("%d/%m/%Y"), datetime.now().strftime("%I:%M %p"), 
                      datos['emisor'], datos['monto'], datos['referencia'], mensaje))
                conn.commit()
            print(f"✅ Nuevo Pago: {datos['referencia']} - Bs.{datos['monto']}")
        except sqlite3.IntegrityError:
            print(f"⚠️ Referencia duplicada ignorada: {datos['referencia']}")

        return jsonify({"status": "success"}), 200
    except Exception as e:
        print(f"❌ Error en webhook: {e}")
        return jsonify({"status": "error", "message": str(e)}), 200

# --- PORTAL DE VENDEDORES (INTERFAZ HTML) ---
HTML_PORTAL = '''
<!DOCTYPE html>
<html>
<head>
    <title>Verificador de Pagos</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body { font-family: 'Segoe UI', sans-serif; text-align: center; padding: 20px; background: #eef2f7; }
        .card { background: white; padding: 30px; border-radius: 15px; box-shadow: 0 10px 25px rgba(0,0,0,0.1); max-width: 450px; margin: auto; }
        h2 { color: #004481; }
        input { width: 90%; padding: 12px; margin: 10px 0; border: 2px solid #ddd; border-radius: 8px; font-size: 18px; text-align: center; }
        button { width: 95%; padding: 12px; background: #004481; color: white; border: none; border-radius: 8px; font-weight: bold; cursor: pointer; }
        .alert { margin-top: 25px; padding: 20px; border-radius: 10px; font-weight: bold; }
        .success { background: #d4edda; color: #155724; }
        .warning { background: #fff3cd; color: #856404; }
        .danger { background: #f8d7da; color: #721c24; }
        .info-pago { font-size: 0.9em; margin-top: 10px; border-top: 1px solid #eee; padding-top: 10px; text-align: left; }
    </style>
</head>
<body>
    <div class="card">
        <h2>Verificador BDV</h2>
        <p>Ingrese los últimos 6 dígitos</p>
        <form method="POST" action="/verificar">
            <input type="text" name="ref" placeholder="Ej: 385344" required>
            <button type="submit">VALIDAR PAGO</button>
        </form>
        {% if resultado %}
            <div class="alert {{ resultado.clase }}">
                {{ resultado.mensaje }}
                {% if resultado.datos %}
                    <div class="info-pago">
                        👤 <b>Emisor:</b> {{ resultado.datos[0] }}<br>
                        💰 <b>Monto:</b> Bs. {{ resultado.datos[1] }}<br>
                        🔢 <b>Ref. Completa:</b> {{ resultado.datos[3] }}
                    </div>
                {% endif %}
            </div>
        {% endif %}
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
    
    if len(busqueda) < 4:
        res = {"clase": "danger", "mensaje": "❌ Ingrese al menos 4 dígitos"}
        return render_template_string(HTML_PORTAL, resultado=res)

    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT emisor, monto, estado, referencia 
            FROM pagos 
            WHERE referencia LIKE ? 
            ORDER BY id DESC LIMIT 1
        """, ('%' + busqueda,))
        
        pago = cursor.fetchone()
        
        if not pago:
            res = {"clase": "danger", "mensaje": "❌ PAGO NO ENCONTRADO"}
        elif pago[2] == 'CANJEADO':
            res = {"clase": "warning", "mensaje": "⚠️ ALERTA: ESTE PAGO YA FUE USADO", "datos": pago}
        else:
            ref_completa = pago[3]
            cursor.execute("UPDATE pagos SET estado = 'CANJEADO' WHERE referencia = ?", (ref_completa,))
            conn.commit()
            res = {"clase": "success", "mensaje": "✅ PAGO VÁLIDO Y CANJEADO", "datos": pago}
            
    return render_template_string(HTML_PORTAL, resultado=res)

if __name__ == '__main__':
    inicializar_db()
    app.run(host='0.0.0.0', port=5000)