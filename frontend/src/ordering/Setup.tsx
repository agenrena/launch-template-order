/** How the store takes orders: modes, hours, tables and their QR codes. */
import { useEffect, useState } from "react";
import QRCode from "qrcode";
import { change, useData } from "../api";
import { Alert, Field, Form, text, useAction } from "../ui";
import { Heading } from "../Heading";
import type { HoursStatus, OrderingSettings, TableRow } from "./types";

export function Setup() {
  return (
    <>
      <Heading
        title="桌位與營業"
        description="接單方式、營業時間與桌上的 QR code。QR 點餐與 Agent 都依照這裡判斷是否接單。"
      />
      <div className="setup-stack">
        <SettingsForm />
        <WeeklyHours />
        <Tables />
      </div>
    </>
  );
}

function SettingsForm() {
  const settings = useData<OrderingSettings>("ordering-settings/");
  const action = useAction();
  const [saved, setSaved] = useState(false);
  if (!settings.data) return <Alert message={settings.error?.message} />;
  const s = settings.data;
  return (
    <section className="panel narrow">
      <h2>接單設定</h2>
      <Form
        busy={action.busy}
        onSubmit={(d) =>
          action.run(async () => {
            await change("ordering-settings/", "PATCH", {
              accepts_takeout: d.get("accepts_takeout") === "on",
              accepts_dine_in: d.get("accepts_dine_in") === "on",
              currency: text(d, "currency"),
              last_order_minutes_before_close: Number(d.get("last_order") || 0),
              agenrena_short_id: text(d, "agenrena_short_id"),
            });
            setSaved(true);
          })
        }
      >
        <label className="check">
          <input
            name="accepts_takeout"
            type="checkbox"
            defaultChecked={s.accepts_takeout}
          />
          接受外帶（含 Agent 確認連結）
        </label>
        <label className="check">
          <input
            name="accepts_dine_in"
            type="checkbox"
            defaultChecked={s.accepts_dine_in}
          />
          接受內用掃碼點餐
        </label>
        <Field label="幣別">
          <input
            name="currency"
            defaultValue={s.currency}
            maxLength={3}
            required
          />
        </Field>
        <Field label="打烊前幾分鐘停止接單（0–240）">
          <input
            name="last_order"
            type="number"
            min={0}
            max={240}
            defaultValue={s.last_order_minutes_before_close}
          />
        </Field>
        <Field label="Agenrena 商家代碼（分享連結 /s/i/ 後面那段）">
          <input
            name="agenrena_short_id"
            defaultValue={s.agenrena_short_id}
            maxLength={32}
          />
        </Field>
        <p className="muted">
          填了代碼，顧客點餐頁會出現「到 Agenrena 問這間店的 Agent」的連結。
        </p>
        <Alert message={action.error} />
        <div className="actions">
          <button className="primary">儲存設定</button>
          {saved && <span className="success">已儲存</span>}
        </div>
      </Form>
    </section>
  );
}

const format = (day: HoursStatus["weekly_hours"][number]) =>
  day.intervals.map((i) => `${i.opens_at}-${i.closes_at}`).join(", ");

function WeeklyHours() {
  const hours = useData<HoursStatus>("hours/");
  const action = useAction();
  const [draft, setDraft] = useState<string[] | null>(null);
  useEffect(() => {
    if (hours.data && draft === null)
      setDraft(hours.data.weekly_hours.map(format));
  }, [hours.data, draft]);
  if (!hours.data || !draft) return <Alert message={hours.error?.message} />;
  return (
    <section className="panel narrow">
      <h2>每週營業時間</h2>
      <p className="muted">
        格式 11:00-14:00, 17:00-21:00；留空表示公休。不能跨過午夜。
        {hours.data.accepting_orders
          ? " 目前接單中。"
          : ` 目前：${hours.data.closed_reason}`}
      </p>
      {hours.data.weekly_hours.map((day, index) => (
        <Field key={day.weekday} label={day.label}>
          <input
            value={draft[index]}
            placeholder="公休"
            onChange={(e) =>
              setDraft(draft.map((v, i) => (i === index ? e.target.value : v)))
            }
          />
        </Field>
      ))}
      <Alert message={action.error} />
      <button
        className="primary"
        disabled={action.busy}
        onClick={() =>
          void action.run(async () => {
            const weekly = draft.map((value, weekday) => ({
              weekday,
              intervals: value
                .split(/[,，、]/)
                .map((part) => part.trim())
                .filter(Boolean)
                .map((part) => {
                  const [opens_at, closes_at] = part.split(/\s*[-–~～]\s*/);
                  return { opens_at, closes_at };
                }),
            }));
            await change("hours/", "PUT", { weekly });
            setDraft(null);
          })
        }
      >
        儲存營業時間
      </button>
    </section>
  );
}

function Tables() {
  const tables = useData<TableRow[]>("tables/");
  const settings = useData<OrderingSettings>("ordering-settings/");
  const action = useAction();
  const published = settings.data?.public_url;
  // Before publishing, the links still open the pages on this computer to try.
  const base = published || window.location.origin;
  return (
    <section className="panel">
      <div className="section-head compact">
        <h2>桌位與 QR code</h2>
      </div>
      {published ? (
        <p className="muted">
          桌上的 QR code 開啟內用點餐，同桌的人共用一張帳單。櫃檯的外帶 QR code
          指向首頁 {published}/。
        </p>
      ) : (
        <p className="notice">
          顧客的手機還連不到這台電腦，所以先不產生 QR code。要讓顧客掃碼點餐，請
          Agent 依照 docs/publish.md
          開放「顧客點餐入口」。在那之前，可以用下面的連結在這台電腦上試用點餐頁。
        </p>
      )}
      <Form
        busy={action.busy}
        onSubmit={(d) =>
          action.run(() => change("tables/", "POST", { code: text(d, "code") }))
        }
      >
        <div className="actions">
          <Field label="新增桌號">
            <input name="code" maxLength={20} required placeholder="A1" />
          </Field>
          <button className="primary">新增</button>
        </div>
      </Form>
      <Alert message={tables.error?.message || action.error} />
      <div className="table-grid">
        <TableCode label="外帶" url={`${base}/`} qr={!!published} />
        {tables.data?.map((t) => (
          <div key={t.id}>
            <TableCode
              label={`桌 ${t.code}`}
              url={`${base}/?table=${encodeURIComponent(t.code)}`}
              qr={!!published}
              muted={!t.is_active}
            />
            <label className="check">
              <input
                type="checkbox"
                checked={t.is_active}
                disabled={action.busy}
                onChange={(e) =>
                  void action.run(() =>
                    change(`tables/${t.id}/`, "PATCH", {
                      is_active: e.target.checked,
                    }),
                  )
                }
              />
              開放點餐
            </label>
          </div>
        ))}
      </div>
    </section>
  );
}

function TableCode({
  label,
  url,
  qr,
  muted = false,
}: {
  label: string;
  url: string;
  qr: boolean;
  muted?: boolean;
}) {
  const [src, setSrc] = useState("");
  useEffect(() => {
    if (qr) void QRCode.toDataURL(url, { margin: 1, width: 180 }).then(setSrc);
    else setSrc("");
  }, [url, qr]);
  return (
    <figure className={"table-code " + (muted ? "muted" : "")}>
      {src && <img src={src} alt={`${label} 的點餐 QR code`} />}
      <figcaption>
        <strong>{label}</strong>
        <a href={url} target="_blank" rel="noreferrer">
          開啟點餐頁
        </a>
      </figcaption>
    </figure>
  );
}
