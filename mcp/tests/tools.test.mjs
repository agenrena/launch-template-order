import test from "node:test";
import assert from "node:assert/strict";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import { createServer } from "../dist/server.js";
import { CoreApi, ApiError } from "../dist/api.js";
async function connect(api) {
  const server = createServer(api),
    client = new Client({ name: "test", version: "1" });
  const [a, b] = InMemoryTransport.createLinkedPair();
  await server.connect(a);
  await client.connect(b);
  return {
    client,
    close: async () => {
      await client.close();
      await server.close();
    },
  };
}
test("composed customer-facing core and ordering tools", async () => {
  const s = await connect({});
  try {
    const { tools } = await s.client.listTools();
    assert.deepEqual(
      tools.map((t) => t.name),
      [
        "get_business",
        "get_customer_profile",
        "update_customer_profile",
        "get_shop",
        "get_menu",
        "create_order_link",
        "list_orders",
        "cancel_order",
      ],
    );
    for (const t of tools.filter((t) => t.name.includes("customer")))
      assert.ok(t.inputSchema.required.includes("customer_ref"));
    for (const t of tools) assert.ok(!t.inputSchema.properties?.role);
  } finally {
    await s.close();
  }
});
test("reference is passed unchanged and name writes are explicit", async () => {
  let received;
  const s = await connect({
    updateProfile: async (args) => {
      received = args;
      return { profile: { id: "internal", display_name: args.display_name } };
    },
  });
  try {
    const args = {
      customer_ref: "bcr_0123456789abcdef0123456789abcdef",
      display_name: "Ada",
    };
    const r = await s.client.callTool({
      name: "update_customer_profile",
      arguments: args,
    });
    assert.deepEqual(received, args);
    assert.equal(r.isError, false);
  } finally {
    await s.close();
  }
});
test("missing or invented identity is refused before upstream call", async () => {
  let called = false;
  const s = await connect({
    profile: async () => {
      called = true;
    },
  });
  try {
    for (const args of [
      {},
      { customer_ref: "guest" },
      { customer_ref: "BCR_0123456789ABCDEF0123456789ABCDEF" },
    ]) {
      const r = await s.client.callTool({
        name: "get_customer_profile",
        arguments: args,
      });
      assert.equal(r.isError, true);
    }
    assert.equal(called, false);
  } finally {
    await s.close();
  }
});
test("backend permission errors remain errors", async () => {
  const body = { error: "permission_denied" };
  const s = await connect({
    business: async () => {
      throw new ApiError(403, body);
    },
  });
  try {
    const r = await s.client.callTool({ name: "get_business", arguments: {} });
    assert.equal(r.isError, true);
    assert.deepEqual(JSON.parse(r.content[0].text), body);
  } finally {
    await s.close();
  }
});
test("transport failures disclose no private details or claimed success", async () => {
  const s = await connect({
    updateProfile: async () => {
      throw new Error("secret-internal-error");
    },
  });
  try {
    const r = await s.client.callTool({
      name: "update_customer_profile",
      arguments: {
        customer_ref: "bcr_0123456789abcdef0123456789abcdef",
        display_name: "Ada",
      },
    });
    assert.equal(r.isError, true);
    assert.ok(!r.content[0].text.includes("secret-internal"));
    assert.equal(JSON.parse(r.content[0].text).error, "upstream_unavailable");
  } finally {
    await s.close();
  }
});
test("API wrapper keeps the prefix, each key and the scoped reference", async () => {
  const original = globalThis.fetch,
    calls = [];
  globalThis.fetch = async (url, init) => {
    calls.push({ url: String(url), init });
    return new Response("{}", { status: 200 });
  };
  try {
    await new CoreApi("http://test/api/agent-api", "abc_first").profile({
      customer_ref: "current_ref",
    });
    await new CoreApi("http://test/api/agent-api/", "abc_second").updateProfile(
      { customer_ref: "second", display_name: "B" },
    );
    assert.equal(
      calls[0].url,
      "http://test/api/agent-api/customer-profile/?customer_ref=current_ref",
    );
    assert.equal(calls[0].init.headers.Authorization, "Bearer abc_first");
    assert.equal(calls[1].init.headers.Authorization, "Bearer abc_second");
    assert.deepEqual(JSON.parse(calls[1].init.body), {
      customer_ref: "second",
      display_name: "B",
    });
  } finally {
    globalThis.fetch = original;
  }
});
