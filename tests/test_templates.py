"""Tous les templates Jinja doivent compiler (syntaxe verifiee a chaque CI)."""
import pathlib
from jinja2 import Environment

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_tous_les_templates_parse():
    files = sorted((ROOT / 'templates').rglob('*.html'))
    assert len(files) >= 30, f'seulement {len(files)} templates trouves'
    env = Environment()
    errors = []
    for p in files:
        try:
            env.parse(p.read_text(encoding='utf-8'))
        except Exception as e:
            errors.append(f'{p.relative_to(ROOT)}: {e}')
    assert errors == [], 'Templates invalides :\n' + '\n'.join(errors)
