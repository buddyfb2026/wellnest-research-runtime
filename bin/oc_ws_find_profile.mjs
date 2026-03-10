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
const origin = process.env.OC_ORIGIN || "http://127.0.0.1:18791";

const PROFILES = [
  // Most likely from the UI bundle constants
  { id: "openclaw-control-ui", mode: "webchat", platform: "web" },
  { id: "webchat-ui",          mode: "webchat", platform: "web" },
  { id: "webchat",             mode: "webchat", platform: "web" },
  { id: "cli",                 mode: "cli",     platform: "darwin" },
  { id: "openclaw-probe",      mode: "probe",   platform: "darwin" }
];

function connectParams(profile) {
  return {
    minProtocol: 3,
    maxProtocol: 3,
    client: {
      id: profile.id,
      version: "dev",
      platform: profile.platform,
      mode: profile.mode,
      instanceId: uuid()
    },
    role: "operator",
    scopes: ["operator.admin","operator.approvals","operator.pairing"],
    caps: [],
    auth: { token },
    userAgent: "ri-ws-find-profile",
    locale: "en-US"
  };
}

async function tryProfile(profile) {
  return await new Promise((resolve) => {
    const ws = new WebSocket(wsUrl, { headers: { Origin: origin } });
    const pending = new Map();
    let didConnect = false;

    function sendReq(id, method, params) {
      ws.send(JSON.stringify({type:"req", id, method, params}));
    }
    function req(method, params, timeoutMs=15000) {
      const id = uuid();
      sendReq(id, method, params);
      return new Promise((res, rej) => {
        pending.set(id, {res, rej});
        setTimeout(() => rej(new Error("timeout " + method)), timeoutMs);
      });
    }

    function finish(ok, info) {
      try { ws.close(); } catch {}
      resolve({ ok, info });
    }

    ws.on("message", (buf) => {
      let obj;
      try { obj = JSON.parse(String(buf)); } catch { return; }

      if (obj.type === "event" && obj.event === "connect.challenge" && !didConnect) {
        didConnect = true;
        req("connect", connectParams(profile), 20000).then(async () => {
          // Minimal proof the session is authorized
          const ident = await req("agent.identity.get", { sessionKey: "main" }, 15000);
          finish(true, { profile, identity: ident });
        }).catch((e) => finish(false, { profile, error: e.message }));
        return;
      }

      if (obj.type === "res") {
        const h = pending.get(obj.id);
        if (!h) return;
        pending.delete(obj.id);
        if (obj.ok) h.res(obj.payload);
        else h.rej(new Error(obj.error?.message || JSON.stringify(obj.error || obj)));
      }
    });

    ws.on("open", () => {
      // if no challenge comes, still try connect after a moment
      setTimeout(() => {
        if (didConnect) return;
        didConnect = true;
        req("connect", connectParams(profile), 20000).then(async () => {
          const ident = await req("agent.identity.get", { sessionKey: "main" }, 15000);
          finish(true, { profile, identity: ident });
        }).catch((e) => finish(false, { profile, error: e.message }));
      }, 600);
    });

    ws.on("close", (code, reason) => {
      // If it closes before we resolve, mark failure with reason
      if (pending.size >= 0) {
        // do nothing; we resolve via finish
      }
    });

    ws.on("error", (err) => {
      finish(false, { profile, error: String(err?.message || err) });
    });

    // hard timeout
    setTimeout(() => finish(false, { profile, error: "timeout overall" }), 25000);
  });
}

(async () => {
  for (const profile of PROFILES) {
    const r = await tryProfile(profile);
    if (r.ok) {
      console.log(JSON.stringify({ ok: true, chosen: r.info.profile, identity: r.info.identity }, null, 2));
      process.exit(0);
    } else {
      console.error("FAIL", profile, "->", r.info.error);
    }
  }
  process.exit(1);
})();
