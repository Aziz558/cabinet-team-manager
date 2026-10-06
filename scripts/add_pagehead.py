"""Ajoute le page-head sur les 6 pages manquantes."""
import os

page_head_tpl = """<div class="page-head animate-fade-in-up">
    <div class="page-head-main">
        <span class="page-head-icon"><i class="bi {icon}"></i></span>
        <div class="page-head-titles">
            <h2>{title}</h2>
            <p class="page-head-sub">{subtitle}</p>
        </div>
    </div>
</div>
"""

pages = [
    ('checklist.html', 'bi-journal-check', 'Checklist métier', 'Obligations fiscales et sociales'),
    ('fiscal.html', 'bi-calendar-check', 'Tableau de bord fiscal', 'Impôts, TVA et déclarations'),
    ('mailbox.html', 'bi-envelope', 'Boîte mail', 'Notifications et suggestions automatiques'),
    ('suggestions.html', 'bi-lightbulb', 'Suggestions de tâches', 'Propositions IA et emails'),
    ('suivi_social.html', 'bi-people', 'Suivi Social', 'DSN, paie et pole social'),
    ('profil.html', 'bi-person', 'Mon profil', 'Mes informations et paramètres'),
]

base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
templates = os.path.join(base, 'templates')

for fname, icon, title, subtitle in pages:
    path = os.path.join(templates, fname)
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    block = '{% block content %}'
    if block in content and 'page-head' not in content:
        head = page_head_tpl.format(icon=icon, title=title, subtitle=subtitle)
        content = content.replace(block, block + '\n' + head, 1)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f'OK: {fname}')
    else:
        print(f'SKIP: {fname} (deja present ou pas de block content)')