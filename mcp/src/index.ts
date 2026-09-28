#!/usr/bin/env node
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";
import { createMcpExpressApp } from "@modelcontextprotocol/sdk/server/express.js";
import { OrderApi, ApiError } from "./api.js";
import { createServer } from "./server.js";
// Compatibility with the Runtime provider’s current environment name.
const base =
  process.env.ORDER_API_URL ??
  process.env.CORE_API_URL ??
  process.env.BOOKING_API_URL;
if (!base) throw new Error("Set ORDER_API_URL, including /api/agent-api/.");
if (process.argv.includes("--stdio")) {
  const key = process.env.ORDER_AGENT_KEY ?? process.env.CORE_AGENT_KEY;
  if (!key) throw new Error("Set ORDER_AGENT_KEY for stdio.");
  await createServer(new OrderApi(base, key)).connect(
    new StdioServerTransport(),
  );
} else {
  const host = process.env.HOST ?? "127.0.0.1";
  const app = createMcpExpressApp({
    host,
    allowedHosts: (process.env.ALLOWED_HOSTS ?? "localhost,127.0.0.1")
      .split(",")
      .map((s) => s.trim()),
  });
  app.get("/health/", (_req, res) => {
    res.json({ status: "ok" });
  });
  app.post("/mcp", async (req, res) => {
    const parts = (req.headers.authorization ?? "").split(" ");
    if (
      parts.length !== 2 ||
      parts[0].toLowerCase() !== "bearer" ||
      !parts[1].startsWith("abc_")
    ) {
      res.status(401).json({ error: "agent_key_required" });
      return;
    }
    const api = new OrderApi(base, parts[1]);
    try {
      await api.session();
    } catch (error) {
      // Validate even tools/list, including revoked keys.
      res
        .status(error instanceof ApiError && error.status === 401 ? 401 : 503)
        .json({ error: "agent_connection_failed" });
      return;
    }
    const server = createServer(api);
    const transport = new StreamableHTTPServerTransport({
      sessionIdGenerator: undefined,
    });
    res.on("close", () => {
      void transport.close();
      void server.close();
    });
    await server.connect(transport);
    await transport.handleRequest(req, res, req.body);
  });
  const listener = app.listen(Number(process.env.PORT ?? 8765), host, () =>
    console.error("Order MCP ready"),
  );
  process.on("SIGTERM", () => listener.close());
}
