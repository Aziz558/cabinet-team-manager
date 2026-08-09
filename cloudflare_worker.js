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

const WEBHOOK_URL = "https://ton-app.onrender.com/api/mailbox/inbound";
const WEBHOOK_SECRET = "cabinet-jmh-secret-2026";
const ALLOWED_SENDERS = []; // ex: ["client1@entreprise.com"]

export default {
  async email(message, env, ctx) {
    const headers = {
      "Content-Type": "application/json",
      "User-Agent": "Cloudflare-Email-Routing/1.0",
      "X-Webhook-Secret": WEBHOOK_SECRET,
    };

    const from = message.from || "";
    const to = message.to || "";
    const subject = message.subject || "";
    const bodyPlain = message.rawBCC || "";
    const bodyHtml = "";

    const payload = {
      from: from,
      to: to,
      subject: subject,
      body_plain: bodyPlain,
      body_html: bodyHtml,
      timestamp: new Date().toISOString(),
      message_id: message.headers["message-id"] || crypto.randomUUID(),
    };

    // Filter allowed senders
    if (ALLOWED_SENDERS.length > 0) {
      const senderEmail = from.toLowerCase();
      const isAllowed = ALLOWED_SENDERS.some(allowed =>
        senderEmail === allowed.toLowerCase() ||
        senderEmail.endsWith("@" + allowed.toLowerCase().split("@")[1])
      );
      if (!isAllowed) {
        console.log(`Blocked sender: ${from}`);
        return;
      }
    }

    try {
      const resp = await fetch(WEBHOOK_URL, {
        method: "POST",
        headers: headers,
        body: JSON.stringify(payload),
        // Verify signature in the worker if needed
      });

      if (!resp.ok) {
        console.error(`Webhook failed: ${resp.status} ${resp.statusText}`);
      }
    } catch (e) {
      console.error("Webhook error:", e);
    }

    // Mark as delivered
    message.setReject(false);
  }
}
