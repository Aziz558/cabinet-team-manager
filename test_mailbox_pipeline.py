"""Test complet du pipeline mailbox : login → switch equipe → process-all."""
import requests

BASE = "https://cabinet-team-manager.onrender.com"
LOGIN_EMAIL = "admin@cabinet-jmh.com"
LOGIN_PASS = "admin123"

s = requests.Session()

# 1. Login
print("=== 1. LOGIN ===")
r = s.post(f"{BASE}/login", data={"email": LOGIN_EMAIL, "password": LOGIN_PASS}, allow_redirects=False)
print(f"Login: {r.status_code} {r.headers.get('Location', 'no redirect')}")
if r.status_code == 302:
    print("✅ Login réussi")
else:
    print(f"❌ Login échoué: {r.text[:500]}")
    exit(1)

# 2. Get dashboard to activate session
print("\n=== 2. DASHBOARD ===")
r = s.get(f"{BASE}/dashboard")
print(f"Dashboard: {r.status_code}, title: {r.text[:100]}")
if "admin" in r.text.lower():
    print("✅ Session active")

# 3. Get teams to find Hamza's equipe_id
print("\n=== 3. EQUIPE ID ===")
r = s.get(f"{BASE}/api/equipes")
print(f"Equipes API: {r.status_code}")
teams_data = r.json()
print(f"Teams: {teams_data}")
hamza_id = None
for t in teams_data.get("equipes", []):
    if "Hamza" in t.get("nom", ""):
        hamza_id = t.get("id")
        break
if not hamza_id:
    # Fallback: first equipe
    for t in teams_data.get("equipes", []):
        hamza_id = t.get("id")
        break
print(f"Using equipe_id: {hamza_id}")

# 4. Switch to Hamza's equipe via /set-team
print("\n=== 4. SWITCH EQUIPE ===")
r = s.get(f"{BASE}/set-team/{hamza_id}")
print(f"Switch equipe: {r.status_code} -> {r.headers.get('Location', 'no redirect')}")

# 5. Test mailbox IMAP connection
print("\n=== 5. TEST MAILBOX ===")
r = s.post(f"{BASE}/api/test/mailbox")
print(f"Test mailbox: {r.status_code} -> {r.json()}")

# 6. Process all emails
print("\n=== 6. PROCESS ALL ===")
r = s.post(f"{BASE}/api/mailbox/process-all")
print(f"Process all: {r.status_code} -> {r.json()}")

# 6b. Process direct (debug)
print("\n=== 6b. PROCESS DIRECT (DEBUG) ===")
r = s.post(f"{BASE}/api/mailbox/process-direct")
print(f"Process direct: {r.status_code}")
print(f"Raw response: {r.text[:2000]}")
try:
    d = r.json()
    if d.get('debug'):
        print(d['debug'])
    if d.get('trace'):
        print(f"TRACE: {d['trace'][:1000]}")
    print(f"Created: {d.get('count', 0)} suggestions")
except Exception as e:
    print(f"Parse error: {e}")

# 7. Check suggestions
print("\n=== 7. CHECK SUGGESTIONS ===")
r = s.get(f"{BASE}/api/suggestions")
print(f"Suggestions: {r.status_code}")
try:
    data = r.json()
    if isinstance(data, dict):
        data = data.get("suggestions", [])
    print(f"Suggestions count: {len(data)}")
    for s_item in data:
        print(f"  - [{s_item.get('statut', '?')}] {s_item.get('titre_suggeree', s_item.get('sujet', '?'))[:60]}")
except Exception as e:
    print(f"❌ Parse error: {e}")
    print(f"  Response: {r.text[:500]}")

print("\n=== DONE ===")
