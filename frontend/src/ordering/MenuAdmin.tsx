/** The menu: categories, dishes, prices and today's sold-out switches. */
import { useState } from "react";
import { change, useData } from "../api";
import { Alert, Field, Form, Modal, text, useAction } from "../ui";
import { Heading } from "../Heading";
import {
  money,
  type AdminItem,
  type Category,
  type OptionGroupRow,
  type OrderingSettings,
} from "./types";

export function MenuAdmin() {
  const categories = useData<Category[]>("categories/");
  const items = useData<AdminItem[]>("menu-items/");
  const settings = useData<OrderingSettings>("ordering-settings/");
  const groups = useData<OptionGroupRow[]>("option-groups/");
  const [group, setGroup] = useState<OptionGroupRow | "new" | null>(null);
  const action = useAction();
  const [editing, setEditing] = useState<
    AdminItem | { category: string } | null
  >(null);
  const [category, setCategory] = useState<Category | "new" | null>(null);
  const currency = settings.data?.currency ?? "";
  return (
    <>
      <Heading
        title="菜單"
        description="顧客、Agent 與店員看到的是同一份菜單。當天沒了就標售完；下架則是整道菜暫時不賣。"
      >
        <button className="primary" onClick={() => setCategory("new")}>
          ＋ 新增分類
        </button>
      </Heading>
      <Alert
        message={
          categories.error?.message || items.error?.message || action.error
        }
      />
      {categories.data?.length === 0 && (
        <p className="panel empty">先新增一個分類，例如「主餐」或「飲料」。</p>
      )}
      {categories.data?.map((c) => {
        const rows = items.data?.filter((i) => i.category === c.id) ?? [];
        return (
          <section className="panel menu-section" key={c.id}>
            <div className="section-head compact">
              <h2>
                {c.name}{" "}
                {!c.is_active && <span className="badge muted">已停用</span>}
              </h2>
              <div className="actions">
                <button onClick={() => setCategory(c)}>編輯分類</button>
                <button
                  className="primary"
                  onClick={() => setEditing({ category: c.id })}
                >
                  ＋ 餐點
                </button>
              </div>
            </div>
            {rows.length === 0 && <p className="empty">這個分類還沒有餐點。</p>}
            {rows.map((item) => (
              <div className="list-row" key={item.id}>
                <div>
                  <strong>{item.name}</strong>
                  <small>
                    {money(item.price, currency)}
                    {!item.is_active && " · 已下架"}
                    {item.guidance && " · 有給 Agent 的說明"}
                  </small>
                </div>
                <div className="actions">
                  <label className="check">
                    <input
                      type="checkbox"
                      checked={item.availability === "sold_out"}
                      disabled={action.busy || !item.is_active}
                      onChange={(e) =>
                        void action.run(() =>
                          change(`menu-items/${item.id}/`, "PATCH", {
                            availability: e.target.checked
                              ? "sold_out"
                              : "available",
                          }),
                        )
                      }
                    />
                    售完
                  </label>
                  <button onClick={() => setEditing(item)}>編輯</button>
                </div>
              </div>
            ))}
          </section>
        );
      })}
      <section className="panel menu-section">
        <div className="section-head compact">
          <h2>選項群組</h2>
          <button className="primary" onClick={() => setGroup("new")}>
            ＋ 選項群組
          </button>
        </div>
        <p className="muted">
          甜度、冰塊、加料、大小等。建一次，就能在多道餐點上使用；改群組會影響所有使用它的餐點。
        </p>
        <Alert message={groups.error?.message} />
        {groups.data?.length === 0 && <p className="empty">還沒有選項群組。</p>}
        {groups.data?.map((g) => (
          <div className="list-row" key={g.id}>
            <div>
              <strong>{g.name}</strong>
              <small>
                {g.min_select > 0 ? `必選 ${g.min_select}` : "可選"}，最多{" "}
                {g.max_select} · 用於{" "}
                {items.data?.filter((i) => i.option_groups.includes(g.id))
                  .length ?? 0}{" "}
                道餐點
              </small>
              <div className="option-chips">
                <small>勾選表示售完：</small>
                {g.options.map((o) => (
                  <label key={o.id} className="check">
                    <input
                      type="checkbox"
                      checked={!o.is_available}
                      disabled={action.busy}
                      onChange={(e) =>
                        void action.run(() =>
                          change(`options/${o.id}/`, "PATCH", {
                            is_available: !e.target.checked,
                          }),
                        )
                      }
                    />
                    {o.name}
                    {Number(o.price_delta) ? ` +${money(o.price_delta)}` : ""}
                  </label>
                ))}
              </div>
            </div>
            <button onClick={() => setGroup(g)}>編輯</button>
          </div>
        ))}
      </section>
      {category && (
        <CategoryEditor category={category} close={() => setCategory(null)} />
      )}
      {group && <GroupEditor group={group} close={() => setGroup(null)} />}
      {editing && categories.data && (
        <ItemEditor
          item={editing}
          categories={categories.data}
          groups={groups.data ?? []}
          close={() => setEditing(null)}
        />
      )}
    </>
  );
}

function CategoryEditor({
  category,
  close,
}: {
  category: Category | "new";
  close: () => void;
}) {
  const current = category === "new" ? null : category;
  const action = useAction();
  return (
    <Modal title={current ? "編輯分類" : "新增分類"} close={close}>
      <Form
        busy={action.busy}
        onSubmit={(d) =>
          action.run(async () => {
            await change(
              `categories/${current ? current.id + "/" : ""}`,
              current ? "PATCH" : "POST",
              {
                name: text(d, "name"),
                sort_order: Number(d.get("sort_order") || 0),
                is_active: d.get("is_active") === "on",
              },
            );
            close();
          })
        }
      >
        <Field label="名稱">
          <input
            name="name"
            defaultValue={current?.name}
            maxLength={120}
            required
          />
        </Field>
        <Field label="排序（數字小的在前）">
          <input
            name="sort_order"
            type="number"
            min={0}
            defaultValue={current?.sort_order ?? 0}
          />
        </Field>
        <label className="check">
          <input
            name="is_active"
            type="checkbox"
            defaultChecked={current?.is_active ?? true}
          />
          顯示在菜單上
        </label>
        <Alert message={action.error} />
        <button className="primary">儲存</button>
      </Form>
    </Modal>
  );
}

function ItemEditor({
  item,
  categories,
  groups,
  close,
}: {
  item: AdminItem | { category: string };
  categories: Category[];
  groups: OptionGroupRow[];
  close: () => void;
}) {
  const current = "id" in item ? item : null;
  const action = useAction();
  return (
    <Modal title={current ? "編輯餐點" : "新增餐點"} close={close}>
      <Form
        busy={action.busy}
        onSubmit={(d) =>
          action.run(async () => {
            await change(
              `menu-items/${current ? current.id + "/" : ""}`,
              current ? "PATCH" : "POST",
              {
                category: text(d, "category"),
                name: text(d, "name"),
                description: text(d, "description"),
                price: text(d, "price"),
                guidance: text(d, "guidance"),
                sort_order: Number(d.get("sort_order") || 0),
                is_active: d.get("is_active") === "on",
                // Only when the list was shown: never clear groups that did not load.
                ...(groups.length
                  ? { option_groups: d.getAll("option_groups").map(String) }
                  : {}),
              },
            );
            close();
          })
        }
      >
        <Field label="分類">
          <select name="category" defaultValue={item.category}>
            {categories.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
        </Field>
        <Field label="名稱">
          <input
            name="name"
            defaultValue={current?.name}
            maxLength={120}
            required
          />
        </Field>
        <Field label="價格">
          <input
            name="price"
            type="number"
            min={0}
            step="0.01"
            defaultValue={current?.price ?? "0"}
            required
          />
        </Field>
        <Field label="介紹（顧客看得到）">
          <textarea
            name="description"
            rows={3}
            maxLength={1000}
            defaultValue={current?.description}
          />
        </Field>
        <Field label="給 Agent 的說明（顧客看不到）">
          <textarea
            name="guidance"
            rows={3}
            maxLength={1000}
            defaultValue={current?.guidance}
            placeholder="例如：想配飲料的客人，推薦加點紅茶。"
          />
        </Field>
        {groups.length > 0 && (
          <fieldset className="option-pick">
            <legend>選項群組</legend>
            {groups.map((g) => (
              <label key={g.id} className="check">
                <input
                  name="option_groups"
                  type="checkbox"
                  value={g.id}
                  defaultChecked={current?.option_groups.includes(g.id)}
                />
                {g.name}
              </label>
            ))}
          </fieldset>
        )}
        <Field label="排序（數字小的在前）">
          <input
            name="sort_order"
            type="number"
            min={0}
            defaultValue={current?.sort_order ?? 0}
          />
        </Field>
        <label className="check">
          <input
            name="is_active"
            type="checkbox"
            defaultChecked={current?.is_active ?? true}
          />
          上架中
        </label>
        <p className="muted">
          改價只影響之後的訂單；已送出的訂單保留當時的價格。
        </p>
        <Alert message={action.error} />
        <button className="primary">儲存</button>
      </Form>
    </Modal>
  );
}

interface OptionDraft {
  id?: string;
  name: string;
  price_delta: string;
  is_available: boolean;
}

function GroupEditor({
  group,
  close,
}: {
  group: OptionGroupRow | "new";
  close: () => void;
}) {
  const current = group === "new" ? null : group;
  const action = useAction();
  const [name, setName] = useState(current?.name ?? "");
  const [min, setMin] = useState(current?.min_select ?? 0);
  const [max, setMax] = useState(current?.max_select ?? 1);
  const [options, setOptions] = useState<OptionDraft[]>(
    current?.options.map((o) => ({ ...o })) ?? [
      { name: "", price_delta: "0", is_available: true },
    ],
  );
  const update = (index: number, patch: Partial<OptionDraft>) =>
    setOptions((all) =>
      all.map((o, i) => (i === index ? { ...o, ...patch } : o)),
    );
  const move = (index: number, by: number) =>
    setOptions((all) => {
      const next = [...all];
      const [row] = next.splice(index, 1);
      next.splice(Math.max(0, Math.min(next.length, index + by)), 0, row);
      return next;
    });
  return (
    <Modal title={current ? "編輯選項群組" : "新增選項群組"} close={close}>
      <Field label="名稱">
        <input
          value={name}
          maxLength={60}
          onChange={(e) => setName(e.target.value)}
          placeholder="甜度"
        />
      </Field>
      <div className="actions">
        <Field label="最少選">
          <input
            type="number"
            min={0}
            value={min}
            onChange={(e) => setMin(Number(e.target.value) || 0)}
          />
        </Field>
        <Field label="最多選">
          <input
            type="number"
            min={1}
            value={max}
            onChange={(e) => setMax(Number(e.target.value) || 1)}
          />
        </Field>
      </div>
      <p className="muted">
        最少 1、最多 1 就是「必選一個」；最少 0 表示可以不選。
      </p>
      {options.map((option, index) => (
        <div className="option-row" key={option.id ?? `new-${index}`}>
          <input
            aria-label="選項名稱"
            value={option.name}
            maxLength={60}
            placeholder="半糖"
            onChange={(e) => update(index, { name: e.target.value })}
          />
          <input
            aria-label="加價"
            type="number"
            step="0.01"
            value={option.price_delta}
            onChange={(e) => update(index, { price_delta: e.target.value })}
          />
          <button
            type="button"
            aria-label="上移"
            onClick={() => move(index, -1)}
          >
            ↑
          </button>
          <button
            type="button"
            aria-label="下移"
            onClick={() => move(index, 1)}
          >
            ↓
          </button>
          <button
            type="button"
            className="danger"
            onClick={() =>
              setOptions((all) => all.filter((_, i) => i !== index))
            }
          >
            移除
          </button>
        </div>
      ))}
      <button
        type="button"
        onClick={() =>
          setOptions((all) => [
            ...all,
            { name: "", price_delta: "0", is_available: true },
          ])
        }
      >
        ＋ 選項
      </button>
      <p className="muted">
        移除選項不影響已送出的訂單，訂單保留當時的名稱與加價。
      </p>
      <Alert message={action.error} />
      <button
        className="primary"
        disabled={
          action.busy || !name.trim() || options.some((o) => !o.name.trim())
        }
        onClick={() =>
          void action.run(async () => {
            await change(
              `option-groups/${current ? current.id + "/" : ""}`,
              current ? "PATCH" : "POST",
              {
                name: name.trim(),
                min_select: min,
                max_select: max,
                options: options.map((o) => ({
                  ...(o.id ? { id: o.id } : {}),
                  name: o.name.trim(),
                  price_delta: o.price_delta || "0",
                  is_available: o.is_available,
                })),
              },
            );
            close();
          })
        }
      >
        儲存
      </button>
    </Modal>
  );
}
