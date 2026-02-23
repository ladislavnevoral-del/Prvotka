#!/bin/bash
cd ~/Prvotkar
echo "Spouštím Prvotkář 3.0 backend..."
if [ ! -f "prvotkar.db" ]; then
  echo "⚠️  Databáze nenalezena. Spouštím sync_ares.py (10-20 minut)..."
  /opt/homebrew/opt/python@3.11/bin/python3.11 sync_ares.py
fi
/opt/homebrew/opt/python@3.11/bin/python3.11 main.py
