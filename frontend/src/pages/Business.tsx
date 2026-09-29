import { useState } from "react";
import { change, type Business } from "../api";
import { Alert, Field, Form, useAction } from "../ui";
import { Heading } from "../Heading";
import { AgenrenaPanel } from "./Agenrena";

export function BusinessPage({
  business,
  owner,
}: {
  business: Business;
  owner: boolean;
}) {
  const action = useAction(),
    [saved, setSaved] = useState(false);
  return (
    <>
      <Heading
        title="商家資料"
        description="這間店的基本資料，會提供給服務顧客的 Agent。一間店就是一個商家，也是 Agenrena 上的一個商家身分。"
      />
      <section className="panel narrow">
        <Form
          busy={action.busy}
          onSubmit={(d) =>
            action.run(async () => {
              await change("business/", "PATCH", Object.fromEntries(d));
              setSaved(true);
            })
          }
        >
          <Field label="商家名稱">
            <input
              name="name"
              defaultValue={business.name}
              maxLength={120}
              required
              onChange={() => setSaved(false)}
            />
          </Field>
          <Field label="商家介紹">
            <textarea
              name="about"
              defaultValue={business.about}
              rows={5}
              maxLength={2000}
              placeholder="簡單介紹你的商家與服務。"
              onChange={() => setSaved(false)}
            />
          </Field>
          <Field label="地址">
            <input
              name="address"
              defaultValue={business.address}
              maxLength={300}
              onChange={() => setSaved(false)}
            />
          </Field>
          <Field label="電話">
            <input
              name="phone"
              type="tel"
              defaultValue={business.phone}
              maxLength={40}
              onChange={() => setSaved(false)}
            />
          </Field>
          <Field label="時區">
            <input
              name="timezone"
              defaultValue={business.timezone}
              required
              onChange={() => setSaved(false)}
            />
          </Field>
          <p className="muted">
            例如 Asia/Taipei。更改時區不會移動既有紀錄的實際時間。
          </p>
          <Alert message={action.error} />
          <div className="actions">
            <button className="primary">儲存變更</button>
            {saved && (
              <span className="success" role="status">
                已儲存
              </span>
            )}
          </div>
        </Form>
      </section>
      <AgenrenaPanel owner={owner} storeName={business.name} />
    </>
  );
}
