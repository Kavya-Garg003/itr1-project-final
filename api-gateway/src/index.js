/**
 * API Gateway — Node.js / Express
 * =================================
 * Routes all frontend traffic to Python microservices.
 * Handles: auth (JWT), rate limiting, file proxying, WebSocket progress.
 *
 * Endpoints:
 *   POST /api/upload/:type        → doc-parser
 *   POST /api/pipeline/run        → agent-orchestrator
 *   GET  /api/pipeline/:sessionId → agent-orchestrator
 *   POST /api/pipeline/update     → agent-orchestrator
 *   POST /api/chat                → agent-orchestrator → rag-service
 *   GET  /api/pipeline/export/:id → agent-orchestrator
 */

const express      = require("express");
const cors         = require("cors");
const multer       = require("multer");
const httpProxy    = require("http-proxy");
const rateLimit    = require("express-rate-limit");
const jwt          = require("jsonwebtoken");
const FormData     = require("form-data");
const fetch        = require("node-fetch");

const app  = express();
const PORT = process.env.PORT || 3001;

// ── Service URLs ──────────────────────────────────────────────────────────────

const SERVICES = {
  docParser:   process.env.DOC_PARSER_URL   || "http://doc-parser:8002",
  ragService:  process.env.RAG_SERVICE_URL  || "http://rag-service:8001",
  agentOrch:   process.env.AGENT_ORCH_URL   || "http://agent-orchestrator:8000",
};

// ── Middleware ────────────────────────────────────────────────────────────────

app.use(cors({ origin: process.env.FRONTEND_URL || "http://localhost:3000" }));
app.use(express.json({ limit: "5mb" }));

// Rate limiting
const apiLimiter = rateLimit({ windowMs: 15 * 60 * 1000, max: 100 });
const uploadLimiter = rateLimit({ windowMs: 15 * 60 * 1000, max: 20 });
app.use("/api/", apiLimiter);
app.use("/api/upload", uploadLimiter);

// File upload (multer — in-memory buffer, forwarded to doc-parser)
const upload = multer({
  storage: multer.memoryStorage(),
  limits: { fileSize: 20 * 1024 * 1024 }, // 20MB
  fileFilter: (req, file, cb) => {
    const allowed = ["application/pdf", "image/jpeg", "image/png"];
    cb(null, allowed.includes(file.mimetype));
  },
});

// ── Auth middleware (optional — skip for demo) ────────────────────────────────

function authMiddleware(req, res, next) {
  if (process.env.SKIP_AUTH === "true") return next();
  const token = req.headers.authorization?.replace("Bearer ", "");
  if (!token) return res.status(401).json({ error: "Unauthorized" });
  try {
    req.user = jwt.verify(token, process.env.JWT_SECRET || "dev-secret");
    next();
  } catch {
    res.status(401).json({ error: "Invalid token" });
  }
}

// ── Helper: forward JSON to a service ────────────────────────────────────────

async function forwardJson(serviceUrl, path, body) {
  const resp = await fetch(`${serviceUrl}${path}`, {
    method:  "POST",
    headers: { "Content-Type": "application/json" },
    body:    JSON.stringify(body),
    timeout: 60000,
  });
  if (!resp.ok) {
    const err = await resp.text();
    throw new Error(`Service error (${resp.status}): ${err}`);
  }
  return resp.json();
}

async function forwardGet(serviceUrl, path) {
  const resp = await fetch(`${serviceUrl}${path}`, { timeout: 30000 });
  if (!resp.ok) {
    const err = await resp.text();
    throw new Error(`Service error (${resp.status}): ${err}`);
  }
  return resp.json();
}

// ── Document upload & parse ───────────────────────────────────────────────────

app.post(
  "/api/upload/:docType",
  authMiddleware,
  upload.single("file"),
  async (req, res) => {
    try {
      const { docType }  = req.params;
      const { session_id, hint } = req.body;

      if (!req.file) return res.status(400).json({ error: "No file provided" });

      // Forward multipart/form-data to doc-parser
      const form = new FormData();
      form.append("file", req.file.buffer, {
        filename:    req.file.originalname,
        contentType: req.file.mimetype,
      });
      if (session_id) form.append("session_id", session_id);
      if (hint)       form.append("hint", hint);

      const endpoint = docType === "auto"
        ? "/parse/auto"
        : docType === "form16"
          ? "/parse/form16"
          : "/parse/bank-statement";

      const resp = await fetch(`${SERVICES.docParser}${endpoint}`, {
        method: "POST",
        body:   form,
        headers: form.getHeaders(),
        timeout: 45000,
      });

      if (!resp.ok) {
        const err = await resp.text();
        return res.status(resp.status).json({ error: err });
      }

      const data = await resp.json();
      res.json(data);
    } catch (err) {
      console.error("Upload error:", err);
      res.status(500).json({ error: err.message });
    }
  }
);

// ── Pipeline: run ─────────────────────────────────────────────────────────────

app.post("/api/pipeline/run", authMiddleware, async (req, res) => {
  try {
    const result = await forwardJson(SERVICES.agentOrch, "/pipeline/run", req.body);
    res.json(result);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// ── Pipeline: get session ─────────────────────────────────────────────────────

app.get("/api/pipeline/:sessionId", authMiddleware, async (req, res) => {
  try {
    const data = await forwardGet(SERVICES.agentOrch, `/pipeline/session/${req.params.sessionId}`);
    res.json(data);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// ── Pipeline: update field ────────────────────────────────────────────────────

app.post("/api/pipeline/update-field", authMiddleware, async (req, res) => {
  try {
    const result = await forwardJson(SERVICES.agentOrch, "/pipeline/update-field", req.body);
    res.json(result);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// ── Pipeline: export ──────────────────────────────────────────────────────────

app.get("/api/pipeline/export/:sessionId", authMiddleware, async (req, res) => {
  try {
    const data = await forwardGet(SERVICES.agentOrch, `/pipeline/export/${req.params.sessionId}`);
    res.json(data);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// ── Chat / Q&A ────────────────────────────────────────────────────────────────

app.post("/api/chat", authMiddleware, async (req, res) => {
  try {
    const result = await forwardJson(SERVICES.agentOrch, "/chat/query", req.body);
    res.json(result);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// ── Health (aggregates all services) ─────────────────────────────────────────

app.get("/api/health", async (req, res) => {
  const checks = await Promise.allSettled(
    Object.entries(SERVICES).map(async ([name, url]) => {
      const r = await fetch(`${url}/health`, { timeout: 3000 });
      return { name, status: r.ok ? "ok" : "degraded" };
    })
  );

  const statuses = Object.fromEntries(
    checks.map(c => c.status === "fulfilled"
      ? [c.value.name, c.value.status]
      : [String(c.reason), "down"]
    )
  );

  const allOk = Object.values(statuses).every(s => s === "ok");
  res.status(allOk ? 200 : 207).json({ gateway: "ok", services: statuses });
});

// ── Start ─────────────────────────────────────────────────────────────────────

app.listen(PORT, () => {
  console.log(`API Gateway running on port ${PORT}`);
  console.log("Services:", SERVICES);
});

module.exports = app;
