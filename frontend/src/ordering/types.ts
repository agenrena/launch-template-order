export type RoundStatus =
  "pending" | "confirmed" | "completed" | "rejected" | "cancelled";
export interface ConsoleLine {
  id: string;
  item: string | null;
  name: string;
  unit_price: string;
  quantity: number;
  note: string;
  choices: {
    option: string | null;
    group: string;
    name: string;
    price_delta: string;
  }[];
  total: string;
}
export interface ConsoleRound {
  id: string;
  status: RoundStatus;
  status_text: string;
  shop_message: string;
  customer_note: string;
  items: ConsoleLine[];
  total: string;
  created_at: string;
  status_changed_at: string;
  source: "customer" | "agent" | "staff";
}
export interface ConsoleTab {
  id: string;
  service_mode: "dine_in" | "takeout";
  table_code: string;
  pickup_code: string;
  business_date: string;
  phone: string;
  customer_name: string;
  from_agenrena: boolean;
  total: string;
  closed_at: string | null;
  created_at: string;
  rounds: ConsoleRound[];
}
export interface Category {
  id: string;
  name: string;
  sort_order: number;
  is_active: boolean;
}
export interface AdminItem {
  id: string;
  category: string;
  name: string;
  description: string;
  price: string;
  availability: "available" | "sold_out";
  guidance: string;
  sort_order: number;
  is_active: boolean;
  option_groups: string[];
}
export interface OptionGroupRow {
  id: string;
  name: string;
  min_select: number;
  max_select: number;
  sort_order: number;
  options: {
    id: string;
    name: string;
    price_delta: string;
    is_available: boolean;
  }[];
}
export interface TableRow {
  id: string;
  code: string;
  is_active: boolean;
}
export interface OrderingSettings {
  currency: string;
  accepts_dine_in: boolean;
  accepts_takeout: boolean;
  last_order_minutes_before_close: number;
  agenrena_short_id: string;
}
export interface HoursStatus {
  accepting_orders: boolean;
  closed_reason: string;
  paused: boolean;
  paused_until: string | null;
  pause_reason: string;
  weekly_hours: {
    weekday: number;
    label: string;
    intervals: { opens_at: string; closes_at: string }[];
  }[];
  last_order_minutes_before_close: number;
}
export const money = (value: string | number, currency = "") =>
  `${currency ? currency + " " : ""}${Number(value).toLocaleString("zh-TW", {
    maximumFractionDigits: 2,
  })}`;
export interface Today {
  business_date: string;
  orders: number;
  revenue: string;
  pending: number;
  currency: string;
}
