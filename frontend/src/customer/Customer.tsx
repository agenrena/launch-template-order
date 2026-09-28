/** What a customer with a phone sees: browse and order. Questions and
 * recommendations belong in the conversation with the store's Agent. */
import { useEffect, useState, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { hydrate, priced, useCart, type CartLine } from "./cart";
import {
  money,
  web,
  OrderError,
  type MenuItem,
  type OptionGroup,
  type Round,
  type Store,
  type Tab,
} from "./web";

const go = (path: string) => window.location.assign(path);

export function MenuPage() {
  const table = new URLSearchParams(window.location.search).get("table") ?? "";
  const client = useQueryClient();
  const store = useQuery({
    queryKey: ["web-store"],
    queryFn: web.store,
    refetchInterval: 30_000,
  });
  const tab = useQuery({
    queryKey: ["web-table", table],
    queryFn: () => web.joinTable(table),
    enabled: !!table && store.data?.accepting_orders === true,
    retry: false,
  });
  const cart = useCart(table ? `table:${table}` : "takeout");
  if (store.isPending) return <Message title="載入中…" />;
  if (!store.data)
    return <Message title="暫時無法載入菜單" body="請稍後再試。" />;
  const data = store.data;
  const takeoutOff = !table && !data.accepts_takeout;
  return (
    <Ordering
      store={data}
      subtitle={table ? `內用點餐 · ${table}` : "外帶點餐"}
      cart={cart}
      requiresPhone={!table}
      blocked={
        takeoutOff
          ? "這家店目前沒有提供外帶。"
          : table && tab.error
            ? tab.error.message
            : ""
      }
      ready={!table || !!tab.data}
      tab={tab.data}
      onSubmit={(phone, note) =>
        table
          ? web.addRound(tab.data!.access_token, cart.inputs, note)
          : web.takeout(cart.inputs, phone, note)
      }
      onFailed={() =>
        void client.invalidateQueries({ queryKey: ["web-store"] })
      }
    />
  );
}

export function DraftPage({ token }: { token: string }) {
  const draft = useQuery({
    queryKey: ["web-draft", token],
    queryFn: () => web.draft(token),
    retry: false,
    refetchInterval: 30_000,
  });
  if (draft.isPending) return <Message title="正在打開訂單…" />;
  if (!draft.data)
    return <Message title="連結無法使用" body="請回原對話取得新連結。" />;
  const data = draft.data;
  if (data.status === "submitted" && data.order)
    return (
      <Message title="這筆訂單已送出" body={`取餐號 ${data.order.pickup_code}`}>
        <button
          className="c-primary"
          onClick={() => go(`/o/${data.order!.access_token}`)}
        >
          查看訂單狀態
        </button>
      </Message>
    );
  if (data.status === "expired")
    return <Message title="確認連結已過期" body="請回原對話取得新連結。" />;
  return (
    <DraftCart
      token={token}
      store={data.store}
      items={data.items}
      note={data.note}
    />
  );
}

function DraftCart({
  token,
  store,
  items,
  note,
}: {
  token: string;
  store: Store;
  items: { item: string; quantity: number; note?: string }[];
  note: string;
}) {
  const client = useQueryClient();
  const prefilled = hydrate(items, store.menu);
  const cart = useCart(`draft:${token}`, prefilled.lines);
  return (
    <Ordering
      store={store}
      subtitle="Agent 幫你準備的外帶訂單"
      cart={cart}
      requiresPhone
      initialNote={note}
      openCart
      notice={
        prefilled.complete
          ? "請確認餐點、留下電話後送出。送出後由店家確認。"
          : "部分餐點已不在菜單上，已從購物車移除，請確認後再送出。"
      }
      ready
      onSubmit={(phone, orderNote) =>
        web.confirmDraft(token, cart.inputs, phone, orderNote)
      }
      onFailed={() =>
        void client.invalidateQueries({ queryKey: ["web-draft", token] })
      }
    />
  );
}

export function StatusPage({ token }: { token: string }) {
  const tab = useQuery({
    queryKey: ["web-tab", token],
    queryFn: () => web.tab(token),
    retry: false,
    refetchInterval: (query) =>
      (query.state.data as Tab | undefined)?.rounds.some(
        (r) => r.status === "pending",
      )
        ? 10_000
        : 60_000,
  });
  if (tab.isPending) return <Message title="載入中…" />;
  if (!tab.data)
    return <Message title="找不到訂單" body="請確認連結是否完整。" />;
  const data = tab.data;
  const takeout = data.service_mode === "takeout";
  const latest = data.rounds[data.rounds.length - 1];
  return (
    <Screen>
      <header className="c-header">
        <p className="c-eyebrow">
          {takeout ? "外帶訂單" : `內用 · ${data.table_code}`}
        </p>
        <h1>{data.store_name}</h1>
      </header>
      <main className="c-main">
        <section
          className={`c-progress c-${latest?.status ?? "pending"}`}
          role="status"
          aria-live="polite"
        >
          <p className="c-eyebrow">訂單進度</p>
          <h2>{latest ? latest.status_text : "還沒有送出的餐點"}</h2>
          {latest?.status === "pending" && (
            <p>店家確認後就會開始製作，這個頁面會自動更新。</p>
          )}
          <div className="c-code">
            <small>{takeout ? "取餐號" : "桌號"}</small>
            <strong>{takeout ? data.pickup_code : data.table_code}</strong>
          </div>
        </section>
        {data.rounds.map((round, index) => (
          <RoundCard
            key={round.id}
            round={round}
            currency={data.currency}
            label={
              data.rounds.length > 1 ? `第 ${index + 1} 次點餐` : "本次點餐"
            }
          />
        ))}
        <p className="c-total">
          <span>已接單金額</span>
          <strong>{money(data.total, data.currency)}</strong>
        </p>
        {!takeout && data.open && (
          <a
            className="c-primary"
            href={`/?table=${encodeURIComponent(data.table_code)}`}
          >
            繼續加點
          </a>
        )}
        {!takeout && !data.open && <p className="c-note">已結帳，無法加點。</p>}
        {takeout && (
          <a className="c-link" href="/">
            回到菜單
          </a>
        )}
        <AskLink name={data.store_name} url={data.ask_url} />
      </main>
    </Screen>
  );
}

function RoundCard({
  round,
  currency,
  label,
}: {
  round: Round;
  currency: string;
  label: string;
}) {
  const excluded = round.status === "rejected" || round.status === "cancelled";
  return (
    <article className="c-card">
      <header>
        <strong>{label}</strong>
        <span className={`c-badge c-${round.status}`}>{round.status_text}</span>
      </header>
      {round.shop_message && (
        <p className="c-warn">店家說明：{round.shop_message}</p>
      )}
      <ul className="c-lines">
        {round.items.map((line, index) => (
          <li key={index}>
            <div>
              {line.name} × {line.quantity}
              {line.choices.length > 0 && (
                <small>{line.choices.map((c) => c.name).join("、")}</small>
              )}
              {line.note && <small>備註：{line.note}</small>}
            </div>
            <span>{money(line.total, currency)}</span>
          </li>
        ))}
      </ul>
      {round.customer_note && (
        <p className="c-note">訂單備註：{round.customer_note}</p>
      )}
      <p className="c-subtotal">
        <span>
          {excluded
            ? "不計入帳單"
            : round.status === "pending"
              ? "待確認小計"
              : "小計"}
        </span>
        <span>{money(round.total, currency)}</span>
      </p>
    </article>
  );
}

function Ordering({
  store,
  subtitle,
  cart,
  requiresPhone,
  ready,
  blocked = "",
  notice = "",
  initialNote = "",
  openCart = false,
  tab,
  onSubmit,
  onFailed,
}: {
  store: Store;
  subtitle: string;
  cart: ReturnType<typeof useCart>;
  requiresPhone: boolean;
  ready: boolean;
  blocked?: string;
  notice?: string;
  initialNote?: string;
  openCart?: boolean;
  tab?: Tab;
  onSubmit: (phone: string, note: string) => Promise<Tab>;
  onFailed: () => void;
}) {
  const [picked, setPicked] = useState<MenuItem | null>(null);
  const [showCart, setShowCart] = useState(openCart);
  const closed = !store.accepting_orders || !!blocked;
  const portions = cart.lines.reduce((sum, l) => sum + l.quantity, 0);
  return (
    <Screen>
      <header className="c-header">
        <p className="c-eyebrow">{subtitle}</p>
        <div className="c-title">
          <h1>{store.name}</h1>
          <span className={`c-badge ${closed ? "c-pending" : "c-confirmed"}`}>
            {closed ? "目前不接單" : "接單中"}
          </span>
        </div>
        {!store.accepting_orders && (
          <p className="c-warn">{store.closed_reason}</p>
        )}
        {blocked && <p className="c-warn">{blocked}</p>}
        {notice && <p className="c-info">{notice}</p>}
        <Hours store={store} />
      </header>
      <main className={`c-main ${cart.lines.length ? "c-with-bar" : ""}`}>
        {tab && tab.rounds.length > 0 && (
          <a className="c-link" href={`/o/${tab.access_token}`}>
            這桌已點 {tab.rounds.length} 次，查看訂單 →
          </a>
        )}
        {store.menu.filter((c) => c.items.length).length === 0 && (
          <p className="c-note">暫無餐點。</p>
        )}
        {store.menu
          .filter((category) => category.items.length)
          .map((category) => (
            <section key={category.id} className="c-category">
              <h2>{category.name}</h2>
              <ul>
                {category.items.map((item) => (
                  <li key={item.id}>
                    <button
                      className="c-item"
                      disabled={!item.orderable || closed}
                      onClick={() => setPicked(item)}
                    >
                      <span>
                        <strong>{item.name}</strong>
                        {!item.orderable && <em>已售完</em>}
                        {item.description && <small>{item.description}</small>}
                      </span>
                      <b>{money(item.price, store.currency)}</b>
                    </button>
                  </li>
                ))}
              </ul>
            </section>
          ))}
        <AskLink name={store.name} url={store.ask_url} />
      </main>
      {cart.lines.length > 0 && (
        <div className="c-bar">
          <button className="c-primary" onClick={() => setShowCart(true)}>
            <span>{portions} 份 · 查看購物車</span>
            <span>{money(cart.total, store.currency)}</span>
          </button>
        </div>
      )}
      {picked && (
        <ItemSheet
          item={picked}
          currency={store.currency}
          close={() => setPicked(null)}
          add={(quantity, note, options) => {
            cart.add(picked, quantity, note, options);
            setPicked(null);
          }}
        />
      )}
      {showCart && (
        <CartSheet
          store={store}
          cart={cart}
          requiresPhone={requiresPhone}
          canSend={ready && !closed}
          initialNote={initialNote}
          close={() => setShowCart(false)}
          send={onSubmit}
          failed={onFailed}
        />
      )}
    </Screen>
  );
}

function ItemSheet({
  item,
  currency,
  close,
  add,
}: {
  item: MenuItem;
  currency: string;
  close: () => void;
  add: (quantity: number, note: string, options: string[]) => void;
}) {
  const [quantity, setQuantity] = useState(1);
  const [note, setNote] = useState("");
  const [picked, setPicked] = useState<Record<string, string[]>>({});
  const options = item.option_groups.flatMap((g) => picked[g.id] ?? []);
  const unit = priced(item, options);
  const missing = item.option_groups.filter(
    (g) => (picked[g.id]?.length ?? 0) < g.min_select,
  );
  function toggle(group: OptionGroup, id: string) {
    setPicked((current) => {
      const now = current[group.id] ?? [];
      if (now.includes(id))
        return { ...current, [group.id]: now.filter((x) => x !== id) };
      // A single choice swaps; a multiple choice stops at its limit.
      if (group.max_select === 1) return { ...current, [group.id]: [id] };
      if (now.length >= group.max_select) return current;
      return { ...current, [group.id]: [...now, id] };
    });
  }
  return (
    <Sheet title={item.name} close={close}>
      {item.description && <p className="c-note">{item.description}</p>}
      {item.option_groups.map((group) => (
        <fieldset className="c-group" key={group.id}>
          <legend>
            {group.name}
            <small>
              {group.min_select > 0
                ? group.min_select === group.max_select
                  ? `必選 ${group.min_select} 個`
                  : `選 ${group.min_select}–${group.max_select} 個`
                : `可選，最多 ${group.max_select} 個`}
            </small>
          </legend>
          {group.options.map((option) => {
            const on = picked[group.id]?.includes(option.id) ?? false;
            return (
              <label
                key={option.id}
                className={`c-choice ${option.available ? "" : "c-off"}`}
              >
                <input
                  type={group.max_select === 1 ? "radio" : "checkbox"}
                  name={group.id}
                  checked={on}
                  disabled={!option.available}
                  onChange={() => toggle(group, option.id)}
                  onClick={() =>
                    group.max_select === 1 && on && toggle(group, option.id)
                  }
                />
                <span>{option.name}</span>
                <small>
                  {!option.available
                    ? "售完"
                    : Number(option.price_delta)
                      ? `+${money(option.price_delta, currency)}`
                      : ""}
                </small>
              </label>
            );
          })}
        </fieldset>
      ))}
      <Stepper value={quantity} min={1} set={setQuantity} />
      <label className="c-field">
        <span>這道菜的備註（選填）</span>
        <input
          value={note}
          maxLength={200}
          onChange={(e) => setNote(e.target.value)}
          placeholder="不要香菜"
        />
      </label>
      <button
        className="c-primary"
        disabled={missing.length > 0 || !unit}
        onClick={() => add(quantity, note.trim(), options)}
      >
        <span>
          {missing.length ? `請選擇${missing[0].name}` : "加入購物車"}
        </span>
        <span>
          {money(Number(unit?.price ?? item.price) * quantity, currency)}
        </span>
      </button>
    </Sheet>
  );
}

function CartSheet({
  store,
  cart,
  requiresPhone,
  canSend,
  initialNote,
  close,
  send,
  failed,
}: {
  store: Store;
  cart: ReturnType<typeof useCart>;
  requiresPhone: boolean;
  canSend: boolean;
  initialNote: string;
  close: () => void;
  send: (phone: string, note: string) => Promise<Tab>;
  failed: () => void;
}) {
  const [phone, setPhone] = useState("");
  const [note, setNote] = useState(initialNote);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<OrderError | null>(null);
  async function submit() {
    setBusy(true);
    setError(null);
    try {
      const tab = await send(phone.trim(), note.trim());
      cart.clear();
      go(`/o/${tab.access_token}`);
    } catch (e) {
      setError(
        e instanceof OrderError
          ? e
          : new OrderError("failed", "送出失敗，請再試一次。"),
      );
      failed();
      setBusy(false);
    }
  }
  return (
    <Sheet title="確認訂單" close={close} busy={busy}>
      {cart.lines.length === 0 && <p className="c-note">購物車是空的。</p>}
      <ul className="c-lines">
        {cart.lines.map((line: CartLine) => (
          <li key={line.key}>
            <div>
              {line.name}
              {line.labels.length > 0 && (
                <small>{line.labels.join("、")}</small>
              )}
              {line.note && <small>備註：{line.note}</small>}
              <Stepper
                value={line.quantity}
                min={0}
                set={(q) => cart.setQuantity(line.key, q)}
              />
            </div>
            <span>
              {money(Number(line.price) * line.quantity, store.currency)}
            </span>
          </li>
        ))}
      </ul>
      <p className="c-total">
        <span>合計</span>
        <strong>{money(cart.total, store.currency)}</strong>
      </p>
      {requiresPhone && (
        <label className="c-field">
          <span>聯絡電話（必填，餐點有狀況時店家會打給你）</span>
          <input
            type="tel"
            inputMode="tel"
            autoComplete="tel"
            value={phone}
            maxLength={20}
            onChange={(e) => setPhone(e.target.value)}
          />
        </label>
      )}
      <label className="c-field">
        <span>訂單備註（選填）</span>
        <input
          value={note}
          maxLength={200}
          onChange={(e) => setNote(e.target.value)}
          placeholder="六點左右到"
        />
      </label>
      {error && (
        <p className="c-warn" role="alert">
          {error.message}
          {error.nextSteps && <small>{error.nextSteps}</small>}
        </p>
      )}
      <button
        className="c-primary"
        disabled={
          busy ||
          !canSend ||
          !cart.lines.length ||
          (requiresPhone && !phone.trim())
        }
        onClick={() => void submit()}
      >
        {busy ? "送出中…" : "確認並送出"}
      </button>
      {/* Never "order placed": everything waits for the shop to confirm. */}
      <p className="c-note">送出後由店家確認，確認前不會開始製作。</p>
    </Sheet>
  );
}

function Hours({ store }: { store: Store }) {
  // The store's weekday, not the phone's: Monday = 0 like the server.
  const short = new Intl.DateTimeFormat("en-US", {
    timeZone: store.timezone,
    weekday: "short",
  }).format(new Date());
  const today = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].indexOf(
    short,
  );
  const day = store.weekly_hours[today];
  const text = day?.intervals.length
    ? day.intervals.map((i) => `${i.opens_at}–${i.closes_at}`).join("、")
    : "今天公休";
  return (
    <details className="c-hours">
      <summary>今天 {text}</summary>
      <ul>
        {store.weekly_hours.map((d) => (
          <li key={d.weekday}>
            {d.label}：
            {d.intervals.length
              ? d.intervals
                  .map((i) => `${i.opens_at}–${i.closes_at}`)
                  .join("、")
              : "公休"}
          </li>
        ))}
      </ul>
      {store.last_order_minutes_before_close > 0 && (
        <small>
          打烊前 {store.last_order_minutes_before_close} 分鐘停止接單
        </small>
      )}
      {store.address && <small>地址：{store.address}</small>}
      {store.phone && <small>電話：{store.phone}</small>}
    </details>
  );
}

/** The one place this page points at the conversation: questions go to the Agent. */
function AskLink({ name, url }: { name: string; url: string }) {
  if (!url) return null;
  return (
    <a className="c-ask" href={url} rel="noreferrer">
      <strong>想問推薦、辣度或過敏原？</strong>
      <span>到 Agenrena 問 {name} 的 Agent，也能直接幫你點好 →</span>
    </a>
  );
}

function Stepper({
  value,
  min,
  set,
}: {
  value: number;
  min: number;
  set: (v: number) => void;
}) {
  return (
    <span className="c-stepper">
      <button
        type="button"
        aria-label="減少"
        onClick={() => set(Math.max(min, value - 1))}
      >
        −
      </button>
      <span aria-live="polite">{value}</span>
      <button
        type="button"
        aria-label="增加"
        disabled={value >= 99}
        onClick={() => set(value + 1)}
      >
        +
      </button>
    </span>
  );
}

function Sheet({
  title,
  close,
  busy = false,
  children,
}: {
  title: string;
  close: () => void;
  busy?: boolean;
  children: ReactNode;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && !busy && close();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [busy, close]);
  return (
    <div
      className="c-sheet-backdrop"
      onClick={(e) => e.target === e.currentTarget && !busy && close()}
    >
      <div
        className="c-sheet"
        role="dialog"
        aria-modal="true"
        aria-label={title}
      >
        <div className="c-sheet-head">
          <h2>{title}</h2>
          <button className="c-quiet" disabled={busy} onClick={close}>
            關閉
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

function Screen({ children }: { children: ReactNode }) {
  return <div className="customer">{children}</div>;
}

function Message({
  title,
  body,
  children,
}: {
  title: string;
  body?: string;
  children?: ReactNode;
}) {
  return (
    <Screen>
      <main className="c-main c-message">
        <h1>{title}</h1>
        {body && <p>{body}</p>}
        {children}
      </main>
    </Screen>
  );
}
