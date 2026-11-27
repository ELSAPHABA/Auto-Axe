import "@testing-library/jest-dom/vitest";
import {
  cleanup,
  render,
  screen,
  fireEvent,
  within,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router";
import { afterEach, expect, test, vi } from "vitest";
import { App } from "./App";

const fake = [
  {
    indicator_id: "PENTAGON_PIZZA_PIZZINT",
    label: "DOUGHCON",
    category: "sentiment",
    source_id: "pizzint",
    unit: "level",
    cadence: "5m",
    source_note: "참고용",
    value: null,
    quality: "permission_required",
    source_event_at: null,
    observed_at: null,
    available_at: null,
    permission: "unverified",
  },
  {
    indicator_id: "FIXTURE_PRICE",
    label: "합성 가격",
    category: "market",
    source_id: "fixture",
    unit: "USD",
    cadence: "trade",
    source_note: "검증용",
    value: "123.45",
    quality: "synthetic_fixture",
    source_event_at: null,
    observed_at: null,
    available_at: null,
    permission: "fixture_only",
  },
  {
    indicator_id: "BITCOIN_BINANCE_SPOT",
    label: "BTCUSDT",
    category: "market",
    source_id: "binance_spot",
    unit: "USDT/BTC",
    cadence: "trade",
    source_note: "권한 필요",
    value: null,
    quality: "permission_required",
    source_event_at: null,
    observed_at: null,
    available_at: null,
    permission: "unverified",
  },
  {
    indicator_id: "BINANCE_GLOBAL_ACCOUNTS_BTCUSDT",
    label: "롱숏 전체 계정",
    category: "market",
    source_id: "binance_futures",
    unit: "ratio",
    cadence: "5m",
    source_note: "5분",
    value: null,
    quality: "permission_required",
    source_event_at: null,
    observed_at: null,
    available_at: null,
    permission: "unverified",
  },
];

function setup(failure = false, authorized = false) {
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string) =>
      failure
        ? Promise.reject(new Error("network down"))
        : Promise.resolve({
            ok: true,
            json: async () =>
              String(url).includes("dashboard/authorized/snapshot")
                ? {
                    data: [
                      {
                        series_id: "BITCOIN_BINANCE_SPOT",
                        source_id: "binance_spot",
                        unit: "USDT/BTC",
                        value: "98765",
                        quality: "valid",
                        version: 1,
                        source_event_at: "2026-11-27T02:00:00Z",
                        received_at: "2026-11-27T02:00:00Z",
                        collector_status: "healthy",
                        collector_checked_at: null,
                      },
                      {
                        series_id: "BINANCE_GLOBAL_ACCOUNTS_BTCUSDT",
                        source_id: "binance_futures",
                        unit: "ratio",
                        value: "1.5",
                        quality: "valid",
                        version: 2,
                        source_event_at: "2026-11-27T02:00:00Z",
                        received_at: "2026-11-27T02:00:00Z",
                        collector_status: "healthy",
                        collector_checked_at: null,
                      },
                    ],
                    meta: {
                      mode: "market_read",
                      versions: {
                        BITCOIN_BINANCE_SPOT: 1,
                        BINANCE_GLOBAL_ACCOUNTS_BTCUSDT: 2,
                      },
                      as_of: "2026-11-27T02:00:00Z",
                      request_id: "test",
                      schema_version: 1,
                    },
                  }
                : String(url).includes("dashboard/official-events")
                  ? {
                      data: [
                        {
                          event_key: "US_CPI:2026-10",
                          source_id: "bls",
                          revision: 2,
                          actual: "321.75",
                          forecast: null,
                          previous: null,
                          unit: "index",
                          scheduled_at: null,
                          released_at: null,
                          first_seen_at: "2026-11-27T02:00:00Z",
                          available_at: "2026-11-27T02:00:00Z",
                          source_url: "https://www.bls.gov/developers/",
                        },
                      ],
                      meta: {
                        request_id: "test",
                        as_of: "2026-11-27T02:00:00Z",
                        source_scope: null,
                        available_count: 1,
                      },
                    }
                  : String(url).includes(
                        "/dashboard/authorized/market/PENTAGON_PIZZA_PIZZINT",
                      )
                    ? {
                        data: [
                          {
                            value: "5",
                            source_event_at: "2026-11-27T04:00:00Z",
                          },
                        ],
                        meta: {
                          unit: "level",
                          collector_status: "healthy",
                          collector_checked_at: "2026-11-27T04:01:00Z",
                          as_of: "2026-11-27T04:01:10Z",
                        },
                      }
                    : String(url).includes("/auth/session")
                      ? { meta: { authenticated: authorized } }
                      : String(url).includes("dashboard/indicators")
                        ? {
                            data: fake,
                            meta: {
                              next_cursor: null,
                              environment: "fixture",
                              schema_version: 1,
                              as_of: "2026-11-27T00:00:00Z",
                              version: 0,
                              request_id: "test",
                              live_enabled: false,
                              external_mcp_enabled: false,
                            },
                          }
                        : {
                            data: {
                              status: "ok",
                              environment: "fixture",
                              live_enabled: false,
                              external_mcp_enabled: false,
                            },
                            meta: { request_id: "test" },
                          },
          }),
    ),
  );
  render(
    <QueryClientProvider
      client={
        new QueryClient({
          defaultOptions: {
            queries: { retry: false },
          },
        })
      }
    >
      <MemoryRouter>
        <App />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

test("Phase 2 home marks synthetic and missing sources accurately", async () => {
  setup();
  expect(screen.getByText("영리적 목적의 사용을 금지합니다")).toBeVisible();
  expect(
    screen.queryByText(/개인.교육용 모드|연구\/개발 환경 · 데이터 이용 권한/),
  ).not.toBeInTheDocument();
  expect(
    await screen.findByRole("heading", { name: "시장 대시보드" }),
  ).toBeVisible();
  expect(await screen.findByText("123.45")).toBeVisible();
  const pizza = screen.getByRole("article", { name: "DOUGHCON" });
  expect(within(pizza).queryByText("5")).not.toBeInTheDocument();
  expect(screen.getAllByText("수집 권한 미확인").length).toBeGreaterThan(0);
  expect(screen.getByText("자동 거래")).toBeVisible();
  const box = screen.getByRole("region", { name: "롱숏 비율" });
  fireEvent.click(within(box).getByRole("checkbox"));
  expect(within(box).getByText("확인된 비율 없음")).toBeVisible();
  fireEvent.click(
    within(box).getByRole("button", { name: "Taker 매수·매도 거래량" }),
  );
  expect(within(box).getByText(/보유 포지션 비율이 아닙니다/)).toBeVisible();
});

test("fixture dashboard backend failure never displays a live price", async () => {
  setup(true);
  expect(await screen.findByText(/지표를 불러오지 못했습니다/)).toBeVisible();
  expect(screen.queryByText("123.45")).not.toBeInTheDocument();
});

test("only authorized, permission-gated official events appear separately", async () => {
  setup(false, true);
  expect(
    await screen.findByText("US_CPI:2026-10", {}, { timeout: 5000 }),
  ).toBeVisible();
  expect(screen.getByText("321.75 index")).toBeVisible();
  expect(screen.getByText("합성 검증 값")).toBeVisible();
  expect(await screen.findByText("98765", {}, { timeout: 5000 })).toBeVisible();
  const ratios = screen.getByRole("region", { name: "롱숏 비율" });
  const toggle = within(ratios).getByRole("checkbox") as HTMLInputElement;
  if (!toggle.checked) fireEvent.click(toggle);
  fireEvent.click(within(ratios).getByRole("button", { name: "전체 계정" }));
  expect(await within(ratios).findByText("LONG 60.00%")).toBeVisible();
  expect(within(ratios).getByText("SHORT 40.00%")).toBeVisible();
});

test("DOUGHCON only shows an authenticated stored level and API timestamp", async () => {
  setup(false, true);
  const card = await screen.findByRole("article", { name: "DOUGHCON" });
  expect(await within(card).findByText("5")).toBeVisible();
  expect(within(card).getByText("최근 저장값 · 참고용")).toBeVisible();
  expect(within(card).getByText(/API 시각.*2026-11-27/)).toBeVisible();
});
