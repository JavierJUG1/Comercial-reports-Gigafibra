#!/usr/bin/env bash
# Instala o actualiza Comercial reports en el servidor (Rocky Linux, nginx, SELinux). Ejecutar como root desde la
# carpeta donde se subieron los archivos:
#     bash instalar_servidor.sh paquete.zip [datos.zip] [backend.env]
# - paquete.zip: release/comercial-reports_<fecha>.zip (deploy/empaquetar.py)
# - datos.zip: backend/data (Excel, .json, historial). Solo se usa si el servidor aún no tiene datos.
# - backend.env: configuración de producción. Solo se usa si el servidor aún no tiene backend/.env.
# Nunca reemplaza backend/.env, backend/data ni backend/.venv existentes. Rutas literales a propósito.
set -euo pipefail

PAQUETE="$1"
DATOS="${2:-}"
ENVF="${3:-}"
STAMP="$(date +%Y%m%d-%H%M%S)"

id -u comercial-reports >/dev/null 2>&1 || \
  useradd --system --no-create-home --home-dir "/var/www/html/Comercial reports" --shell /sbin/nologin comercial-reports

systemctl stop comercial-reports 2>/dev/null || true
mkdir -p "/var/www/html/Comercial reports" /root/comercial_reports_backups

# Respaldo del código y la configuración anteriores (si los hay)
if [ -d "/var/www/html/Comercial reports/backend/app" ]; then
  tar -czf "/root/comercial_reports_backups/codigo-$STAMP.tar.gz" -C "/var/www/html/Comercial reports" \
    --exclude=backend/.venv --exclude=backend/data .
fi

rm -rf /root/comercial_reports_deploy_pkg
mkdir -p /root/comercial_reports_deploy_pkg
unzip -q -o "$PAQUETE" -d /root/comercial_reports_deploy_pkg

# Código: se reemplaza completo (no toca backend/.env, backend/data ni backend/.venv)
rm -rf "/var/www/html/Comercial reports/backend/app" "/var/www/html/Comercial reports/backend/config" \
       "/var/www/html/Comercial reports/backend/scripts" "/var/www/html/Comercial reports/frontend" \
       "/var/www/html/Comercial reports/deploy" "/var/www/html/Comercial reports/docs"
cp -a /root/comercial_reports_deploy_pkg/. "/var/www/html/Comercial reports/"

# Datos (solo la primera vez)
if [ -n "$DATOS" ] && [ ! -e "/var/www/html/Comercial reports/backend/data/reporte/planes TV 2026.xlsx" ]; then
  mkdir -p "/var/www/html/Comercial reports/backend/data"
  unzip -q "$DATOS" -d "/var/www/html/Comercial reports/backend/data"
  echo "Datos copiados."
fi

# Configuración (solo la primera vez)
if [ -n "$ENVF" ] && [ ! -e "/var/www/html/Comercial reports/backend/.env" ]; then
  install -m 600 "$ENVF" "/var/www/html/Comercial reports/backend/.env"
  echo "backend/.env instalado."
fi

# Entorno de Python propio
if [ ! -x "/var/www/html/Comercial reports/backend/.venv/bin/python" ]; then
  python3.12 -m venv "/var/www/html/Comercial reports/backend/.venv"
fi
"/var/www/html/Comercial reports/backend/.venv/bin/python" -m pip install -q --upgrade pip
"/var/www/html/Comercial reports/backend/.venv/bin/python" -m pip install -q -r "/var/www/html/Comercial reports/backend/requirements.txt"

# Permisos: solo el usuario del servicio (nginx no necesita leer la carpeta: publica por proxy)
chown -R comercial-reports:comercial-reports "/var/www/html/Comercial reports"
find "/var/www/html/Comercial reports" -path "*/backend/.venv" -prune -o -type d -exec chmod 750 {} +
find "/var/www/html/Comercial reports" -path "*/backend/.venv" -prune -o -type f -exec chmod 640 {} +
chmod 600 "/var/www/html/Comercial reports/backend/.env"

# SELinux: el Python del entorno debe poder ejecutarse como servicio (sin esto: 203/EXEC Permission denied).
# semanage no acepta espacios en la ruta: se escribe "\s" en lugar del espacio de "Comercial reports".
if ! semanage fcontext -l | grep -qF 'Comercial\sreports/backend/\.venv/bin'; then
  semanage fcontext -a -t bin_t '/var/www/html/Comercial\sreports/backend/\.venv/bin(/.*)?'
fi
restorecon -R "/var/www/html/Comercial reports"

install -m 644 "/var/www/html/Comercial reports/deploy/comercial-reports.service" /etc/systemd/system/comercial-reports.service
restorecon /etc/systemd/system/comercial-reports.service
systemctl daemon-reload
systemctl enable comercial-reports >/dev/null 2>&1
systemctl restart comercial-reports
sleep 4
systemctl is-active comercial-reports
rm -rf /root/comercial_reports_deploy_pkg
echo "Instalación lista."
