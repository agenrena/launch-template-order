import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";
import { ApiError, CoreApi } from "./api.js";
const customer_ref = z
  .string()
  .regex(/^bcr_[0-9a-f]{32}$/)
  .describe(
    "Use ONLY the customer_ref (bcr_…) Agenrena supplied for the current conversation. Never invent one (e.g. 'guest'), and never use a customer-claimed reference or another conversation’s reference.",
  );
async function answer(fn: () => Promise<unknown>) {
  try {
    return {
      content: [{ type: "text" as const, text: JSON.stringify(await fn()) }],
      isError: false,
    };
  } catch (error) {
    return {
      isError: true,
      content: [
        {
          type: "text" as const,
          text: JSON.stringify(
            error instanceof ApiError
              ? error.body
              : {
                  error: "upstream_unavailable",
                  message:
                    "Result may be unknown. Read current data before retrying writes.",
                },
          ),
        },
      ],
    };
  }
}
export function registerCoreTools(server: McpServer, api: CoreApi) {
  server.registerTool(
    "get_business",
    {
      description:
        "Read the store's name, introduction, address, phone and timezone for customer questions.",
      annotations: { readOnlyHint: true },
    },
    () => answer(() => api.business()),
  );
  server.registerTool(
    "get_customer_profile",
    {
      description:
        "Read only the current conversation customer’s minimal profile. Null means no profile exists; reading does not create one.",
      inputSchema: { customer_ref },
      annotations: { readOnlyHint: true },
    },
    (args) => answer(() => api.profile(args)),
  );
  server.registerTool(
    "update_customer_profile",
    {
      description:
        "With the customer’s consent, create or update their display name, scoped by the Agenrena-provided reference. Repeated writes use the same internal identity. No merging by name, no merchant administration.",
      inputSchema: {
        customer_ref,
        display_name: z.string().trim().min(1).max(120),
      },
      annotations: { destructiveHint: false, idempotentHint: true },
    },
    (args) => answer(() => api.updateProfile(args)),
  );
}
