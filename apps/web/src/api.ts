import type { paths } from "../../../packages/contracts/generated/api";

export type Health =
  paths["/api/v1/system/health"]["get"]["responses"][200]["content"]["application/json"];
export type QuotePage =
  paths["/api/v1/fixtures/quotes"]["get"]["responses"][200]["content"]["application/json"];

export type DashboardPage =
  paths["/api/v1/dashboard/indicators"]["get"]["responses"][200]["content"]["application/json"];
export type IndicatorView = DashboardPage["data"][number];

export async function getHealth(): Promise<Health> {
  const response = await fetch("/api/v1/system/health", {
    credentials: "same-origin",
    cache: "no-store",
  });
  if (!response.ok) throw new Error("fixture API unavailable");
  return (await response.json()) as Health;
}

export async function getDashboardPage({
  category,
  cursor,
}: {
  category?: string;
  cursor?: string | null;
} = {}): Promise<DashboardPage> {
  const params = new URLSearchParams({ limit: "100" });
  if (category) params.set("category", category);
  if (cursor) params.set("cursor", cursor);
  const response = await fetch("/api/v1/dashboard/indicators?" + params, {
    credentials: "same-origin",
    cache: "no-store",
  });
  if (!response.ok) throw new Error("대시보드 API에 연결할 수 없습니다.");
  return (await response.json()) as DashboardPage;
}
