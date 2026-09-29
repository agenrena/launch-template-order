/** The service screen: what came in, and what staff do about it. */
import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, change, useData } from "../api";
import { Alert, Field, Modal, useAction } from "../ui";
import { Heading } from "../Heading";
import {
  money,
  type AdminItem,
  type ConsoleRound,
  type ConsoleTab,
  type HoursStatus,
  type OptionGroupRow,
  type OrderingSettings,
} from "./types";

type Stage = "waiting" | "making" | "settle" | "ended";
const STAGES: { key: Stage; title: string; empty: string }[] = [
  { key: "waiting", title: "待確認", empty: "沒有待確認的訂單。" },
  { key: "making", title: "製作中", empty: "沒有製作中的餐點。" },
  { key: "settle", title: "待結帳", empty: "沒有待結帳的帳單。" },
  { key: "ended", title: "已結束", empty: "今天還沒有結束的訂單。" },
];

function stage(tab: ConsoleTab): Stage {
  if (tab.rounds.some((r) => r.status === "pending")) return "waiting";
  if (tab.rounds.some((r) => r.status === "confirmed")) return "making";
  if (
    !tab.closed_at &&
    (Number(tab.total) > 0 || tab.service_mode === "dine_in")
  )
    return "settle";
  return "ended";
}

/** What the customer asked for, pending included; refused and withdrawn do not count. */
function ordered(tab: ConsoleTab) {
  return tab.rounds
    .filter((r) => r.status !== "rejected" && r.status !== "cancelled")
    .reduce((sum, r) => sum + Number(r.total), 0);
}

function elapsed(since: string, now: number) {
  const minutes = Math.max(0, Math.floor((now - Date.parse(since)) / 60_000));
  return minutes < 60
    ? `${minutes} 分鐘`
    : `${Math.floor(minutes / 60)} 小時 ${minutes % 60} 分鐘`;
}

export function Orders({ timezone }: { timezone: string }) {
  const tabs = useQuery({
    queryKey: ["tabs/"],
    queryFn: () => api<ConsoleTab[]>("tabs/"),
    refetchInterval: 10_000,
  });
  const settings = useData<OrderingSettings>("ordering-settings/");
  const status = useData<HoursStatus>("ordering-status/");
  const [now, setNow] = useState(Date.now());
  const [amending, setAmending] = useState<ConsoleRound | null>(null);
  const [showEnded, setShowEnded] = useState(false);
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 30_000);
    return () => window.clearInterval(timer);
  }, []);
  const currency = settings.data?.currency ?? "";
  return (
    <>
      <Heading
        title="訂單"
        description="QR 點餐、Agent 確認連結與店員代改的訂單都在這裡。有問題先聯絡顧客，談妥後再修改。"
      >
        <span
          className={"badge " + (status.data?.accepting_orders ? "" : "muted")}
        >
          {status.data
            ? status.data.accepting_orders
              ? "接單中"
              : status.data.closed_reason
            : "…"}
        </span>
      </Heading>
      {status.data && <PauseControl status={status.data} />}
      <Alert message={tabs.error?.message} />
      {tabs.isPending && <p>載入中…</p>}
      {STAGES.map(({ key, title, empty }) => {
        // A table that was scanned but has not ordered yet is not work for anyone.
        const rows = (tabs.data ?? []).filter(
          (t) => t.rounds.length > 0 && stage(t) === key,
        );
        if (key === "ended")
          return (
            <details
              key={key}
              open={showEnded}
              onToggle={(e) => setShowEnded(e.currentTarget.open)}
            >
              <summary>
                <strong>
                  {title}（{rows.length}）
                </strong>
              </summary>
              <div className="order-grid">
                {rows.map((tab) => (
                  <TabCard
                    key={tab.id}
                    tab={tab}
                    now={now}
                    currency={currency}
                    timezone={timezone}
                    amend={setAmending}
                  />
                ))}
              </div>
            </details>
          );
        return (
          <section key={key} className={`order-stage stage-${key}`}>
            <div className="section-head compact">
              <h2>
                {title} <span className="muted">{rows.length}</span>
              </h2>
            </div>
            {rows.length === 0 && <p className="empty">{empty}</p>}
            <div className="order-grid">
              {rows.map((tab) => (
                <TabCard
                  key={tab.id}
                  tab={tab}
                  now={now}
                  currency={currency}
                  timezone={timezone}
                  amend={setAmending}
                />
              ))}
            </div>
          </section>
        );
      })}
      {amending && (
        <AmendDialog
          round={amending}
          currency={currency}
          close={() => setAmending(null)}
        />
      )}
    </>
  );
}

function TabCard({
  tab,
  now,
  currency,
  timezone,
  amend,
}: {
  tab: ConsoleTab;
  now: number;
  currency: string;
  timezone: string;
  amend: (round: ConsoleRound) => void;
}) {
  const action = useAction();
  const takeout = tab.service_mode === "takeout";
  const act = (round: ConsoleRound, name: string, data: object = {}) =>
    action.run(() => change(`rounds/${round.id}/${name}/`, "POST", data));
  const today = new Intl.DateTimeFormat("en-CA", { timeZone: timezone }).format(
    new Date(),
  );
  return (
    <article className={`panel order-card ${tab.closed_at ? "closed" : ""}`}>
      <header>
        <div>
          <strong className="order-code">
            {takeout ? `#${tab.pickup_code}` : `桌 ${tab.table_code}`}
          </strong>
          <small>
            {takeout ? "外帶" : "內用"}
            {tab.business_date !== today && ` · ${tab.business_date}`}
          </small>
        </div>
        <span className="badge">{money(ordered(tab), currency)}</span>
      </header>
      {(tab.customer_name || tab.phone) && (
        <p className="muted">
          {[
            tab.from_agenrena && `◆ Agenrena ${tab.customer_name}`,
            tab.phone && `電話 ${tab.phone}`,
          ]
            .filter(Boolean)
            .join(" · ")}
        </p>
      )}
      {tab.rounds.map((round, index) => (
        <div key={round.id} className={`round round-${round.status}`}>
          <div className="round-head">
            <span>
              {tab.rounds.length > 1 && `第 ${index + 1} 次 · `}
              {round.source === "agent"
                ? "Agent 連結"
                : round.source === "staff"
                  ? "店員"
                  : "QR"}
            </span>
            <span className={`status status-${round.status}`}>
              {round.status_text}
              {round.status === "pending" &&
                ` ${elapsed(round.created_at, now)}`}
              {round.status === "confirmed" &&
                ` ${elapsed(round.status_changed_at, now)}`}
            </span>
          </div>
          <ul className="round-lines">
            {round.items.map((line) => (
              <li key={line.id}>
                <span>
                  {line.name} × {line.quantity}
                  {line.choices.length > 0 && (
                    <small>{line.choices.map((c) => c.name).join("、")}</small>
                  )}
                  {line.note && <small>備註：{line.note}</small>}
                </span>
                <span>{money(line.total)}</span>
              </li>
            ))}
          </ul>
          {round.customer_note && (
            <p className="muted">顧客備註：{round.customer_note}</p>
          )}
          {round.shop_message && (
            <p className="muted">拒單原因：{round.shop_message}</p>
          )}
          {(round.status === "pending" || round.status === "confirmed") && (
            <div className="actions">
              {round.status === "pending" ? (
                <button
                  className="primary"
                  disabled={action.busy}
                  onClick={() => void act(round, "confirm")}
                >
                  接單
                </button>
              ) : (
                <button
                  className="primary"
                  disabled={action.busy}
                  onClick={() => void act(round, "complete")}
                >
                  完成餐點
                </button>
              )}
              <button disabled={action.busy} onClick={() => amend(round)}>
                修改
              </button>
              <button
                className="danger"
                disabled={action.busy}
                onClick={() => {
                  const message = window.prompt("拒單原因（會顯示給顧客）", "");
                  if (message !== null) void act(round, "reject", { message });
                }}
              >
                拒單
              </button>
            </div>
          )}
        </div>
      ))}
      {!tab.closed_at && stage(tab) === "settle" && (
        <button
          className="wide"
          disabled={action.busy}
          onClick={() => {
            if (
              window.confirm(
                `確認已現場結帳 ${money(tab.total, currency)}？關帳後這張帳單不能再加點。`,
              )
            )
              void action.run(() =>
                change(`tabs/${tab.id}/close/`, "POST", {}),
              );
          }}
        >
          結帳／關帳
        </button>
      )}
      <Alert message={action.error} />
    </article>
  );
}

/** Busy? Stop new orders everywhere for a while; what was sent stays. */
function PauseControl({ status }: { status: HoursStatus }) {
  const action = useAction();
  const pause = (minutes: number | null) => {
    const reason = window.prompt("暫停原因（顧客看得到）", "訂單較多，請稍候");
    if (reason !== null)
      void action.run(() =>
        change("ordering-status/", "POST", {
          action: "pause",
          minutes,
          reason,
        }),
      );
  };
  return (
    <section className="panel pause-bar">
      {status.paused ? (
        <>
          <span>{status.closed_reason}</span>
          <button
            className="primary"
            disabled={action.busy}
            onClick={() =>
              void action.run(() =>
                change("ordering-status/", "POST", { action: "resume" }),
              )
            }
          >
            恢復接單
          </button>
        </>
      ) : (
        <>
          <span>忙不過來時可暫停新訂單，已送出的訂單不受影響。</span>
          <div className="actions">
            <button disabled={action.busy} onClick={() => pause(15)}>
              暫停 15 分鐘
            </button>
            <button disabled={action.busy} onClick={() => pause(30)}>
              30 分鐘
            </button>
            <button disabled={action.busy} onClick={() => pause(null)}>
              直到恢復
            </button>
          </div>
        </>
      )}
      <Alert message={action.error} />
    </section>
  );
}

interface Draft {
  item: string;
  name: string;
  quantity: number;
  note: string;
  unit_price: string;
  options: string[];
  /** A chosen option that has since been deleted: the line cannot be re-sent as is. */
  lost: boolean;
}

function AmendDialog({
  round,
  currency,
  close,
}: {
  round: ConsoleRound;
  currency: string;
  close: () => void;
}) {
  const items = useData<AdminItem[]>("menu-items/");
  const groups = useData<OptionGroupRow[]>("option-groups/");
  const action = useAction();
  const [lines, setLines] = useState<Draft[]>(
    round.items.map((l) => ({
      item: l.item ?? "",
      name: l.name,
      quantity: l.quantity,
      note: l.note,
      unit_price: l.unit_price,
      options: l.choices.flatMap((c) => (c.option ? [c.option] : [])),
      lost: l.choices.some((c) => !c.option),
    })),
  );
  const [adding, setAdding] = useState("");
  const missing = lines.some((l) => !l.item || l.lost);
  const allOptions = (groups.data ?? []).flatMap((g) => g.options);
  const delta = (ids: string[]) =>
    ids.reduce(
      (sum, id) =>
        sum + Number(allOptions.find((o) => o.id === id)?.price_delta ?? 0),
      0,
    );
  const total = lines.reduce(
    (sum, l) =>
      sum + (Number(l.unit_price || 0) + delta(l.options)) * l.quantity,
    0,
  );
  const groupsFor = (itemId: string) => {
    const ids = items.data?.find((i) => i.id === itemId)?.option_groups ?? [];
    return (groups.data ?? []).filter((g) => ids.includes(g.id));
  };
  const update = (index: number, patch: Partial<Draft>) =>
    setLines((current) =>
      current.map((l, i) => (i === index ? { ...l, ...patch } : l)),
    );
  const save = (confirm: boolean) =>
    action.run(async () => {
      await change(`rounds/${round.id}/amend/`, "POST", {
        items: lines.map((l) => ({
          item: l.item,
          quantity: l.quantity,
          note: l.note,
          unit_price: l.unit_price,
          options: l.options,
        })),
        confirm,
      });
      close();
    });
  return (
    <Modal title="修改訂單" close={close}>
      <p className="muted">
        先和顧客談妥再修改。售完標示不會阻擋店員；價格可改成談好的金額。
      </p>
      {lines.map((line, index) => (
        <div className="amend-line" key={index}>
          <strong>{line.name}</strong>
          <Field label="數量">
            <input
              type="number"
              min={1}
              max={99}
              value={line.quantity}
              onChange={(e) =>
                update(index, {
                  quantity: Math.max(
                    1,
                    Math.min(99, Number(e.target.value) || 1),
                  ),
                })
              }
            />
          </Field>
          {groupsFor(line.item).map((group) => (
            <div key={group.id} className="amend-options">
              <span>
                {group.name}
                <small>
                  {group.min_select > 0 ? `必選 ${group.min_select}` : "可選"}
                  ，最多 {group.max_select}
                </small>
              </span>
              {group.options.map((option) => (
                <label key={option.id} className="check">
                  <input
                    type="checkbox"
                    checked={line.options.includes(option.id)}
                    onChange={(e) => {
                      const others = line.options.filter(
                        (id) => !group.options.some((o) => o.id === id),
                      );
                      const mine = line.options.filter((id) =>
                        group.options.some((o) => o.id === id),
                      );
                      const next = e.target.checked
                        ? group.max_select === 1
                          ? [option.id]
                          : [...mine, option.id].slice(-group.max_select)
                        : mine.filter((id) => id !== option.id);
                      update(index, {
                        options: [...others, ...next],
                        lost: false,
                      });
                    }}
                  />
                  {option.name}
                  {Number(option.price_delta)
                    ? ` +${money(option.price_delta)}`
                    : ""}
                  {!option.is_available && "（售完）"}
                </label>
              ))}
            </div>
          ))}
          <Field label="單價（不含選項加價）">
            <input
              type="number"
              min={0}
              step="0.01"
              value={line.unit_price}
              onChange={(e) => update(index, { unit_price: e.target.value })}
            />
          </Field>
          <Field label="備註">
            <input
              value={line.note}
              maxLength={200}
              onChange={(e) => update(index, { note: e.target.value })}
            />
          </Field>
          <button
            className="danger"
            onClick={() => setLines((c) => c.filter((_, i) => i !== index))}
          >
            移除
          </button>
          {!line.item && (
            <small className="danger">
              這道菜已從菜單刪除，請移除後改選其他餐點。
            </small>
          )}
          {line.item && line.lost && (
            <small className="danger">原本的選項已被刪除，請重新勾選。</small>
          )}
        </div>
      ))}
      <Field label="加一道菜">
        <select
          value={adding}
          onChange={(e) => {
            const item = items.data?.find((i) => i.id === e.target.value);
            if (item)
              setLines((c) => [
                ...c,
                {
                  item: item.id,
                  name: item.name,
                  quantity: 1,
                  note: "",
                  unit_price: item.price,
                  options: [],
                  lost: false,
                },
              ]);
            setAdding("");
          }}
        >
          <option value="">選擇餐點</option>
          {items.data
            ?.filter((i) => i.is_active)
            .map((i) => (
              <option key={i.id} value={i.id}>
                {i.name} · {money(i.price)}
                {i.availability === "sold_out" ? "（售完）" : ""}
              </option>
            ))}
        </select>
      </Field>
      <p>
        修改後金額：<strong>{money(total, currency)}</strong>
      </p>
      <Alert
        message={action.error || items.error?.message || groups.error?.message}
      />
      <div className="actions">
        <button
          className="primary"
          disabled={action.busy || !lines.length || missing}
          onClick={() => void save(false)}
        >
          儲存修改
        </button>
        {round.status === "pending" && (
          <button
            disabled={action.busy || !lines.length || missing}
            onClick={() => void save(true)}
          >
            儲存並接單
          </button>
        )}
      </div>
    </Modal>
  );
}
