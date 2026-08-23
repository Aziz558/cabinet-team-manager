import sys
sys.path.insert(0, '.')
from app import app
rules = [str(r.rule) for r in app.url_map.iter_rules()]
critical = ['/membres', 'fiche_membre', '/ajouter_membre', '/suggestions', '/api/suggestions/refresh', '/fiscal', '/ajouter_dossier', '/assigner_equipe']
for r in critical:
    found = any(r in rule for rule in rules)
    print(f"{'OK' if found else 'MISSING'} : {r}")
print(f"Total routes: {len(rules)}")
