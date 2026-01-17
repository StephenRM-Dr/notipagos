# 🏦 Sistema de Automatización y Verificación de Pagos (BDV)

Este proyecto es una solución integral para comercios que desean automatizar la validación de Pagos Móviles del **Banco de Venezuela (BDV)**. Permite capturar notificaciones en un teléfono Android y enviarlas a un panel administrativo en la nube para su verificación en tiempo real.

## 🚀 Características
* **Captura Automática:** Uso de MacroDroid para detectar notificaciones bancarias.
* **Limpiador de Texto:** Extracción inteligente de Emisor, Monto y Referencia mediante Regex.
* **Protección Anti-Fraude:** Implementación de bloqueos de base de datos (`SELECT FOR UPDATE`) para evitar la doble validación simultánea (Race Condition).
* **Panel Administrativo:** Gestión de pagos, exportación a Excel y sistema de canje.
* **Diseño Responsivo:** Optimizado para celulares y tablets.

## 🛠️ Requisitos
1. **Servidor:** Una cuenta en [Koyeb](https://koyeb.com) o cualquier hosting Python.
2. **Base de Datos:** PostgreSQL (Recomendado: [Neon.tech](https://neon.tech)).
3. **Móvil:** Android con la aplicación [MacroDroid](https://play.google.com/store/apps/details?id=com.arlosoft.macrodroid).

## 📦 Instalación del Servidor

### 1. Clonar el repositorio
```bash
git clone [https://github.com/StephenRM-Dr/notipagos.git](https://github.com/StephenRM-Dr/notipagos.git)
cd notipagos
```

### 2. Clonar el repositorio


Crea un archivo `.env` o configura las siguientes variables en tu plataforma de Hosting (Koyeb):

`DB_HOST:` Host de tu base de datos PostgreSQL.

`DB_NAME:` Nombre de la base de datos.

`DB_USER:` Usuario de la base de datos.

`DB_PASS:` Contraseña.

`ADMIN_PASSWORD:` Clave para acceder al panel /admin.

`SECRET_KEY:` Una clave aleatoria para las sesiones.


### 3   . Ejecutar Localmente (Opcional)

```bash
pip install -r requirements.txt
python app.py
```

### 📱 Configuración de MacroDroid
Para que el sistema funcione, debes configurar una macro con los siguientes parámetros (o importar el archivo .macro adjunto):

__Disparador (Trigger)__: Notificación de la App "BDV digital".

__Acción__: Solicitud HTTP POST.

**Nota Importante:** deben cambiar la URL de la acción HTTP por la que les corresponde, ya que actualmente tiene  URL de `localhost`.

__URL__: `https://tu-app-koyeb.koyeb.app/webhook-bdv`(nube-koyeb)
__URL__: `https://localhost:5000/webhook-bdv` (Local)



__Cuerpo (application/json)__:

```json
{"mensaje": "[notification_title] [notification_text]"}
```


**Nota Importante:** En el README, avisa a los usuarios que deben cambiar la URL de la acción HTTP por la de ellos, ya que actualmente tiene tu URL de Koyeb.
### 🔐 Seguridad (Race Condition)
El sistema incluye protección de base de datos `FOR UPDATE` para evitar que una misma referencia de pago sea validada dos veces simultáneamente.

### 📄 Licencia
Este proyecto se distribuye bajo la licencia MIT. ¡Siéntete libre de usarlo y mejorarlo!