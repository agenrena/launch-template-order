import type { MenuPhoto } from "../ordering/Photos";
/** The public ordering API. Nobody signs in: the table or the link is the credential. */
export interface OptionGroup {
  id: string;
  name: string;
  min_select: number;
  max_select: number;
  options: {
    id: string;
    name: string;
    price_delta: string;
    available: boolean;
  }[];
}
export interface MenuItem {
  photos: MenuPhoto[];
  id: string;
  name: string;
  description: string;
  price: string;
  orderable: boolean;
  option_groups: OptionGroup[];
}
export interface Store {
  name: string;
  about: string;
  address: string;
  phone: string;
  timezone: string;
  currency: string;
  accepts_dine_in: boolean;
  accepts_takeout: boolean;
  accepting_orders: boolean;
  closed_reason: string;
  paused: boolean;
  weekly_hours: {
    weekday: number;
    label: string;
    intervals: { opens_at: string; closes_at: string }[];
  }[];
  last_order_minutes_before_close: number;
  ask_url: string;
  menu: { id: string; name: string; items: MenuItem[] }[];
}
export interface Line {
  name: string;
  unit_price: string;
  quantity: number;
  note: string;
  choices: { group: string; name: string; price_delta: string }[];
  total: string;
}
export interface Round {
  id: string;
  status: "pending" | "confirmed" | "completed" | "rejected" | "cancelled";
  status_text: string;
  shop_message: string;
  customer_note: string;
  items: Line[];
  total: string;
  created_at: string;
}
export interface Tab {
  access_token: string;
  service_mode: "dine_in" | "takeout";
  table_code: string;
  pickup_code: string;
  open: boolean;
  total: string;
  rounds: Round[];
  created_at: string;
  store_name: string;
  timezone: string;
  currency: string;
  ask_url: string;
}
export interface LineInput {
  item: string;
  quantity: number;
  options?: string[];
  note?: string;
}
export interface Draft {
  status: "pending" | "expired" | "submitted";
  expires_at: string;
  items: LineInput[];
  note: string;
  store: Store;
  order?: Tab;
}
export class OrderError extends Error {
  constructor(
    readonly code: string,
    message: string,
    readonly nextSteps = "",
  ) {
    super(message);
  }
}
async function call<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(`/api/web/${path}`, {
    method: body === undefined ? "GET" : "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok)
    throw new OrderError(
      payload.error ?? "request_failed",
      payload.message ??
        (response.status === 429
          ? "操作太頻繁，請稍後再試。"
          : "暫時無法完成，請稍後再試。"),
      payload.next_steps ?? "",
    );
  return payload as T;
}
export const web = {
  store: () => call<Store>("store/"),
  joinTable: (table: string) => call<Tab>("tabs/", { table }),
  takeout: (items: LineInput[], phone: string, note: string) =>
    call<Tab>("orders/", { items, phone, note }),
  tab: (token: string) => call<Tab>(`tabs/${encodeURIComponent(token)}/`),
  addRound: (token: string, items: LineInput[], note: string) =>
    call<Tab>(`tabs/${encodeURIComponent(token)}/rounds/`, { items, note }),
  draft: (token: string) =>
    call<Draft>(`order-drafts/${encodeURIComponent(token)}/`),
  confirmDraft: (
    token: string,
    items: LineInput[],
    phone: string,
    note: string,
  ) =>
    call<Tab>(`order-drafts/${encodeURIComponent(token)}/confirm/`, {
      items,
      phone,
      note,
    }),
};
export function money(amount: string | number, currency: string) {
  const value = Number(amount);
  return `${currency} ${value.toLocaleString("zh-TW", {
    minimumFractionDigits: Number.isInteger(value) ? 0 : 2,
    maximumFractionDigits: 2,
  })}`;
}
