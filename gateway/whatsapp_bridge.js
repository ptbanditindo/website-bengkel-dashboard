/* Baileys WhatsApp gateway bridge — localhost HTTP, internal auth.
 *
 * Legacy bridge retained for reference. The app now runs Knightbot-MD/index.js.
 *
 * Serves 127.0.0.1:BAILEYS_PORT (default 9090) for the Python side
 * (whatsapp/baileys_client.py), and forwards inbound WhatsApp messages to
 * BAILEYS_INBOUND_URL (the FastAPI inbound webhook). The shared auth token is
 * read from data/integration_settings.json (whatsapp_internal_token).
 */

import http from "node:http"
import fs from "node:fs"
import path from "node:path"
import { fileURLToPath } from "node:url"

import makeWASocket, {
  useMultiFileAuthState,
  makeCacheableSignalKeyStore,
  DisconnectReason,
  fetchLatestBaileysVersion,
  Browsers,
} from "@whiskeysockets/baileys"
import { Boom } from "@hapi/boom"
import NodeCache from "@cacheable/node-cache"
import pino from "pino"
import qrcode from "qrcode"

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const PROJECT_ROOT = path.resolve(__dirname, "..")

const HOST = process.env.BAILEYS_HOST || "127.0.0.1"
const PORT = Number.parseInt(process.env.BAILEYS_PORT || "9090", 10)
const AUTH_DIR = process.env.BAILEYS_AUTH_DIR || path.join(PROJECT_ROOT, "data", "baileys_session")
const INBOUND_URL = process.env.BAILEYS_INBOUND_URL || "http://127.0.0.1:8000/api/integrations/whatsapp/inbound"
const SETTINGS_PATH = path.join(PROJECT_ROOT, "data", "integration_settings.json")

// ---------- config helpers ----------
function readInternalToken() {
  try {
    const data = JSON.parse(fs.readFileSync(SETTINGS_PATH, "utf8"))
    return (data && data.whatsapp_internal_token) || ""
  } catch {
    return ""
  }
}

// ---------- mutable state ----------
let sock = null
let authState = null
let currentStatus = "connecting"
let currentQrDataUrl = null
let currentQrExpiresAt = 0
let currentPairingCode = null
let currentError = ""
let pairingMode = false
let authedNumber = ""

// Number -> full JID mapping (e.g. "69904887738555" -> "69904887738555@lid").
// Needed because privacy-protected senders arrive as @lid JIDs whose suffix
// would be lost by jidToNumber(); replying must reuse the exact same JID.
const JID_MAP_PATH = path.join(PROJECT_ROOT, "data", "jid_map.json")

function loadJidMap() {
  try {
    return new Map(Object.entries(JSON.parse(fs.readFileSync(JID_MAP_PATH, "utf8"))))
  } catch {
    return new Map()
  }
}

function saveJidMap() {
  try {
    fs.writeFileSync(JID_MAP_PATH, JSON.stringify(Object.fromEntries(jidByNumber)))
  } catch {}
}

const jidByNumber = loadJidMap()

// IDs of messages this gateway itself sent via /send. Used to distinguish the
// AI's own replies from the owner's manual replies on the same WhatsApp number.
const sentMessageIds = new Set()

function jidToNumber(jid) {
  return String(jid || "").split("@")[0].split(":")[0]
}

function meId() {
  if (sock && sock.user && sock.user.id) return sock.user.id
  if (authState && authState.creds && authState.creds.me) return authState.creds.me.id
  return ""
}

function statusPayload() {
  const num = meId() ? jidToNumber(meId()) : authedNumber
  return {
    status: currentStatus,
    provider: "baileys",
    authedNumber: num || "",
    qr: currentQrDataUrl || null,
    qrExpiresAt: currentQrExpiresAt || 0,
    error: currentError || "",
  }
}

function extractText(m) {
  const msg = m && m.message
  if (!msg) return ""
  if (typeof msg.conversation === "string") return msg.conversation
  if (msg.extendedTextMessage && typeof msg.extendedTextMessage.text === "string") {
    return msg.extendedTextMessage.text
  }
  if (msg.imageMessage && typeof msg.imageMessage.caption === "string") return msg.imageMessage.caption
  if (msg.videoMessage && typeof msg.videoMessage.caption === "string") return msg.videoMessage.caption
  return ""
}

async function forwardIncoming(m) {
  try {
    const jid = m && m.key && m.key.remoteJid
    console.log("[gateway] upsert jid=", jid, "fromMe=", m && m.key && m.key.fromMe, "type=", Object.keys((m && m.message) || {}))
    if (!jid || m.key.fromMe) return
    if (jid.endsWith("@g.us") || jid === "status@broadcast" || jid.endsWith("@newsletter")) return
    const text = extractText(m)
    if (!text) return
    const number = jidToNumber(jid)
    jidByNumber.set(number, jid)
    saveJidMap()
    console.log("[gateway] forwarding to API from=", number, "jid=", jid, "text_len=", text.length)
    const payload = { from: number, message_id: m.key.id || "", text }
    const resp = await fetch(INBOUND_URL, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: "Bearer " + readInternalToken(),
      },
      body: JSON.stringify(payload),
    })
    if (!resp.ok) console.error("[gateway] inbound HTTP " + resp.status)
  } catch (err) {
    console.error("[gateway] inbound error:", err)
  }
}

async function forwardOwnerReply(m) {
  try {
    const jid = m && m.key && m.key.remoteJid
    if (!jid) return
    if (jid.endsWith("@g.us") || jid === "status@broadcast" || jid.endsWith("@newsletter")) return
    const id = (m.key && m.key.id) || ""
    if (sentMessageIds.has(id)) {
      sentMessageIds.delete(id)  // this was the AI's own reply
      return
    }
    const text = extractText(m)
    if (!text) return
    const number = jidToNumber(jid)
    console.log("[gateway] owner reply to=", number, "jid=", jid, "text_len=", text.length)
    const payload = { from: number, from_me: true, message_id: id, text }
    const resp = await fetch(INBOUND_URL, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: "Bearer " + readInternalToken(),
      },
      body: JSON.stringify(payload),
    })
    if (!resp.ok) console.error("[gateway] owner-reply HTTP " + resp.status)
  } catch (err) {
    console.error("[gateway] owner-reply error:", err)
  }
}

function scheduleReconnect() {
  setTimeout(() => {
    start().catch((err) => {
      currentStatus = "error"
      currentError = String((err && err.message) || err)
      console.error("[gateway] reconnect failed:", err)
    })
  }, 3000)
}

async function start() {
  const { state, saveCreds } = await useMultiFileAuthState(AUTH_DIR)
  authState = state
  const msgRetryCounterCache = new NodeCache()
  const logger = pino({ level: process.env.BAILEYS_LOG_LEVEL || "silent" })

  let version
  try {
    version = (await fetchLatestBaileysVersion()).version
  } catch (err) {
    console.warn("[gateway] fetchLatestBaileysVersion failed:", (err && err.message) || err)
  }

  currentStatus = "connecting"
  currentError = ""

  sock = makeWASocket({
    logger,
    browser: Browsers.macOS("Chrome"),
    auth: {
      creds: state.creds,
      keys: makeCacheableSignalKeyStore(state.keys, logger),
    },
    markOnlineOnConnect: false,
    syncFullHistory: false,
    msgRetryCounterCache,
    defaultQueryTimeoutMs: 60000,
    connectTimeoutMs: 60000,
    keepAliveIntervalMs: 10000,
    ...(version ? { version } : {}),
  })

  sock.ev.on("creds.update", saveCreds)

  sock.ev.on("connection.update", (update) => {
    const { connection, lastDisconnect, qr } = update

    if (qr && !pairingMode) {
      currentQrDataUrl = null
      currentQrExpiresAt = Date.now() + 20000
      currentStatus = "awaiting_scan"
      qrcode.toDataURL(qr, { width: 300 }).then((u) => { currentQrDataUrl = u }).catch(() => {})
    }

    if (connection === "open") {
      currentStatus = "connected"
      currentQrDataUrl = null
      currentQrExpiresAt = 0
      currentPairingCode = null
      pairingMode = false
      authedNumber = jidToNumber(meId())
      console.log("[gateway] connected as", authedNumber || "(unknown)")
    } else if (connection === "close") {
      const err = lastDisconnect && lastDisconnect.error
      const statusCode = err instanceof Boom ? err.output.statusCode : err && err.output ? err.output.statusCode : undefined
      if (statusCode === DisconnectReason.loggedOut) {
        currentStatus = "logged_out"
        currentQrDataUrl = null
        currentPairingCode = null
        pairingMode = false
        currentError = "Sesi telah logout."
        console.log("[gateway] logged out")
      } else {
        currentStatus = "reconnecting"
        currentError = "Koneksi terputus" + (statusCode ? " (kode " + statusCode + ")" : "") + ". Mencoba ulang…"
        console.log("[gateway] closed, reconnecting:", statusCode || err)
        scheduleReconnect()
      }
    }
  })

  sock.ev.on("messages.upsert", ({ type, messages }) => {
    console.log("[gateway] messages.upsert type=", type, "count=", (messages || []).length)
    if (type !== "notify") return
    for (const m of messages) {
      if (m.key && m.key.fromMe) forwardOwnerReply(m)
      else forwardIncoming(m)
    }
  })
}

// ---------- HTTP ----------
function sendJson(res, code, obj) {
  res.writeHead(code, { "Content-Type": "application/json; charset=utf-8" })
  res.end(JSON.stringify(obj))
}

function authorized(req) {
  const token = readInternalToken()
  if (!token) return false
  return (req.headers["authorization"] || "") === "Bearer " + token
}

function readBody(req) {
  return new Promise((resolve) => {
    let data = ""
    req.on("data", (chunk) => { data += chunk })
    req.on("end", () => {
      try { resolve(data ? JSON.parse(data) : {}) } catch { resolve({}) }
    })
    req.on("error", () => resolve({}))
  })
}

const server = http.createServer(async (req, res) => {
  if (!authorized(req)) return sendJson(res, 401, { error: "unauthorized" })

  const url = new URL(req.url, "http://" + HOST)
  const route = req.method + " " + url.pathname

  try {
    if (route === "GET /status") {
      return sendJson(res, 200, statusPayload())
    }

    if (route === "POST /start-qr") {
      pairingMode = false
      currentPairingCode = null
      currentError = ""
      if (currentStatus !== "connected") {
        currentStatus = "awaiting_scan"
      }
      return sendJson(res, 200, statusPayload())
    }

    if (route === "POST /request-pairing") {
      const body = await readBody(req)
      const phone = String(body.phone || "").replace(/\D/g, "")
      if (!phone) return sendJson(res, 400, { error: "phone required" })
      if (!sock) return sendJson(res, 503, { status: "bridge_unavailable", error: "socket belum siap" })
      if (authState && authState.creds && authState.creds.registered) {
        return sendJson(res, 200, statusPayload())
      }
      try {
        pairingMode = true
        currentQrDataUrl = null
        const code = await sock.requestPairingCode(phone)
        currentPairingCode = code
        currentStatus = "awaiting_pairing"
        return sendJson(res, 200, { status: "awaiting_pairing", pairingCode: code })
      } catch (err) {
        currentStatus = "error"
        currentError = String((err && err.message) || err)
        return sendJson(res, 400, { status: "error", error: currentError })
      }
    }

    if (route === "POST /logout") {
      pairingMode = false
      currentPairingCode = null
      currentQrDataUrl = null
      currentError = ""
      if (sock) {
        try { await sock.logout() } catch {}
      }
      currentStatus = "logged_out"
      return sendJson(res, 200, statusPayload())
    }

    if (route === "POST /send") {
      const body = await readBody(req)
      const to = String(body.to || "").trim()
      const text = String(body.text || "")
      if (!to || !text) return sendJson(res, 400, { sent: false, error: "to/text required" })
      if (!sock || currentStatus !== "connected") {
        return sendJson(res, 503, { sent: false, error: "not connected" })
      }
      const jid = to.includes("@") ? to : (jidByNumber.get(to) || (to + "@s.whatsapp.net"))
      console.log("[gateway] send to=", to, "resolvedJid=", jid)
      try {
        const sentMsg = await sock.sendMessage(jid, { text })
        if (sentMsg && sentMsg.key && sentMsg.key.id) {
          sentMessageIds.add(sentMsg.key.id)
          while (sentMessageIds.size > 500) sentMessageIds.delete(sentMessageIds.values().next().value)
        }
        return sendJson(res, 200, { sent: true })
      } catch (err) {
        return sendJson(res, 200, { sent: false, error: String((err && err.message) || err) })
      }
    }

    return sendJson(res, 404, { error: "not found" })
  } catch (err) {
    return sendJson(res, 500, { error: String((err && err.message) || err) })
  }
})

server.listen(PORT, HOST, () => {
  console.log("[gateway] listening on http://" + HOST + ":" + PORT)
  console.log("[gateway] auth dir:", AUTH_DIR)
  start().catch((err) => {
    currentStatus = "error"
    currentError = String((err && err.message) || err)
    console.error("[gateway] start failed:", err)
  })
})


