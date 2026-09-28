import { useState, type ReactNode, type FormEvent } from "react";
export function useAction() {
  const [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  async function run(action: () => Promise<unknown>) {
    if (busy) return;
    setError("");
    setBusy(true);
    try {
      await action();
    } catch (e) {
      setError(e instanceof Error ? e.message : "操作失敗，請再試一次。");
    } finally {
      setBusy(false);
    }
  }
  return { error, busy, run };
}
export function Alert({ message }: { message?: string }) {
  return message ? (
    <p role="alert" className="error">
      {message}
    </p>
  ) : null;
}
export function Field({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <label className="field">
      <span>{label}</span>
      {children}
    </label>
  );
}
export function Form({
  children,
  onSubmit,
  busy,
}: {
  children: ReactNode;
  onSubmit: (data: FormData) => Promise<unknown>;
  busy: boolean;
}) {
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void onSubmit(new FormData(event.currentTarget));
  }
  return (
    <form onSubmit={submit}>
      <fieldset disabled={busy}>{children}</fieldset>
    </form>
  );
}
export function Modal({
  title,
  children,
  close,
}: {
  title: string;
  children: ReactNode;
  close: () => void;
}) {
  return (
    <dialog
      ref={(node) => {
        if (node && !node.open) node.showModal();
      }}
      onCancel={close}
      onClick={(e) => {
        if (e.target === e.currentTarget) close();
      }}
    >
      <div className="modal-head">
        <h2>{title}</h2>
        <button
          type="button"
          className="quiet"
          aria-label="關閉"
          onClick={close}
        >
          ✕
        </button>
      </div>
      {children}
    </dialog>
  );
}
export function Pages({
  page,
  pages,
  set,
}: {
  page: number;
  pages: number;
  set: (page: number) => void;
}) {
  return pages > 1 ? (
    <div className="actions">
      <button disabled={page <= 1} onClick={() => set(page - 1)}>
        上一頁
      </button>
      <span>
        {page} / {pages}
      </span>
      <button disabled={page >= pages} onClick={() => set(page + 1)}>
        下一頁
      </button>
    </div>
  ) : null;
}
export const text = (data: FormData, name: string) =>
  String(data.get(name) ?? "").trim();
