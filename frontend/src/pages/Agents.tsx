import { useState } from "react";
import {
  change,
  useData,
  type AgentRole,
  type AgentKey,
  type McpInfo,
} from "../api";
import { Alert, Field, Form, Modal, text, useAction } from "../ui";
import { Heading } from "../Heading";
import { Icon } from "../icons";

// Agent on this computer: the standard mcpServers entry most Agents accept.
function stdioConfig(
  mcp: Extract<McpInfo, { transport: "stdio" }>,
  key: string,
) {
  const server = {
    command: mcp.command,
    args: mcp.args,
    env: { ...mcp.env, [mcp.key_env]: key },
  };
  return JSON.stringify({ mcpServers: { [mcp.name]: server } }, null, 2);
}

function Snippet({ value }: { value: string }) {
  return (
    <textarea
      className="snippet"
      readOnly
      rows={value.split("\n").length}
      value={value}
      onFocus={(e) => e.target.select()}
    />
  );
}

export function Agents() {
  const mcp = useData<McpInfo>("mcp/"),
    roles = useData<AgentRole[]>("agent-roles/"),
    keys = useData<AgentKey[]>("keys/"),
    action = useAction(),
    [creating, setCreating] = useState(false),
    [secret, setSecret] = useState("");
  return (
    <>
      <Heading
        title="Agent 連接"
        description="讓這間店在 Agenrena 上的客服 Agent 代表商家，為顧客提供服務。"
      >
        <button
          className="primary"
          disabled={!roles.data?.length}
          onClick={() => setCreating(true)}
        >
          ＋ 建立連接
        </button>
      </Heading>
      <Alert
        message={
          mcp.error?.message ||
          roles.error?.message ||
          keys.error?.message ||
          action.error
        }
      />
      <section className="panel connection">
        <span className="tile large soft" aria-hidden>
          <Icon name="agents" />
        </span>
        <div>
          <h2>顧客服務入口</h2>
          {mcp.data?.transport === "stdio" ? (
            <>
              <p>
                這間店的 Agent 在這台電腦上時，建立金鑰後把下面的設定交給
                Agent，加入它的 MCP 設定。要讓顧客在 Agenrena
                對話裡收到進度通知，請到「商家資料」連接 Agenrena。
              </p>
              <Snippet value={stdioConfig(mcp.data, "<你的金鑰>")} />
            </>
          ) : mcp.data ? (
            <>
              <p>
                把這個網址與金鑰加入這間店 Agent 的 MCP 設定。要讓顧客在
                Agenrena 對話裡收到進度通知，請到「商家資料」連接 Agenrena。
              </p>
              <label className="field">
                <span>MCP 網址</span>
                <input
                  readOnly
                  value={mcp.data.url}
                  onFocus={(e) => e.target.select()}
                />
              </label>
              <code>Authorization: Bearer &lt;你的金鑰&gt;</code>
            </>
          ) : null}
        </div>
      </section>
      <div className="section-head compact">
        <h2>Agent 權限組</h2>
        <span className="muted">目前提供的能力</span>
      </div>
      <div className="role-grid">
        {roles.data?.map((r) => (
          <section className="panel" key={r.code}>
            <span className="badge brand">{r.code}</span>
            <h3>{r.label}</h3>
            <ul className="permissions">
              {r.permissions.map((p) => (
                <li key={p.code}>
                  <span>{p.label}</span>
                  <small>
                    {p.scope === "customer" ? "僅當前顧客" : "商家公開資料"}
                  </small>
                </li>
              ))}
            </ul>
          </section>
        ))}
      </div>
      <div className="section-head compact">
        <h2>連接金鑰</h2>
      </div>
      <section className="panel">
        {keys.data?.length === 0 && (
          <p className="empty">尚未建立連接。金鑰建立後只顯示一次。</p>
        )}
        {keys.data?.map((k) => (
          <div className="list-row" key={k.id}>
            <div>
              <strong>{k.label}</strong>
              <small>
                {k.prefix}… ·{" "}
                {roles.data?.find((r) => r.code === k.role_id)?.label ??
                  k.role_id}
              </small>
            </div>
            {k.revoked_at ? (
              <span className="badge">已撤銷</span>
            ) : (
              <button
                className="danger"
                disabled={action.busy}
                onClick={() => {
                  if (
                    window.confirm(
                      `撤銷「${k.label}」？使用它的 Agent 將無法連接。`,
                    )
                  )
                    void action.run(() =>
                      change(`keys/${k.id}/revoke/`, "POST", {}),
                    );
                }}
              >
                撤銷
              </button>
            )}
          </div>
        ))}
      </section>
      {creating && (
        <Modal title="建立 Agent 連接" close={() => setCreating(false)}>
          <Form
            busy={action.busy}
            onSubmit={(d) =>
              action.run(async () => {
                const result = await change<{ secret: string }>(
                  "keys/",
                  "POST",
                  {
                    label: text(d, "label"),
                    role: text(d, "role"),
                  },
                );
                setSecret(result.secret);
                setCreating(false);
              })
            }
          >
            <Field label="連接名稱">
              <input
                name="label"
                maxLength={80}
                placeholder="例如：Agenrena 顧客服務"
                required
              />
            </Field>
            <Field label="權限組">
              <select name="role">
                {roles.data?.map((r) => (
                  <option value={r.code} key={r.code}>
                    {r.label}
                  </option>
                ))}
              </select>
            </Field>
            <Alert message={action.error} />
            <button className="primary">建立金鑰</button>
          </Form>
        </Modal>
      )}
      {secret && (
        <Modal title="保存你的 Agent 金鑰" close={() => setSecret("")}>
          {mcp.data?.transport === "stdio" ? (
            <>
              <p>
                金鑰只顯示這一次。把下面整段設定交給這間店的
                Agent（已經填好金鑰）。
              </p>
              <Snippet value={stdioConfig(mcp.data, secret)} />
            </>
          ) : (
            <>
              <p>金鑰只顯示這一次，請存入 Agent 的連線設定。</p>
              <Field label="新金鑰">
                <input
                  readOnly
                  value={secret}
                  onFocus={(e) => e.target.select()}
                />
              </Field>
            </>
          )}
          <button className="primary" onClick={() => setSecret("")}>
            我已保存
          </button>
        </Modal>
      )}
    </>
  );
}
