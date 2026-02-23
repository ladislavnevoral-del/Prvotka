#!/bin/bash
cd ~/Prvotkar
echo "Stahuji data z ARES do lokální databáze..."
echo "Trvá cca 10-20 minut. Nevypínej okno!"
/opt/homebrew/opt/python@3.11/bin/python3.11 sync_ares.py
echo ""
echo "Hotovo! Databáze je uložena jako prvotkar.db"
read -p "Stiskni Enter pro zavření..."
