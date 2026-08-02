@echo off
cd /d C:\Users\Mohamed Aziz JLASSI\Downloads\cabinet_team_manager\cabinet_team_manager
call venv\Scripts\activate
python -c "from app import db; db.create_all(); print('Base de donnees initialisee.')"
python -c "from app import app; app.run(debug=True, port=5000, use_reloader=False)"
