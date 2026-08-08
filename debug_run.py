import ast, os, glob, sys
from app import app, db

with app.app_context():
    results = []

    # 1. Syntax check on routes.py
    try:
        with open(os.path.join(app.root_path, 'routes.py')) as f:
            ast.parse(f.read())
        results.append(('Syntaxe routes.py', 'ok', 'OK'))
    except Exception as e:
        results.append(('Syntaxe routes.py', 'error', str(e)))

    # 2. Database connection
    try:
        db.session.execute(db.text('SELECT 1'))
        results.append(('Connexion base de données', 'ok', 'OK'))
    except Exception as e:
        results.append(('Connexion base de données', 'error', str(e)))

    # 3. Templates count
    try:
        templates = glob.glob(os.path.join(app.root_path, '..', 'templates', '*.html'))
        results.append(('Templates', 'ok', f'{len(templates)} templates trouvés'))
    except Exception as e:
        results.append(('Templates', 'error', str(e)))

    # 4. Upload folder
    try:
        upload_folder = app.config.get('UPLOAD_FOLDER')
        exists = upload_folder and os.path.isdir(upload_folder)
        results.append(('Dossier uploads', 'ok' if exists else 'warning', f'Upload folder: {upload_folder} (exists={exists})'))
    except Exception as e:
        results.append(('Dossier uploads', 'error', str(e)))

    # 5. Mailbox config
    try:
        from app.integrations.mailbox import MailboxClient
        client = MailboxClient()
        configured = client.is_configured()
        user_display = client.user[:3] + '***' if client.user else 'user=None'
        results.append(('Boîte mail (credentials)', 'ok' if configured else 'warning', f'Configured={configured}, user={user_display}'))
    except Exception as e:
        results.append(('Boîte mail (credentials)', 'error', str(e)))

    # 6. LLM config
    try:
        from app.integrations.openrouter import OpenRouterClient
        llm = OpenRouterClient()
        configured = llm.is_configured()
        api_key = app.config.get('OPENROUTER_API_KEY', '') or ''
        results.append(('LLM (OpenRouter)', 'ok' if configured else 'warning', f'Configured={configured}, api_key_set={bool(api_key)}'))
    except Exception as e:
        results.append(('LLM (OpenRouter)', 'error', str(e)))

    # 7. Static files
    try:
        missing = []
        for f in ['img/logo-jmh.png', 'css/style.css']:
            path = os.path.join(app.static_folder, f)
            if not os.path.exists(path):
                missing.append(f)
        results.append(('Fichiers statiques', 'ok' if not missing else 'warning', 'Manquants: ' + ', '.join(missing) if missing else 'Tous présents'))
    except Exception as e:
        results.append(('Fichiers statiques', 'error', str(e)))

    # 8. Routes accessibility
    try:
        from flask import url_for
        routes_ok = 0
        routes_err = []
        routes_with_args = []
        for rule in app.url_map.iter_rules():
            if rule.arguments:
                routes_with_args.append(rule.rule)
                continue
            try:
                url_for(rule.endpoint)
                routes_ok += 1
            except Exception:
                routes_err.append(rule.rule)
        results.append(('Routes accessibles', 'ok' if not routes_err else 'warning', f'{routes_ok} OK, {len(routes_err)} erreurs, {len(routes_with_args)} avec arguments'))
    except Exception as e:
        results.append(('Routes accessibles', 'error', str(e)))

    # 9. Models
    try:
        from app.models import User, Dossier, Tache, Notification, SuggestionTache, AppSetting, Equipe, CommentaireTache, Performance
        results.append(('Modèles SQLAlchemy', 'ok', 'Tous importables'))
    except Exception as e:
        results.append(('Modèles SQLAlchemy', 'error', str(e)))

    # Display results
    print()
    print("=" * 60)
    print("DIAGNOSTIC DE L'APPLICATION")
    print("=" * 60)
    for check, status, message in results:
        icon = '✅' if status == 'ok' else '⚠️' if status == 'warning' else '❌'
        print(f'{icon} {check}: {message}')
    print("=" * 60)
