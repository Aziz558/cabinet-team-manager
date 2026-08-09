/**
 * Cloudflare Worker — Cloudflare Email Routing → Webhook
 *
 * Reçoit les emails via Cloudflare Email Routing,
 * les convertit en format standard,
 * les POSTe vers https://ton-app.onrender.com/api/mailbox/inbound
 *
 * Activation :
 * 1. Crée une route Cloudflare Email : *.domaine.com → Worker
 * 2. Dans le Worker, configure WEBHOOK_URL et WEBHOOK_SECRET
 */

const WEBHOOK_URL = env.WEBHOOK_URL || "https://ton-app.onrender.com/api/mailbox/inbound";
const WEBHOOK_SECRET = env.WEBHOOK_SECRET || "";
const ALLOWED_SENDERS = (env.ALLOWED_SENDERS || "").split(",").filter(Boolean);

function extractHeaders(rawHeaders) {
  const headers = {};
  if (!rawHeaders) return headers;
  try {
    const lines = String(rawHeaders).split("\n");
    for (const line of lines) {
      const idx = line.indexOf(":");
      if (idx > -1) {
        const key = line.slice(0, idx).trim().toLowerCase();
        const val = line.slice(idx + 1).trim();
        headers[key] = val;
      }
    }
  } catch (e) {
    console.error("Header parse error:", e);
  }
  return headers;
}

function extractTextPart(raw) {
  if (!raw) return "";
  const str = String(raw);
  const m = str.match(/Content-Type:\s*text/plain[^]*?\r?\n\r?\n([\s\S]*?)(?:\r?\n--|\z)/i);
  if (m) return m[1].trim();
  return str;
}

export default {
  async email(message, env, ctx) {
    const raw = await message.text();
    const headers = extractHeaders(message.headers ? message.headers.raw : raw);
    const from = (message.from || headers.from || headers.sender || "").trim();
    const to = (message.to || headers.to || headers["x-original-to"] || "").trim();
    const subject = (message.subject || headers.subject || "").trim();
    const bodyPlain = extractTextPart(raw) || String(raw).slice(0, 2000);
    const bodyHtml = "";

    const payload = {
      from,
      to,
      subject,
      body_plain: bodyPlain,
      body_html: bodyHtml,
      timestamp: new Date().toISOString(),
      message_id: headers["message-id"] || headers["message-id"] || crypto.randomUUID(),
    };

    if (ALLOWED_SENDERS.length > 0) {
      const senderEmail = from.toLowerCase();
      const isAllowed = ALLOWED_SENDERS.some(allowed => {
        const a = allowed.toLowerCase();
        return senderEmail === a || senderEmail.endsWith("@" + a.split("@")[1]);
      });
      if (!isAllowed) {
        console.log(`Blocked sender: ${from}`);
        return;
      }
    }

    try {
      const resp = await fetch(WEBHOOK_URL, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "User-Agent": "Cloudflare-Email-Routing/1.0",
          "X-Webhook-Secret": WEBHOOK_SECRET,
        },
        body: JSON.stringify(payload),
      });

      if (!resp.ok) {
        console.error(`Webhook failed: ${resp.status} ${resp.statusText}`);
      }
    } catch (e) {
      console.error("Webhook error:", e);
    }

    message.setReject(false);
  },
};
