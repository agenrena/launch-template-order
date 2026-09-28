import test from "node:test";
import assert from "node:assert/strict";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import { createServer } from "../dist/server.js";
import { OrderApi, ApiError } from "../dist/api.js";
const ref = "bcr_0123456789abcdef0123456789abcdef";
const id = "f38fe48e-0e01-4c5b-8918-21c7f3af9bac";
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
test("order link passes the cart and reference unchanged", async () => {
  let args;
  const s = await connect({
    createOrderLink: async (a) => {
      args = a;
      return { status: "pending_confirmation" };
    },
  });
  try {
    const input = {
      customer_ref: ref,
      items: [{ item: id, quantity: 2, options: [id], note: "不要香菜" }],
      customer_name: "Ada",
      note: "六點到",
    };
    const r = await s.client.callTool({
      name: "create_order_link",
      arguments: input,
    });
    assert.equal(r.isError, false);
    assert.deepEqual(args, input);
  } finally {
    await s.close();
  }
});
test("prices, invented references and names instead of ids are refused locally", async () => {
  let called = false;
  const s = await connect({
    createOrderLink: async () => {
      called = true;
    },
  });
  try {
    for (const args of [
      { customer_ref: ref, items: [{ item: id, unit_price: 1 }] },
      { customer_ref: "guest", items: [{ item: id }] },
      { customer_ref: ref, items: [{ item: "牛肉堡" }] },
      { customer_ref: ref, items: [] },
      { customer_ref: ref, items: [{ item: id, options: ["半糖"] }] },
    ]) {
      const r = await s.client.callTool({
        name: "create_order_link",
        arguments: args,
      });
      assert.equal(r.isError, true, JSON.stringify(args));
    }
    assert.equal(called, false);
  } finally {
    await s.close();
  }
});
test("shop refusals stay structured for the Agent to relay", async () => {
  const body = {
    error: "already_confirmed",
    message: "店家已接單，無法直接取消。",
    next_steps: "請聯絡店家。",
  };
  const s = await connect({
    cancel: async () => {
      throw new ApiError(409, body);
    },
  });
  try {
    const r = await s.client.callTool({
      name: "cancel_order",
      arguments: { customer_ref: ref, order_id: id },
    });
    assert.equal(r.isError, true);
    assert.deepEqual(JSON.parse(r.content[0].text), body);
  } finally {
    await s.close();
  }
});
test("HTTP wrapper scopes reads and cancels by the conversation reference", async () => {
  const original = globalThis.fetch,
    calls = [];
  globalThis.fetch = async (url, init) => {
    calls.push({ url: String(url), init });
    return new Response("{}", { status: 200 });
  };
  try {
    const api = new OrderApi("http://order.test/api/agent-api", "abc_key");
    await api.orders({ customer_ref: ref });
    await api.cancel(id, { customer_ref: ref });
    assert.equal(
      calls[0].url,
      `http://order.test/api/agent-api/orders/?customer_ref=${ref}`,
    );
    assert.equal(
      calls[1].url,
      `http://order.test/api/agent-api/orders/${id}/cancel/`,
    );
    assert.deepEqual(JSON.parse(calls[1].init.body), { customer_ref: ref });
    assert.equal(calls[1].init.headers.Authorization, "Bearer abc_key");
  } finally {
    globalThis.fetch = original;
  }
});
