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

const types = ["req","cmd","call","rpc"];
const opKeys = ["op","method","cmd","action","name"];
const pKeys = ["p","payload","params","d","data"];

const ops = [
  "connect",
  "connect.respond",
  "connect.response",
  "connect.handshake",
  "session.connect",
  "client.connect",
  "hello",
  "client.hello"
];

function frame(t, opKey, pKey, op, nonce) {
  const f = { type: t, id: 1 };
  f[opKey] = op;
  f[pKey] = { nonce, client };
  return f;
}

async function tryOne(t, opKey, pKey, op) {
  return await new Promise((resolve) => {
    const ws = new WebSocket(wsUrl, { headers: { Origin: OC_ORIGIN } });
    let nonce = null;
    let sent = false;

    const kill = setTimeout(() => {
      try { ws.close(); } catch {}
      resolve({ ok: false, why: "timeout" });
    }, 2500);

    ws.on("message", (d) => {
      const s = d.toString();
      let m = null;
      try { m = JSON.parse(s); } catch {}

      if (m && m.type === "event" && m.event === "connect.challenge" && !sent) {
        nonce = m.payload?.nonce || null;
        const f = frame(t, opKey, pKey, op, nonce);
        ws.send(JSON.stringify(f));
        sent = true;
        return;
      }

      if (sent && m) {
        clearTimeout(kill);
        try { ws.close(); } catch {}
        resolve({ ok: true, msg: s });
      }
    });

    ws.on("close", (code, reason) => {
      clearTimeout(kill);
      resolve({ ok: false, why: `close ${code} ${String(reason||"")}` });
    });

    ws.on("error", (e) => {
      clearTimeout(kill);
      resolve({ ok: false, why: `err ${String(e)}` });
    });
  });
}

(async () => {
  for (const t of types) {
    for (const opKey of opKeys) {
      for (const pKey of pKeys) {
        for (const op of ops) {
          const r = await tryOne(t, opKey, pKey, op);
          if (r.ok) {
            console.log(JSON.stringify({ type:t, opKey, pKey, op, sample:r.msg }));
            process.exit(0);
          }
          if (!r.why.includes("close 1008")) {
            console.log(JSON.stringify({ type:t, opKey, pKey, op, note:r.why }));
          }
        }
      }
    }
  }
  console.error("NO_MATCH");
  process.exit(1);
})();
