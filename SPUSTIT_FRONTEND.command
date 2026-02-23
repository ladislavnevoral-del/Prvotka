#!/bin/bash
cd "$(dirname "$0")"
echo "================================"
echo "  Prvotkář 3.0 - frontend běží"
echo "  Otevři Chrome: http://localhost:3000"
echo "  Nezavírej toto okno!"
echo "================================"
/opt/homebrew/opt/python@3.11/bin/python3.11 -m http.server 3000
