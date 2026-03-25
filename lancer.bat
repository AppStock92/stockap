@echo off
cd /d "C:\Users\lawso\Documents\GESTION DE STOCK"
set DATABASE_URL=sqlite:///stock.db
set SECRET_KEY=46d6632e8a5a6d5fc5af35543e871f5e0c92c7fd05b7b4b7bb628bbc5aa603c1
set FLASK_ENV=development
python app.py
pause