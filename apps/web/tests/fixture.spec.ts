import { expect, test } from "@playwright/test";

test("fixture page works without a live provider", async ({ page }) => {
  await page.route("**/api/v1/system/health", (route) =>
    route.fulfill({
      json: {
        data: {
          status: "ok",
          environment: "fixture",
          live_enabled: false,
          external_mcp_enabled: false,
        },
        meta: {
          request_id: "e2e",
          schema_version: 1,
          source: "synthetic_fixture",
          permission: "fixture_only",
        },
      },
    }),
  );
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "개발 환경" })).toBeVisible();
  await expect(page.getByText("개발 API 연결됨 (합성 데이터)")).toBeVisible();
  await page.getByRole("link", { name: "개발 범위" }).click();
  await expect(
    page.getByRole("heading", { name: "Phase 0 개발 기반" }),
  ).toBeVisible();
});
