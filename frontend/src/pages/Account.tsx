import { useState } from "react";
import { change, type User } from "../api";
import { Alert, Field, Form, useAction } from "../ui";
import { roleName } from "../labels";
import { Heading } from "../Heading";

export function Account({ user }: { user: User }) {
  const action = useAction(),
    [saved, setSaved] = useState(false),
    [formKey, setFormKey] = useState(0);
  return (
    <>
      <Heading
        eyebrow="ACCOUNT"
        title="我的帳號"
        description={`${user.username} · ${roleName(user.role)}`}
      />
      <section className="panel narrow">
        <h2>更改密碼</h2>
        <Form
          key={formKey}
          busy={action.busy}
          onSubmit={(d) =>
            action.run(async () => {
              if (d.get("password") !== d.get("confirm"))
                throw new Error("兩次新密碼不一致。");
              await change("password/", "POST", {
                old_password: String(d.get("old_password")),
                password: String(d.get("password")),
              });
              setSaved(true);
              setFormKey((k) => k + 1);
            })
          }
        >
          <Field label="目前密碼">
            <input
              type="password"
              name="old_password"
              autoComplete="current-password"
              required
            />
          </Field>
          <Field label="新密碼">
            <input
              type="password"
              name="password"
              autoComplete="new-password"
              minLength={8}
              maxLength={1024}
              required
            />
          </Field>
          <Field label="再次輸入新密碼">
            <input
              type="password"
              name="confirm"
              autoComplete="new-password"
              required
            />
          </Field>
          <Alert message={action.error} />
          <button className="primary">更新密碼</button>
          {saved && (
            <p className="success" role="status">
              密碼已更新。
            </p>
          )}
        </Form>
      </section>
    </>
  );
}
