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

const ws = new WebSocket(wsUrl, { headers: { Origin: OC_ORIGIN } });

let nonce = null;
let step = 0;

const candidates = [
  (n) => ({ type: "event", event: "connect.respond", payload: { nonce: n, client } }),
  (n) => ({ type: "event", event: "connect.response", payload: { nonce: n, client } }),
  (n) => ({ type: "connect.respond", payload: { nonce: n, client } }),
  (n) => ({ type: "connect.response", payload: { nonce: n, client } }),
  (n) => ({ type: "connect.hello", payload: { nonce: n, client } }),
  (n) => ({ type: "event", event: "connect.hello", payload: { nonce: n, client } })
];

function sendNext() {
  if (!nonce) return;
  if (step >= candidates.length) {
    console.error("NO_ACK");
    process.exit(3);
  }
  const msg = candidates[step++](nonce);
  console.error("SEND", JSON.stringify(msg));
  ws.send(JSON.stringify(msg));
}

ws.on("open", () => {
  console.error("OPEN");
});

ws.on("message", (d) => {
  const s = d.toString();
  console.error("MSG", s);

  let m = null;
  try { m = JSON.parse(s); } catch {}

  if (m && m.type === "event" && m.event === "connect.challenge") {
    nonce = m.payload?.nonce || null;
    sendNext();
    return;
  }

  if (m && (m.event === "connect.ok" || m.event === "connect.accepted" || m.event === "connect.ready" || m.type === "connect.ok")) {
    console.error("ACK");
    process.exit(0);
  }

  if (m && m.type === "event" && (m.event || "").startsWith("connect.")) {
    if (nonce) sendNext();
  }
});

ws.on("close", (c, r) => {
  console.error("CLOSE", c, String(r || ""));
  process.exit(4);
});

ws.on("error", (e) => {
  console.error("ERR", String(e));
  process.exit(5);
});

setTimeout(() => {
  console.error("TIMEOUT");
  process.exit(6);
}, 8000);
