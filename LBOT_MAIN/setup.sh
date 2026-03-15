#!/bin/bash
# ==============================================
# Script de nettoyage et setup - L3D3B07
# ==============================================

echo "=========================================="
echo "  L3D3B07 - Nettoyage et Setup"
echo "=========================================="

# Nettoyer les virtualenvs s'ils existent
echo ""
echo "[1/4] Nettoyage des virtualenvs..."
rm -rf L3D3BOT/ 2>/dev/null
rm -rf dashboard/dashboard/ 2>/dev/null
rm -rf venv/ 2>/dev/null
rm -rf .venv/ 2>/dev/null
echo "      OK"

# Nettoyer les fichiers Python compiles
echo "[2/4] Nettoyage des fichiers compiles..."
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null
find . -type f -name "*.pyc" -delete 2>/dev/null
echo "      OK"

# Creer le virtualenv
echo "[3/4] Creation du virtualenv..."
python -m venv venv
echo "      OK"

# Installer les dependances
echo "[4/4] Installation des dependances..."
if [[ "$OSTYPE" == "msys" ]] || [[ "$OSTYPE" == "win32" ]]; then
    # Windows
    ./venv/Scripts/pip install -r requirements.txt
    ./venv/Scripts/pip install -r dashboard/requirements.txt
else
    # Linux/Mac
    ./venv/bin/pip install -r requirements.txt
    ./venv/bin/pip install -r dashboard/requirements.txt
fi
echo "      OK"

echo ""
echo "=========================================="
echo "  Setup termine!"
echo "=========================================="
echo ""
echo "Prochaines etapes:"
echo ""
echo "1. Copie .env.exemple vers .env:"
echo "   cp .env.exemple .env"
echo ""
echo "2. Remplis le fichier .env avec tes tokens"
echo ""
echo "3. Lance le bot:"
if [[ "$OSTYPE" == "msys" ]] || [[ "$OSTYPE" == "win32" ]]; then
    echo "   .\\venv\\Scripts\\python bot.py"
else
    echo "   ./venv/bin/python bot.py"
fi
echo ""
echo "4. Lance le dashboard (dans un autre terminal):"
if [[ "$OSTYPE" == "msys" ]] || [[ "$OSTYPE" == "win32" ]]; then
    echo "   cd dashboard"
    echo "   ..\\venv\\Scripts\\python app.py"
else
    echo "   cd dashboard"
    echo "   ../venv/bin/python app.py"
fi
echo ""
