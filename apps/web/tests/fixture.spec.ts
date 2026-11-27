import { expect, test } from "@playwright/test";

test("Phase 2 dashboard remains clearly synthetic, mobile and accessible", async ({
  page,
}) => {
  await page.route("**/api/v1/system/health", (route) =>
    route.fulfill({
      json: {
        data: {
          status: "ok",
          environment: "fixture",
          live_enabled: false,
          external_mcp_enabled: false,
        },
        meta: { request_id: "e2e", schema_version: 1 },
      },
    }),
  );
  await page.route("**/api/v1/dashboard/stream", (route) =>
    route.fulfill({
      status: 200,
      contentType: "text/event-stream",
      body: 'event: ready\ndata: {"schema_version":1,"mode":"fixture","aggregate":"dashboard","version":0}\n\n',
    }),
  );
  await page.route("**/api/v1/auth/session", (route) =>
    route.fulfill({
      status: 401,
      json: { error: { code: "UNAUTHENTICATED" } },
    }),
  );
  await page.route("**/api/v1/dashboard/indicators?**", (route) =>
    route.fulfill({
      json: {
        data: [
          {
            indicator_id: "FIXTURE_PRICE",
            label: "합성 가격",
            category: "market",
            source_id: "fixture",
            unit: "USD",
            cadence: "trade",
            source_note: "합성",
            value: "123.45",
            quality: "synthetic_fixture",
            source_event_at: null,
            observed_at: null,
            available_at: null,
            permission: "fixture_only",
          },
          {
            indicator_id: "BITCOIN_BINANCE_SPOT",
            label: "Bitcoin Spot",
            category: "market",
            source_id: "binance_spot",
            unit: "USDT/BTC",
            cadence: "trade",
            source_note: "",
            value: null,
            quality: "permission_required",
            source_event_at: null,
            observed_at: null,
            available_at: null,
            permission: "unverified",
          },
        ],
        meta: {
          request_id: "e2e",
          environment: "fixture",
          schema_version: 1,
          version: 0,
          as_of: "2026-11-27T00:00:00Z",
          live_enabled: false,
          external_mcp_enabled: false,
          next_cursor: null,
        },
      },
    }),
  );
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "시장 대시보드" }),
  ).toBeVisible();
  await expect(
    page.locator(".indicator-value", { hasText: "123.45" }),
  ).toBeVisible();
  await expect(page.getByText("외부 MCP: OFF · LIVE: OFF")).toBeVisible();
  await expect(page.getByText("수집 권한 미확인")).toBeVisible();
  await page.getByRole("link", { name: "전체 지표", exact: true }).click();
  await expect(page.getByRole("heading", { name: "지표 탐색" })).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByRole("heading", { name: "지표 탐색" })).toBeVisible();
  const extent = await page.evaluate(() => ({
    scroll: document.documentElement.scrollWidth,
    screen: document.documentElement.clientWidth,
  }));
  expect(extent.scroll).toBeLessThanOrEqual(extent.screen);
});
