import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router";
import { afterEach, expect, test, vi } from "vitest";
import { App } from "./App";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

test("fixture API and disabled LIVE state", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        data: {
          status: "ok",
          environment: "fixture",
          live_enabled: false,
          external_mcp_enabled: false,
        },
        meta: {
          request_id: "test",
          schema_version: 1,
          source: "synthetic_fixture",
          permission: "fixture_only",
        },
      }),
    }),
  );
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <App />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  expect(
    await screen.findByText("개발 API 연결됨 (합성 데이터)"),
  ).toBeVisible();
  expect(screen.getByText("LIVE: OFF · 외부 MCP: OFF")).toBeVisible();
});

test("API failure does not display a healthy state", async () => {
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <App />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  expect(await screen.findByText("연결 불가")).toBeVisible();
});
