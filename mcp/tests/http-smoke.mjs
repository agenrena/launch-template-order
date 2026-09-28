import assert from "node:assert/strict";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";
const { SMOKE_MCP_URL, SMOKE_AGENT_KEY } = process.env;
const config = JSON.parse(process.env.SMOKE_ORDER);
const client = new Client({ name: "order-smoke", version: "1" });
await client.connect(
  new StreamableHTTPClientTransport(new URL(SMOKE_MCP_URL), {
    requestInit: { headers: { Authorization: `Bearer ${SMOKE_AGENT_KEY}` } },
  }),
);
async function call(name, args = {}, expectError = false) {
  const result = await client.callTool({ name, arguments: args });
  assert.equal(result.isError, expectError, JSON.stringify(result));
  return JSON.parse(result.content[0].text);
}
try {
  const { tools } = await client.listTools();
  assert.equal(tools.length, 8);
  assert.equal((await call("get_shop")).accepting_orders, true);
  const menu = await call("get_menu");
  assert.equal(menu.categories[0].items[0].id, config.item);
  const customer_ref = "bcr_5e0ce0000000000000000000000000a1";
  assert.equal(menu.categories[0].items[0].options[0].choose, "必選 1 個");
  const missing = await call(
    "create_order_link",
    { customer_ref, customer_name: "Smoke", items: [{ item: config.item }] },
    true,
  );
  assert.equal(missing.error, "option_required");
  const cart = {
    customer_ref,
    items: [{ item: config.item, quantity: 2, options: [config.option] }],
  };
  const unnamed = await call("create_order_link", cart, true);
  assert.equal(unnamed.error, "new_customer_name_required");
  const link = await call("create_order_link", {
    ...cart,
    customer_name: "Smoke",
  });
  assert.ok(link.confirmation_url.startsWith(`${config.base}/d/`));
  // Nothing is ordered until the customer confirms on the page.
  assert.deepEqual((await call("list_orders", { customer_ref })).orders, []);
  const token = link.confirmation_url.split("/d/")[1];
  const confirm = () =>
    fetch(`${config.base}/api/web/order-drafts/${token}/confirm/`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ phone: "0912" }),
    });
  const first = await confirm();
  const again = await confirm();
  assert.equal(first.status, 201);
  assert.equal(again.status, 200);
  const orders = (await call("list_orders", { customer_ref })).orders;
  assert.equal(orders.length, 1);
  assert.equal(orders[0].status_text, "等待店家確認");
  assert.equal(orders[0].total, "280");
  const other = await call(
    "cancel_order",
    {
      customer_ref: "bcr_5e0ce0000000000000000000000000b2",
      order_id: orders[0].id,
    },
    true,
  );
  assert.equal(other.error, "not_found");
  const cancelled = await call("cancel_order", {
    customer_ref,
    order_id: orders[0].id,
  });
  assert.equal(cancelled.status, "cancelled");
  console.log(
    "Streamable HTTP: menu, order link, customer confirm/retry, scoped list and cancel passed.",
  );
} finally {
  await client.close();
}
