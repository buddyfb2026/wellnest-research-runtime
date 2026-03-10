#!/usr/bin/env node
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

const gatewayHttp = process.env.OC_GATEWAY_HTTP || "http://127.0.0.1:18791";
const wsUrl = process.env.OC_GATEWAY_WS || wsUrlFromHttp(gatewayHttp);
const token = process.env.OC_GATEWAY_TOKEN || readToken();
const origin = process.env.OC_ORIGIN || "http://127.0.0.1:18789";

const ws = new WebSocket(wsUrl, { headers: { Origin: origin } });
const pending = new Map();

function sendReq(id, method, params) {
  ws.send(JSON.stringify({type:"req", id, method, params}));
}

function req(method, params, timeoutMs=15000) {
  const id = uuid();
  sendReq(id, method, params);
  return new Promise((resolve, reject) => {
    pending.set(id, {resolve, reject});
    setTimeout(() => reject(new Error("timeout waiting for " + method)), timeoutMs);
  });
}

let didConnect = false;

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
    userAgent: "ri-ws-ping",
    locale: "en-US"
  }, 20000);

  const ident = await req("agent.identity.get", { sessionKey: (process.env.OC_SESSION_KEY || "main") }, 15000);
  console.log(JSON.stringify({ ok: true, identity: ident }, null, 2));
  ws.close();
}

ws.on("message", (buf) => {
  let obj;
  try { obj = JSON.parse(String(buf)); } catch { return; }

  if (obj.type === "event" && obj.event === "connect.challenge") {
    doConnect().catch(e => {
      console.error("ERR(connect):", e?.message || String(e));
      ws.close();
      process.exitCode = 1;
    });
    return;
  }

  if (obj.type === "res") {
    const h = pending.get(obj.id);
    if (!h) return;
    pending.delete(obj.id);
    obj.ok ? h.resolve(obj.payload) : h.reject(new Error(obj.error?.message || "request failed"));
  }
});

ws.on("open", () => {
  setTimeout(() => {
    doConnect().catch(e => {
      console.error("ERR(connect-no-challenge):", e?.message || String(e));
      ws.close();
      process.exitCode = 1;
    });
  }, 600);
});

ws.on("error", (e) => {
  console.error("ERR: ws error", e?.message || "");
  process.exit(1);
});
