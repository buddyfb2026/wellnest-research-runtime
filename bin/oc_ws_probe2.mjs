#!/opt/homebrew/bin/node
import process from "node:process";
const WebSocket = (await import("ws")).default;

const OC_GATEWAY_HTTP = process.env.OC_GATEWAY_HTTP;
const OC_ORIGIN = process.env.OC_ORIGIN;
if (!OC_GATEWAY_HTTP || !OC_ORIGIN) {
  console.error("need OC_GATEWAY_HTTP and OC_ORIGIN");
  process.exit(2);
}

const wsUrl = OC_GATEWAY_HTTP.replace(/^http/, "ws") + "/ws";
const client = { id: "webchat-ui", mode: "webchat", platform: "web" };

const eventNames = [
  "connect.respond",
  "connect.response",
  "connect.answer",
  "connect.solve",
  "connect.handshake",
  "client.hello",
  "hello",
  "auth.respond",
  "auth.response",
  "session.respond",
  "session.hello"
];

function runOne(eventName) {
  return new Promise((resolve) => {
    const ws = new WebSocket(wsUrl, { headers: { Origin: OC_ORIGIN } });

    let nonce = null;
    let closed = false;

    const t = setTimeout(() => {
      if (!closed) {
        console.error("TIMEOUT", eventName);
        try { ws.close(); } catch {}
      }
      resolve({ eventName, ok: false, why: "timeout" });
    }, 2500);

    ws.on("open", () => {
      console.error("OPEN", eventName);
    });

    ws.on("message", (d) => {
      const s = d.toString();
      console.error("MSG", eventName, s);

      let m = null;
      try { m = JSON.parse(s); } catch {}

      if (m && m.type === "event" && m.event === "connect.challenge") {
        nonce = m.payload?.nonce || null;
        const frame = { type: "event", event: eventName, payload: { nonce, client } };
        console.error("SEND", eventName, JSON.stringify(frame));
        ws.send(JSON.stringify(frame));
        return;
      }

      if (m && m.type === "event" && (m.event || "").startsWith("connect.")) {
        clearTimeout(t);
        try { ws.close(); } catch {}
        resolve({ eventName, ok: true, msg: s });
      }
    });

    ws.on("close", (code, reason) => {
      closed = true;
      clearTimeout(t);
      console.error("CLOSE", eventName, code, String(reason || ""));
      resolve({ eventName, ok: false, why: `close ${code} ${String(reason||"")}` });
    });

    ws.on("error", (e) => {
      closed = true;
      clearTimeout(t);
      console.error("ERR", eventName, String(e));
      resolve({ eventName, ok: false, why: `err ${String(e)}` });
    });
  });
}

(async () => {
  for (const ev of eventNames) {
    const r = await runOne(ev);
    if (r.ok) {
      console.error("FOUND", ev);
      process.exit(0);
    }
  }
  console.error("NONE_FOUND");
  process.exit(1);
})();
