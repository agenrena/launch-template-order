# Agenrena Order template

Read README.md and docs/product-decisions.md before changing scope.
This is a complete editable COPY of Business Core plus an ordering domain for one store.
Do not import sibling business_core/booking/repair at runtime or automatically sync their updates.
Do not modify /Users/fanchengkai/Documents/order (the source project) or the Runtime project from here.

- One store per App/database: Business is the store. There is no Location/branch model; a chain deploys one App per store. Do not reintroduce branches unless requested.
- The store is one Agenrena Business Profile. The App is its Agenrena Vendor; Vendor credentials come only from env (AGENRENA_VENDOR_ID/SECRET) and are never committed, logged, returned or given to the frontend/MCP. At most one grant (AgenrenaConnection singleton).
- Shared core lives in backend/core, common frontend pages and mcp/src/core.ts (see docs/core-copy.md).
- Ordering rules live in backend/ordering/services.py and hours.py. QR pages, the console and the Agent all call them; do not duplicate rules in views or the frontend.
- Tab = the bill (dine-in: the table is the credential and stays open for more rounds; takeout: one round, a daily pickup code, a phone). Round = one send, and the status machine: pending -> confirmed/rejected/cancelled, confirmed -> completed/rejected.
- Copy item names and prices onto RoundItem, and chosen options onto RoundItemChoice (group name, option name, price delta). Never read an order's money back through MenuItem or Option.
- Options are one level: store-wide OptionGroups (min_select/max_select) attached to dishes. Customers cannot pick unavailable options; staff can; everyone must satisfy min/max. No nested set-meal options.
- Pausing (OrderingSettings.orders_paused/paused_until) is checked first by accepting_orders and stops every entrance; submitted orders are unaffected.
- Keep scope minimal (see README "範圍"): device pairing, Firebase, special dates, menu version locks and reports are merchant customizations, not template features.
- Customers may not order sold-out dishes; staff may (amend). Staff amendments keep the status unless confirm is requested. Agents never set prices and never edit submitted orders.
- Agents prepare drafts only (create_order_link). A Tab, pickup number and kitchen ticket exist only after the customer confirms the link; confirmation is idempotent. Takeout only for Agents.
- Every Agent order read/cancel is scoped by the customer's CustomerIdentity; never look up an order by ID alone. customer_ref is Agenrena's bcr_ + 32 hex, trusted from the authorized Agent (not signed).
- The same accepting_orders check (modes, weekly hours, last-order minutes) guards every entrance, with a sentence to show the customer.
- Order progress for Agenrena customers goes through ordering.notifications.announce -> core notify_customer after commit; never let delivery fail or roll back an order. QR orders are anonymous and not messaged. Tests fake core.agenrena._request.
- Audit staff mutations and Agent actions; never log credentials, Vendor secrets, consent links, phone numbers or message text.
- Fresh-install schema only; initial migrations may be rewritten while there is no data.
- Validate with core.tests + ordering.tests on SQLite and PostgreSQL, makemigrations --check, frontend build, MCP tests, ./start.command --no-browser for startup changes and scripts/http_smoke.py for integration changes.
- No .env, credentials, production/customer data, virtualenvs or node_modules in deliveries.
- Local is the default: scripts/start.py (start.command / start.bat) runs everything on this computer with SQLite in data/, no Docker, no database server. DATABASE_URL switches to PostgreSQL for hosting (Compose/Runtime). Keep both working; use only features both databases support.
- LOCAL_APP (set by start.py) opens first-owner setup in the browser only from loopback and only while no active owner exists, and makes the console show the stdio MCP config. Hosted installs never set it.
- The store's Agent is brought by the merchant and runs on their side; locally it launches the MCP over stdio. Agenrena never calls into the App.
- Customer entrance (docs/publish.md): customers' phones must open the ordering pages, but locally the App listens on 127.0.0.1. When PUBLIC_PORT is set, start.py also serves config.public.public_only(app) on 127.0.0.1:PUBLIC_PORT for a tunnel the merchant chooses (Cloudflare Tunnel, Tailscale Funnel, a reverse proxy; never hard-code one). It passes only PUBLIC_PREFIXES (/, /assets/, /d/, /o/, /api/web/) and 404s the rest. Never add console, setup, agent-api or MCP paths to it: a tunnel connects from loopback, so the console's loopback trust would open to the internet. New customer pages/APIs go under those prefixes.
- Customer URLs (table QR codes, Agent confirmation links) come from views.public_base: ORDER_PUBLIC_BASE_URL, or this site when hosted. Locally without it, the console shows no QR codes and create_order_link refuses with not_published rather than sending a link customers cannot open.
- Styling: every colour, font, radius and density value lives in frontend/src/theme.css (identical to business_core's). To rebrand, change --brand (and --brand-fg if button text is unreadable); the console and the customer pages both follow it. style.css, customer/customer.css and components use only var(--…); `npm run check:style` (also part of build) rejects colour literals elsewhere. Status colours (--ok, --danger) stay independent of the brand. Dark mode follows the system via the media block in theme.css.
