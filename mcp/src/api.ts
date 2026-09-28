export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly body: unknown,
  ) {
    super(`API returned ${status}`);
  }
}
export class CoreApi {
  private base: string;
  constructor(
    base: string,
    private key: string,
  ) {
    this.base = base.endsWith("/") ? base : base + "/";
  }
  session() {
    return this.call("session/");
  }
  business() {
    return this.call("business/");
  }
  profile(args: { customer_ref: string }) {
    return this.call(
      `customer-profile/?customer_ref=${encodeURIComponent(args.customer_ref)}`,
    );
  }
  updateProfile(args: { customer_ref: string; display_name: string }) {
    return this.call("customer-profile/", args);
  }
  protected async call(
    path: string,
    body?: unknown,
    method?: string,
  ): Promise<unknown> {
    const response = await fetch(new URL(path, this.base), {
      method: method ?? (body === undefined ? "GET" : "POST"),
      signal: AbortSignal.timeout(15000),
      headers: {
        Authorization: `Bearer ${this.key}`,
        "Content-Type": "application/json",
      },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const payload = await response.json();
    if (!response.ok) throw new ApiError(response.status, payload);
    return payload;
  }
}

export class OrderApi extends CoreApi {
  shop() {
    return this.call("shop/");
  }
  menu() {
    return this.call("menu/");
  }
  orders(args: { customer_ref: string }) {
    return this.call(
      `orders/?customer_ref=${encodeURIComponent(args.customer_ref)}`,
    );
  }
  createOrderLink(args: Record<string, unknown>) {
    return this.call("order-drafts/", args);
  }
  cancel(id: string, args: { customer_ref: string }) {
    return this.call(`orders/${encodeURIComponent(id)}/cancel/`, args);
  }
}
