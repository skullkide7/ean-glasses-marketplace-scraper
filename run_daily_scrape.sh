#!/bin/bash
# run_daily_scrape.sh - Corrida diaria completa (pensada para correr 1x al día a las 8am vía launchd)
#
# 1. Refresca el directorio real de tiendas (rápido, ~1 min)
# 2. Catálogo completo + precio real por tienda de PAK'nSAVE
# 3. Catálogo completo + precio real por tienda de New World
#
# Debe correr en una Mac con IP de Nueva Zelanda (PAK'nSAVE/New World bloquean
# IPs de fuera de NZ). Si el Mac está dormido a las 8am, launchd NO lo despierta
# solo -> revisa con `pmset repeat` si quieres que despierte automáticamente.

set -e
cd "$(dirname "$0")"
source venv/bin/activate

mkdir -p output/logs
TS=$(date +%Y%m%d_%H%M)
LOG="output/logs/daily_${TS}.log"

{
  echo "=== Corrida diaria iniciada $(date) ==="

  echo "--- 1. Refrescando directorio real de tiendas ---"
  python3 discover_stores_real.py

  echo "--- 2. PAK'nSAVE: catálogo + precio real por tienda ---"
  python3 scrape_catalog_paknsave.py

  echo "--- 3. New World: catálogo + precio real por tienda ---"
  python3 scrape_catalog_new_world.py

  echo "=== Corrida diaria terminada $(date) ==="
} > "$LOG" 2>&1

echo "Log completo en $LOG"
