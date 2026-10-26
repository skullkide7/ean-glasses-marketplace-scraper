#!/bin/bash
# run_manual_scrape.command - Corrida manual completa
#
# Doble click en Finder (o ./run_manual_scrape.command desde Terminal) para
# correr ahora mismo lo mismo que corre solo todos los días a las 8am:
#   1. Refresca el directorio real de tiendas
#   2. Catálogo completo + precio real por tienda de PAK'nSAVE
#   3. Catálogo completo + precio real por tienda de New World
#
# Tarda varias horas. Si la cierras a mitad de camino, no se pierde nada:
# las tiendas ya procesadas quedan con precio de hoy, el resto se queda con
# el último precio conocido hasta la próxima corrida (automática o manual).
#
# Debe correr en este Mac con IP de Nueva Zelanda (si usas VPN, apágala primero).

cd "$(dirname "$0")"
echo "=== Corrida manual iniciada $(date) ==="
echo "(esto puede tardar varias horas - puedes dejar esta ventana abierta y minimizarla)"
echo

source venv/bin/activate

echo "--- 1. Refrescando directorio real de tiendas ---"
python3 discover_stores_real.py
echo

echo "--- 2. PAK'nSAVE: catálogo + precio real por tienda ---"
python3 scrape_catalog_paknsave.py
echo

echo "--- 3. New World: catálogo + precio real por tienda ---"
python3 scrape_catalog_new_world.py
echo

echo "=== Corrida manual terminada $(date) ==="
echo "Presiona Enter para cerrar esta ventana."
read
