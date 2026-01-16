import os

def alternar_entorno():
    # 0. Verificar si el archivo existe en el directorio actual
    env_path = '.env'
    if not os.path.exists(env_path):
        print("❌ No se encontró el archivo .env")
        return

    # 1. Leer el archivo actual
    with open(env_path, 'r') as f:
        lineas = f.readlines()

    # 2. Detectar estado actual (Buscamos si la línea activa es Nube o Local)
    es_nube_activo = False
    for linea in lineas:
        l = linea.strip()
        if l.startswith('DB_HOST=') and 'neon.tech' in l:
            es_nube_activo = True
            break

    # 3. Definir los nuevos valores (Si estaba en Nube -> va a Local y viceversa)
    if es_nube_activo:
        nuevo_destino = "LOCAL 🏠"
        config = {
            'DB_HOST': 'localhost',
            'DB_NAME': 'pagos',
            'DB_USER': 'admin',
            'DB_PASS': 'sistemasmv',
            'DB_PORT': '5432',
            'DB_SSL': 'disable'
        }
    else:
        nuevo_destino = "NUBE ☁️"
        config = {
            'DB_HOST': 'ep-mute-bonus-acz4xec4-pooler.sa-east-1.aws.neon.tech',
            'DB_NAME': 'pagos',
            'DB_USER': 'neondb_owner',
            'DB_PASS': 'npg_IYuEG1LBQ4ys',
            'DB_PORT': '5432',
            'DB_SSL': 'require'
        }

    # 4. Procesar y actualizar las líneas
    nuevas_lineas = []
    claves_actualizadas = set()

    for linea in lineas:
        # Si la línea no tiene un '=', la pasamos tal cual (comentarios o espacios)
        if '=' not in linea:
            nuevas_lineas.append(linea)
            continue
        
        # Obtener la clave (lo que está antes del '=') incluso si está comentada
        clave = linea.split('=')[0].replace('#', '').strip()
        
        if clave in config:
            # Reemplazamos la línea con el nuevo valor activo (sin el #)
            nuevas_lineas.append(f"{clave}={config[clave]}\n")
            claves_actualizadas.add(clave)
        else:
            # Mantener otras variables (como SECRET_KEY o ADMIN_PASSWORD)
            nuevas_lineas.append(linea)

    # Añadir claves que falten por si el .env estaba incompleto
    for clave, valor in config.items():
        if clave not in claves_actualizadas:
            nuevas_lineas.append(f"{clave}={valor}\n")

    # 5. Guardar los cambios
    with open(env_path, 'w') as f:
        f.writelines(nuevas_lineas)

    print(f"✅ Entorno cambiado exitosamente a: {nuevo_destino}")

if __name__ == "__main__":
    alternar_entorno()