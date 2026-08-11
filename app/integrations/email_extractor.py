"""
Extracteur Intelligent d'Emails pour Suggestion de Tâches.

Extrait maximum d'informations des emails (corps + PDFs joints),
utilise LLM avec contexte riche (dossiers existants, profil manager),
et crée des suggestions de tâches intelligentes avec raisonnement logique.

Performance optimisée pour rapidité + qualité maximale.
"""

from __future__ import annotations

import json
import logging
import re
from email import policy
from email.parser import BytesParser
from io import BytesIO
from typing import Any, Dict, List, Optional, Tuple

try:
    import fitz  # PyMuPDF pour extraction PDF
except ImportError:
    fitz = None

from app import app, db
from app.models import SuggestionTache, Dossier, User, Equipe

logger = logging.getLogger(__name__)


def extract_pdf_text(msg) -> List[str]:
    """Extract text from all PDF attachments in email. Fast and efficient."""
    texts = []
    if not fitz:
        return texts

    for part in msg.walk():
        # Skip non-attachments and non-PDFs
        if part.get_content_maintype() != 'application':
            continue
        if part.get_content_subtype() != 'pdf':
            continue

        filename = part.get_filename()
        payload = part.get_payload(decode=True)
        if not payload:
            continue

        try:
            pdf_bytes = BytesIO(payload)
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            for page in doc:
                page_text = page.get_text()
                if page_text.strip():
                    texts.append(f"[PDF: {filename}] {page_text[:2000]}")
            doc.close()
        except Exception as e:
            logger.warning(f"PDF extraction failed for {filename}: {e}")
            continue

    return texts


def extract_email_content(msg) -> Tuple[str, str, List[str]]:
    """Extract subject, body (plain + html), and PDF texts from email message."""
    subject = ""
    body_plain = ""
    body_html = ""
    pdf_texts = []

    try:
        # Decode subject
        from email.header import decode_header
        decoded_subject = decode_header(msg.get("Subject", ""))
        parts = []
        for part, charset in decoded_subject:
            if isinstance(part, bytes):
                parts.append(part.decode(charset or 'utf-8', errors='replace'))
            else:
                parts.append(part)
        subject = ' '.join(parts)
    except Exception:
        subject = msg.get("Subject", "") or ""

    # Get message as bytes for parser
    raw = msg.as_bytes() if hasattr(msg, 'as_bytes') else b""
    if raw:
        parser = BytesParser(policy=policy.default)
        parsed = parser.parsebytes(raw)
        subject = parsed.get("Subject", subject)
    else:
        parsed = msg

    # Extract body
    if parsed.is_multipart():
        for part in parsed.walk():
            content_type = part.get_content_type()
            content_disp = str(part.get("Content-Disposition", ""))

            # Skip attachments for body extraction
            if "attachment" in content_disp.lower():
                continue

            if content_type == "text/plain" and not body_plain:
                try:
                    payload = part.get_payload(decode=True)
                    if payload:
                        charset = part.get_content_charset() or 'utf-8'
                        body_plain = payload.decode(charset, errors='replace')
                except Exception:
                    pass
            elif content_type == "text/html" and not body_html:
                try:
                    payload = part.get_payload(decode=True)
                    if payload:
                        charset = part.get_content_charset() or 'utf-8'
                        body_html = payload.decode(charset, errors='replace')
                except Exception:
                    pass
    else:
        try:
            payload = parsed.get_payload(decode=True)
            if payload:
                charset = parsed.get_content_charset() or 'utf-8'
                ct = parsed.get_content_type()
                if ct == "text/plain":
                    body_plain = payload.decode(charset, errors='replace')
                elif ct == "text/html":
                    body_html = payload.decode(charset, errors='replace')
        except Exception:
            pass

    # Extract PDFs
    pdf_texts = extract_pdf_text(parsed)

    return subject.strip(), body_plain.strip(), pdf_texts


def load_dossiers_for_context() -> List[Dict[str, Any]]:
    """Load existing dossiers for LLM context. Optimized for speed."""
    dossiers = []
    try:
        for d in Dossier.query.limit(200).all():
            dossiers.append({
                'id': d.id,
                'numero': d.numero_dossier,
                'intitule': d.intitule,
            })
    except Exception as e:
        logger.warning(f"Failed to load dossiers: {e}")
    return dossiers


def load_manager_context() -> Dict[str, Any]:
    """Load manager/team context for LLM."""
    context = {
        'current_equipe_id': None,
        'equipe_name': None,
        'manager_name': None,
    }
    try:
        from flask import session
        equipe_id = session.get('current_equipe_id')
        if equipe_id:
            equipe = Equipe.query.get(equipe_id)
            if equipe:
                context['current_equipe_id'] = equipe.id
                context['equipe_name'] = equipe.nom
                if equipe.manager:
                    context['manager_name'] = f"{equipe.manager.prenom} {equipe.manager.nom}"
    except Exception:
        pass
    return context


def _build_smart_prompt(subject: str, body: str, pdf_texts: List[str],
                        dossiers: List[Dict], manager_ctx: Dict[str, Any]) -> str:
    """Build a rich LLM prompt with maximum context for intelligent extraction.

    This prompt is designed to:
    1. Force the LLM to read ALL content (subject, body, PDFs)
    2. Match against existing dossiers
    3. Reason logically about task creation
    4. Extract structured, actionable data
    5. Be fast but thorough
    """

    # Build dossier list string
    dossier_list = ""
    if dossiers:
        dossier_list = "\nDOSSIERS EXISTANTS DANS L'APPLICATIF:\n"
        for d in dossiers:
            dossier_list += f"  - {d['numero']} ({d['intitule']})\n"
        dossier_list += "\n"

    # Build manager context
    manager_info = ""
    if manager_ctx.get('equipe_name'):
        manager_info = f"\n- Équipe actuelle: {manager_ctx['equipe_name']}"
        if manager_ctx.get('manager_name'):
            manager_info += f"\n- Manager: {manager_ctx['manager_name']}"

    # Build PDF content
    pdf_content = ""
    if pdf_texts:
        pdf_content = "\nPIECES JOINTES (PDF):\n"
        for pdf_text in pdf_texts[:5]:  # Limit to 5 PDFs for speed
            pdf_content += f"{pdf_text[:1500]}\n\n"

    prompt = f"""Tu es un assistant comptable expert pour le Cabinet JMH{manager_info}.

MISSION: Analyser cet email et extraire une tâche professionnelle actionnable avec maximum de précision.

CONTEXTE:
- Cabinet comptable français
- Gère déclarations fiscales, bilans, TVA, paie, dossiers clients
- Vérifie d'abord les dossiers existants avant de créer

INSTRUCTIONS D'ANALYSE (SUCCESIVE):
1. LIS le sujet ET le corps de l'email ENTIEREMENT
{f"2. LIS tous les documents PDF joints ({len(pdf_texts)} PDF trouvé(s))" if pdf_texts else "2. PAS de pièces jointes"}
3. CHERCHE dans l'email: dates, actions requises, noms de dossiers, priorités implicites
4. VERIFIE dans {len(dossiers)} dossiers existants si un dossier correspond
5. RAISONNE: quelle est l'action concrète à faire ?

REGLE SPECIALE POUR PDF:
- Si des PDF sont joints, EXTRAIS les informations importantes (montants, dates, références)
- INCORPORE ces infos dans la description de la tâche
- Exemple: "Vérifier les factures de SOPARK (3 factures: #123, #124, #125)"

REGLE POUR DOSSIERS:
- Si tu reconnais un dossier existant, utilise son ID et son nom
- Si c'est un nouveau client/dossier, note "nouveau_dossier"
- Ne NEVER créer de doublon sans vérifier d'abord

REGLE DE PRIORITE:
- "urgent", "important", "deadline" → "haute"
- "normale", "standard" → "moyenne"
- "pas pressé", "quand tu peux" → "basse"

REGLE POUR DATE:
- Extrait la date d'échéance si mentionnée
- Si pas de date, mets "2026-08-31" (fin de mois par défaut)
- Formats courants: JJ/MM/AAAA, "avant le X", "échéance: ..."

{dossier_list}EMAIL À ANALYSER:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SUJET: {subject}

CORPS:
{body[:5000] if body else "(vide)"}
{pdf_content}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Réponds STRICTEMENT en JSON (PAS de texte autour):
{{
  "titre": "Titre court de la tâche (max 80 chars)",
  "description": "Description détaillée avec infos clés de l'email ET des PDF",
  "dossier_id": id_dossier_existants_ou_null,
  "dossier_nom": "nom_dossier_ou_nouveau_dossier",
  "priorite": "haute|moyenne|basse",
  "date_echeance": "AAAA-MM-JJ",
  "action_concrete": "Phrase décrivant l'action EXACTE à faire",
  "notes_interne": "Notes utiles pour le manager (1-2 phrases)"
}}

Exemple de bonne réponse:
{{"titre": "Déclaration TVA Trimestre 2 - SOPARK", "description": "Préparer et envoyer la déclaration CA3 pour SOPARK. 3 factures à vérifier (PDF joint). Deadline: 15/08/2026.", "dossier_id": 5, "dossier_nom": "SOPARK", "priorite": "haute", "date_echeance": "2026-08-15", "action_concrete": "Vérifier 3 factures et préparer déclaration CA3 SOPARK T2 2026", "notes_interne": "Client a envoyé 3 factures en PDF - à traiter en priorité"}}"""

    return prompt


def _parse_llm_response(raw: str) -> Optional[Dict[str, Any]]:
    """Parse LLM JSON response with robust error handling."""
    try:
        raw = raw.strip()
        # Remove markdown code blocks
        if raw.startswith("```"):
            raw = re.sub(r'```(?:json)?', '', raw, flags=re.IGNORECASE)
        if raw.startswith("{"):
            # Find the last } to handle trailing text
            last_brace = raw.rfind("}")
            if last_brace > 0:
                raw = raw[:last_brace + 1]

        data = json.loads(raw)
        if not isinstance(data, dict):
            return None

        # Validate and normalize
        return {
            'titre': str(data.get('titre', '')).strip()[:200],
            'description': str(data.get('description', '')).strip()[:1000],
            'dossier_id': _parse_dossier_id(data.get('dossier_id')),
            'dossier_nom': str(data.get('dossier_nom', '')).strip()[:200],
            'priorite': str(data.get('priorite', 'moyenne')).strip().lower(),
            'date_echeance': str(data.get('date_echeance', '2026-08-31')).strip(),
            'action_concrete': str(data.get('action_concrete', '')).strip()[:300],
            'notes_interne': str(data.get('notes_interne', '')).strip()[:500],
        }
    except (json.JSONDecodeError, ValueError, TypeError) as e:
        logger.warning(f"LLM JSON parse failed: {e}")
        return None


def _parse_dossier_id(val: Any) -> Optional[int]:
    """Parse dossier_id safely."""
    if val is None:
        return None
    if isinstance(val, int):
        return val if val > 0 else None
    if isinstance(val, str):
        val = val.strip().lower()
        if val in ('null', 'none', '""', "''", 'nouveau_dossier', 'nouveau', 'new'):
            return None
        try:
            return int(val) if int(val) > 0 else None
        except (ValueError, TypeError):
            return None
    return None


def _normalize_priorite(priorite: str) -> str:
    """Normalize priority to standard values."""
    priorite = priorite.lower().strip()
    if priorite in ('urgent', 'haute', 'high', 'critical'):
        return 'haute'
    elif priorite in ('basse', 'low', 'pas_urgent'):
        return 'basse'
    return 'moyenne'


def _normalize_date(date_str: str) -> str:
    """Normalize date to YYYY-MM-DD format."""
    date_str = date_str.strip()

    # Already YYYY-MM-DD
    if re.match(r'^\d{4}-\d{2}-\d{2}$', date_str):
        return date_str

    # Try DD/MM/YYYY
    m = re.match(r'^(\d{1,2})/(\d{1,2})/(\d{4})$', date_str)
    if m:
        day, month, year = m.groups()
        return f"{year}-{month.zfill(2)}-{day.zfill(2)}"

    # Try extracting date from text like "avant le 15/08/2026"
    m = re.search(r'(\d{1,2})/(\d{1,2})/(\d{4})', date_str)
    if m:
        day, month, year = m.groups()
        return f"{year}-{month.zfill(2)}-{day.zfill(2)}"

    return date_str[:10] if len(date_str) >= 10 else "2026-08-31"


def analyze_email_intelligent(subject: str, body: str, pdf_texts: List[str],
                               sender: str = "") -> Optional[Dict[str, Any]]:
    """Main entry point: analyze email with maximum intelligence and speed.

    Returns dict with: titre, description, dossier_id, dossier_nom,
    priorite, date_echeance, action_concrete, notes_interne
    Or None if no actionable task found.
    """

    from app.integrations.openrouter import OpenRouterClient

    # Load context (fast)
    dossiers = load_dossiers_for_context()
    manager_ctx = load_manager_context()

    # Build rich prompt
    prompt = _build_smart_prompt(subject, body, pdf_texts, dossiers, manager_ctx)

    # Call LLM
    try:
        llm = OpenRouterClient()
        if not llm.is_configured():
            logger.warning("OpenRouter not configured")
            return None

        messages = [
            {"role": "system", "content": "Tu es un assistant comptable expert du Cabinet JMH. Tu extrais des tâches actionnables des emails avec maximum de précision. Tu réponds STRICTEMENT en JSON."},
            {"role": "user", "content": prompt},
        ]

        # Use a fast but powerful model
        raw = llm.chat(messages, model="meta-llama/llama-3.3-70b-instruct-free")
        if not raw:
            return None

    except Exception as e:
        logger.warning(f"LLM analysis failed: {e}")
        return None

    # Parse response
    result = _parse_llm_response(raw)
    if not result:
        logger.warning("Failed to parse LLM response")
        return None

    # Validate and clean
    if not result['titre']:
        return None

    result['priorite'] = _normalize_priorite(result['priorite'])
    result['date_echeance'] = _normalize_date(result['date_echeance'])

    # If no dossier found but we have PDFs or body hints, try regex fallback
    if result['dossier_id'] is None:
        result['dossier_id'] = _find_dossier_by_regex(subject, body, pdf_texts)

    # Use action_concrete as title if title is too generic
    if result['titre'] in ('Tâche', 'Task', 'Action', ''):
        result['titre'] = result.get('action_concrete', result['titre'])[:200]

    # Add PDF info to description if present
    if pdf_texts and f"[PDF:" not in result['description']:
        result['description'] = f"[PDF(s) joint(s)] {result['description']}"

    return result


def _find_dossier_by_regex(subject: str, body: str, pdf_texts: List[str]) -> Optional[int]:
    """Fallback regex dossier matching."""
    text = f"{subject} {body} {' '.join(pdf_texts[:2])}"
    m = re.search(r'(?:dossier|client|affaire|société|sarl|sas|sarl)\s*[:\s\-]*([A-Za-z\w\-]{2,30})', text, re.I)
    if m:
        key = m.group(1).strip()
        try:
            dossier = Dossier.query.filter(
                (Dossier.numero_dossier.ilike(f"%{key}%")) |
                (Dossier.intitule.ilike(f"%{key}%"))
            ).first()
            if dossier:
                return dossier.id
        except Exception:
            pass
    return None


def create_suggestion_from_analysis(subject: str, body: str, pdf_texts: List[str],
                                     uid: str, sender: str = "") -> Optional[SuggestionTache]:
    """Create a SuggestionTache from intelligent email analysis.

    Returns the created suggestion or None if no task extracted.
    """
    analysis = analyze_email_intelligent(subject, body, pdf_texts, sender)
    if not analysis:
        return None

    # Extract action_concrete for better task description
    task_desc = analysis.get('action_concrete', analysis['description'])[:500]

    suggestion = SuggestionTache(
        sujet=subject[:200],
        corps=body or "",
        dossier_id=analysis['dossier_id'],
        titre_suggere=analysis['titre'],
        description_suggeree=f"{task_desc}\n\nDétails: {analysis['description'][:500]}",
        mail_uid=uid,
        priorite_suggeree=analysis['priorite'],
        statut="en_attente",
    )

    db.session.add(suggestion)
    db.session.commit()
    return suggestion


def quick_extract_from_body(body: str, subject: str) -> Optional[str]:
    """Quick regex fallback when LLM is unavailable."""
    text = f"{subject} {body}"
    triggers = [
        r"(?:à faire|action|tâche|faire|préparer|valider|envoyer|merci de)\s*[:\s\-]*\s*(.+)",
    ]
    for pat in triggers:
        m = re.search(pat, text, re.I | re.S)
        if m:
            return m.group(1).strip().split("\n")[0][:200]
    return None
