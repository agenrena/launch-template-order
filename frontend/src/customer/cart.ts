import { useCallback, useEffect, useState } from "react";
import type { LineInput, MenuItem } from "./web";

export interface CartLine {
  key: string;
  item: string;
  name: string;
  /** The dish's price plus every chosen option, for one. */
  price: string;
  quantity: number;
  note: string;
  options: string[];
  /** 半糖、珍珠: what to read back. */
  labels: string[];
}

function read(key: string, initial: CartLine[] = []): CartLine[] {
  // What the customer already changed wins over what the link prefilled.
  try {
    const raw = window.localStorage.getItem(key);
    const saved = raw ? (JSON.parse(raw) as CartLine[]) : initial;
    return saved.map((l) => ({
      ...l,
      options: l.options ?? [],
      labels: l.labels ?? [],
    }));
  } catch {
    return initial;
  }
}

/** The price and labels of one dish with these option ids, or null if an id is unknown. */
export function priced(item: MenuItem, optionIds: string[]) {
  const all = item.option_groups.flatMap((g) => g.options);
  const chosen = optionIds.map((id) => all.find((o) => o.id === id));
  if (chosen.some((o) => !o)) return null;
  const price =
    Number(item.price) +
    chosen.reduce((sum, o) => sum + Number(o!.price_delta), 0);
  return { price: price.toFixed(2), labels: chosen.map((o) => o!.name) };
}

/** One cart per table, per takeout visit or per Agent link, kept across reloads. */
export function useCart(storageKey: string, initial?: CartLine[]) {
  const key = `order-cart:${storageKey}`;
  const [lines, setLines] = useState<CartLine[]>(() => read(key, initial));
  useEffect(() => {
    try {
      window.localStorage.setItem(key, JSON.stringify(lines));
    } catch {
      // Private browsing: the cart still works for this page.
    }
  }, [key, lines]);
  const add = useCallback(
    (item: MenuItem, quantity: number, note: string, options: string[]) => {
      const detail = priced(item, options);
      if (!detail) return;
      setLines((current) => {
        const same = current.find(
          (l) =>
            l.item === item.id &&
            l.note === note &&
            l.options.join() === options.join(),
        );
        if (same)
          return current.map((l) =>
            l === same
              ? { ...l, quantity: Math.min(99, l.quantity + quantity) }
              : l,
          );
        return [
          ...current,
          {
            key: `${item.id}:${Date.now()}`,
            item: item.id,
            name: item.name,
            price: detail.price,
            quantity,
            note,
            options,
            labels: detail.labels,
          },
        ];
      });
    },
    [],
  );
  const setQuantity = useCallback((lineKey: string, quantity: number) => {
    setLines((current) =>
      quantity <= 0
        ? current.filter((l) => l.key !== lineKey)
        : current.map((l) =>
            l.key === lineKey ? { ...l, quantity: Math.min(99, quantity) } : l,
          ),
    );
  }, []);
  const clear = useCallback(() => setLines([]), []);
  const total = lines.reduce((sum, l) => sum + Number(l.price) * l.quantity, 0);
  const inputs: LineInput[] = lines.map((l) => ({
    item: l.item,
    quantity: l.quantity,
    ...(l.options.length ? { options: l.options } : {}),
    ...(l.note ? { note: l.note } : {}),
  }));
  return { lines, add, setQuantity, clear, total, inputs };
}

/** An Agent link's cart, with today's names and prices. Unknown dishes or choices are dropped. */
export function hydrate(items: LineInput[], menu: { items: MenuItem[] }[]) {
  const byId = new Map(menu.flatMap((c) => c.items).map((i) => [i.id, i]));
  const lines: CartLine[] = [];
  let complete = true;
  items.forEach((line, index) => {
    const item = byId.get(line.item);
    const detail = item && priced(item, line.options ?? []);
    if (!item || !detail) {
      complete = false;
      return;
    }
    lines.push({
      key: `${item.id}:${index}`,
      item: item.id,
      name: item.name,
      price: detail.price,
      quantity: line.quantity,
      note: line.note ?? "",
      options: line.options ?? [],
      labels: detail.labels,
    });
  });
  return { lines, complete };
}
