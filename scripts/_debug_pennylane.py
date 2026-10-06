# -*- coding: utf-8 -*-
"""Debug script for pennylane.html."""
import os

BASE = r"C:\Users\Mohamed Aziz JLASSI\Desktop\aziz gestion de cabinet\cabinet_team_manager"
path = os.path.join(BASE, "templates", "pennylane.html")

with open(path, "r", encoding="utf-8") as f:
    content = f.read()

# Find the card div
idx = content.find('<div class="col-md-4 col-lg-3">')
if idx >= 0:
    print("Found col-md-4 at", idx)
    print(repr(content[idx:idx+500]))
else:
    print("col-md-4 not found")

# Check if UI already exists
if "syncSelectedTva" in content:
    print("\nUI de selection DEJA presente")
else:
    print("\nUI de selection NON presente")

# Check if checkboxes already exist
if "pl-dossier-check" in content:
    print("Checkboxes DEJA presentes")
else:
    print("Checkboxes NON presentes")