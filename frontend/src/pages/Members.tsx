import { useState } from "react";
import { change, useData, type User, type Page } from "../api";
import { Alert, Field, Form, Modal, Pages, text, useAction } from "../ui";
import { roleName } from "../labels";
import { Heading } from "../Heading";

export function Members() {
  const [page, setPage] = useState(1),
    rows = useData<Page<User>>(`members/?page=${page}`),
    [editing, setEditing] = useState<User | "new" | null>(null);
  return (
    <>
      <Heading
        eyebrow="TEAM"
        title="團隊成員"
        description="擁有者管理成員與 Agent 授權；管理員維護商家資料。"
      >
        <button className="primary" onClick={() => setEditing("new")}>
          ＋ 新增成員
        </button>
      </Heading>
      <Alert message={rows.error?.message} />
      {rows.isPending && <p>載入中…</p>}
      <section className="panel table-wrap">
        <table>
          <thead>
            <tr>
              <th>成員</th>
              <th>角色</th>
              <th>狀態</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {rows.data?.results.map((u) => (
              <tr key={u.id}>
                <td>
                  <strong>{u.name || u.username}</strong>
                  <small>{u.username}</small>
                </td>
                <td>{roleName(u.role)}</td>
                <td>
                  <span className="badge">{u.is_active ? "啟用" : "停用"}</span>
                </td>
                <td>
                  <button onClick={() => setEditing(u)}>編輯</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {rows.data && (
          <Pages page={page} pages={rows.data.pages} set={setPage} />
        )}
      </section>
      {editing && (
        <MemberEditor user={editing} close={() => setEditing(null)} />
      )}
    </>
  );
}
function MemberEditor({
  user,
  close,
}: {
  user: User | "new";
  close: () => void;
}) {
  const current = user === "new" ? null : user,
    action = useAction();
  return (
    <Modal title={current ? "編輯成員" : "新增成員"} close={close}>
      <Form
        busy={action.busy}
        onSubmit={(d) =>
          action.run(async () => {
            const values = {
              name: text(d, "name"),
              role: text(d, "role"),
              ...(current
                ? { is_active: d.get("is_active") === "on" }
                : {
                    username: text(d, "username"),
                    password: String(d.get("password")),
                  }),
            };
            await change(
              `members/${current ? current.id + "/" : ""}`,
              current ? "PATCH" : "POST",
              values,
            );
            close();
          })
        }
      >
        {!current && (
          <>
            <Field label="登入帳號">
              <input
                name="username"
                maxLength={150}
                autoComplete="off"
                required
              />
            </Field>
            <Field label="初始密碼">
              <input
                name="password"
                type="password"
                minLength={8}
                maxLength={1024}
                autoComplete="new-password"
                required
              />
            </Field>
            <p className="muted">
              請私下交付帳密，成員可在「我的帳號」更改密碼。
            </p>
          </>
        )}
        <Field label="顯示名稱">
          <input name="name" defaultValue={current?.name} maxLength={150} />
        </Field>
        <Field label="角色">
          <select name="role" defaultValue={current?.role ?? "admin"}>
            <option value="admin">管理員</option>
            <option value="owner">擁有者</option>
          </select>
        </Field>
        {current && (
          <label className="check">
            <input
              name="is_active"
              type="checkbox"
              defaultChecked={current.is_active}
            />
            啟用帳號
          </label>
        )}
        <Alert message={action.error} />
        <button className="primary">儲存成員</button>
      </Form>
    </Modal>
  );
}
