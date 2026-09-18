#!/usr/bin/env bash
set -e

echo "================================================="
echo "   SHEA: System Host for Empathetic AI - Installer"
echo "================================================="

if ! command -v python3 &> /dev/null; then
    echo "[!] Python 3.11+ is required but not found."
    exit 1
fi

echo ">> Creating isolated virtual environment..."
python3 -m venv .venv

echo ">> Installing production dependencies..."
source .venv/bin/activate
pip install --upgrade pip setuptools wheel
pip install -e .

echo ">> Bootstrapping system state and secure database..."
python -m shea.bootstrap

echo ">> Validating production environment..."
if [ ! -f "shea.db" ]; then
    echo "[!] Failed to create system database."
    exit 1
fi

echo "================================================="
echo " Installation complete! "
echo " You can now run SHEA securely:"
echo "   $ source .venv/bin/activate"
echo "   $ shea chat"
echo "================================================="