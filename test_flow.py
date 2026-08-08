import requests

BASE = 'https://cabinet-team-manager-production.up.railway.app'
s = requests.Session()

def show(label, resp, n=600):
    print(f"\n=== {label} :: HTTP {resp.status_code} ===")
    txt = resp.text
    if resp.status_code >= 500:
        print(txt[:n])
    else:
        # show flashed messages / alerts if any
        import re
        m = re.findall(r'alert-(?:danger|success)-custom">\s*(.*?)\s*</div>', txt, re.S)
        print("alerts:", m if m else "(none)")
        print("len:", len(txt))

# 1. GET register
r = s.get(f'{BASE}/register', timeout=15)
show('GET /register', r)

# 2. POST register (unique email)
import time
email = f'flow_{int(time.time())}@example.com'
r = s.post(f'{BASE}/register', data={
    'prenom': 'Flow', 'nom': 'Test', 'email': email, 'password': 'test123', 'role': 'admin'
}, timeout=15)
show('POST /register', r)

# 3. GET login
r = s.get(f'{BASE}/login', timeout=15)
show('GET /login', r)

# 4. POST login
r = s.post(f'{BASE}/login', data={'email': email, 'password': 'test123'}, timeout=15, allow_redirects=False)
show('POST /login', r)

# 5. follow redirect to dashboard
if r.status_code in (302, 303):
    loc = r.headers.get('Location')
    r2 = s.get(BASE + loc, timeout=15)
    show(f'GET {loc} (dashboard)', r2)

# 6. team-select
r3 = s.get(f'{BASE}/team-select', timeout=15)
show('GET /team-select', r3)
