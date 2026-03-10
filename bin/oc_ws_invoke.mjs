#!/opt/homebrew/bin/node
import fs from "fs";
import WebSocket from "ws";

function uuid() {
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, c => {
    const r = (Math.random()*16)|0;
    const v = c === "x" ? r : (r&0x3)|0x8;
    return v.toString(16);
  });
}

function readToken() {
  const f = process.env.OC_GATEWAY_TOKEN_FILE || (process.env.HOME + "/ri_db/secrets/gateway_token.txt");
  return fs.readFileSync(f, "utf8").trim();
}

function wsUrlFromHttp(httpUrl) {
  return httpUrl.replace(/^http:/, "ws:").replace(/^https:/, "wss:");
}

function extractText(msg) {
  if (!msg || typeof msg !== "object") return "";
  if (typeof msg.text === "string") return msg.text;
  const c = msg.content;
  if (Array.isArray(c)) {
    return c.filter(x => x && x.type === "text" && typeof x.text === "string").map(x => x.text).join("");
  }
  return "";
}

const gatewayHttp = process.env.OC_GATEWAY_HTTP || "http://127.0.0.1:18791";
const wsUrl = process.env.OC_GATEWAY_WS || wsUrlFromHttp(gatewayHttp);
const token = process.env.OC_GATEWAY_TOKEN || readToken();
const origin = process.env.OC_ORIGIN || "http://127.0.0.1:18789";

const agentId = process.argv[2];
const prompt = process.argv.slice(3).join(" ").trim();

if (!agentId || !prompt) {
  console.error("usage: oc_ws_invoke.mjs <agentId> <prompt>");
  process.exit(2);
}

const sessionKey = (process.env.OC_SESSION_KEY && process.env.OC_SESSION_KEY.trim()) ? process.env.OC_SESSION_KEY.trim() : `agent:${agentId}:main`;

const ws = new WebSocket(wsUrl, { headers: { Origin: origin } });
const pending = new Map();

function sendReq(id, method, params) {
  ws.send(JSON.stringify({type:"req", id, method, params}));
}

function req(method, params, timeoutMs=20000) {
  const id = uuid();
  sendReq(id, method, params);
  return new Promise((resolve, reject) => {
    pending.set(id, {resolve, reject});
    setTimeout(() => reject(new Error("timeout waiting for " + method)), timeoutMs);
  });
}

let didConnect = false;
let runId = null;

async function doConnect() {
  if (didConnect) return;
  didConnect = true;

  await req("connect", {
    minProtocol: 3,
    maxProtocol: 3,
    client: {
      id: "webchat-ui",
      version: "dev",
      platform: "web",
      mode: "webchat",
      instanceId: uuid()
    },
    role: "operator",
    scopes: ["operator.admin","operator.approvals","operator.pairing"],
    caps: [],
    auth: { token },
    userAgent: "ri-ws-invoke",
    locale: "en-US"
  }, 25000);

  const payload = await req("chat.send", {
    sessionKey,
    message: prompt,
    deliver: false,
    idempotencyKey: uuid()
  }, 25000);

  if (payload && typeof payload.runId === "string") runId = payload.runId;
}


console.error("WS_DEBUG", JSON.stringify({
  gatewayHttp,
  wsUrl,
  origin,
  tokenLength: token ? token.length : 0,
  sessionKey
}, null, 2));

ws.on("unexpected-response", (_req, res) => {
  console.error("WS_UNEXPECTED_RESPONSE", res.statusCode, res.statusMessage);
  console.error("WS_UNEXPECTED_HEADERS", JSON.stringify(res.headers, null, 2));
  let body = "";
  res.on("data", chunk => { body += chunk.toString(); });
  res.on("end", () => {
    if (body) console.error("WS_UNEXPECTED_BODY", body);
  });
});

ws.on("close", (code, reason) => {
  console.error("WS_CLOSE", code, reason ? reason.toString() : "");
});

const finalPromise = new Promise((resolve, reject) => {
  const t = setTimeout(() => reject(new Error("timeout waiting for final chat")), 180000);

  ws.on("message", (buf) => {
    let obj;
    try { obj = JSON.parse(String(buf)); } catch { return; }

    if (obj.type === "event" && obj.event === "chat") {
      const p = obj.payload;
      if (!p) return;
      if (runId && p.runId && p.runId !== runId) return;

      if (p.state === "final") {
        clearTimeout(t);
        resolve(extractText(p.message).trimEnd());
      }
      if (p.state === "error") {
        clearTimeout(t);
        reject(new Error(p.errorMessage || "chat error"));
      }
      if (p.state === "aborted") {
        clearTimeout(t);
        resolve(extractText(p.message).trimEnd());
      }
    }

    if (obj.type === "res") {
      const h = pending.get(obj.id);
      if (!h) return;
      pending.delete(obj.id);
      obj.ok ? h.resolve(obj.payload) : h.reject(new Error(obj.error?.message || "request failed"));
    }
  });

  ws.on("error", (e) => {
    clearTimeout(t);
    reject(new Error(e?.message || "ws error"));
  });

  ws.on("close", () => {
    // finalPromise will handle timeout if no final arrives
  });
});

ws.on("open", async () => {
  try {
    await doConnect();
    const finalText = await finalPromise;
    process.stdout.write(finalText + "\n");
    ws.close();
  } catch (e) {
    console.error("ERR:", e?.message || String(e));
  if (e && e.stack) console.error(e.stack);
    ws.close();
    process.exitCode = 1;
  }
});

ws.on("message", (buf) => {
  // connect.challenge may arrive before open handler completes; handle by calling doConnect
  let obj;
  try { obj = JSON.parse(String(buf)); } catch { return; }
  if (obj.type === "event" && obj.event === "connect.challenge") {
    doConnect().catch(() => {});
  }
});
