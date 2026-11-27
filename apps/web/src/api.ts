import type { paths } from "../../../packages/contracts/generated/api";

export type Health =
  paths["/api/v1/system/health"]["get"]["responses"][200]["content"]["application/json"];
export type QuotePage =
  paths["/api/v1/fixtures/quotes"]["get"]["responses"][200]["content"]["application/json"];

export type DashboardPage =
  paths["/api/v1/dashboard/indicators"]["get"]["responses"][200]["content"]["application/json"];
export type IndicatorView = DashboardPage["data"][number];
export type OfficialEventsPage =
  paths["/api/v1/dashboard/official-events"]["get"]["responses"][200]["content"]["application/json"];
export type ApprovedMarketPage =
  paths["/api/v1/dashboard/authorized/market/{series_id}"]["get"]["responses"][200]["content"]["application/json"];
export type AuthorizedSnapshot =
  paths["/api/v1/dashboard/authorized/snapshot"]["get"]["responses"][200]["content"]["application/json"];
export type SnapshotPoint = AuthorizedSnapshot["data"][number];
export type GuidancePage =
  paths["/api/v1/dashboard/corporate-guidance"]["get"]["responses"][200]["content"]["application/json"];
export type ExpiryPage =
  paths["/api/v1/dashboard/expiry-calendar"]["get"]["responses"][200]["content"]["application/json"];
export type SeibroPage =
  paths["/api/v1/dashboard/authorized/seibro"]["get"]["responses"][200]["content"]["application/json"];

export async function getSeibroTop50(
  country: string,
  period: string,
  basis: string,
): Promise<SeibroPage> {
  const params = new URLSearchParams({
    country_code: country,
    period_code: period,
    rank_basis: basis,
  });
  const response = await fetch(
    "/api/v1/dashboard/authorized/seibro?" + params,
    { credentials: "same-origin", cache: "no-store" },
  );
  if (!response.ok) throw new Error("SEIBro 결제 자료 조회 실패");
  return (await response.json()) as SeibroPage;
}

export async function getCorporateGuidance(): Promise<GuidancePage> {
  const response = await fetch(
    "/api/v1/dashboard/corporate-guidance?limit=30",
    {
      credentials: "same-origin",
      cache: "no-store",
    },
  );
  if (!response.ok) throw new Error("기업 가이던스 조회 실패");
  const result = (await response.json()) as GuidancePage;
  if (!Array.isArray(result.data)) throw new Error("가이던스 계약 불일치");
  return result;
}

export async function getExpiryCalendar(date: string): Promise<ExpiryPage> {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) throw new Error("잘못된 조회일");
  const response = await fetch(
    "/api/v1/dashboard/expiry-calendar?candidate_date=" +
      encodeURIComponent(date),
    {
      credentials: "same-origin",
      cache: "no-store",
    },
  );
  if (!response.ok) throw new Error("만기 일정 조회 실패");
  const result = (await response.json()) as ExpiryPage;
  if (!Array.isArray(result.sessions) || !Array.isArray(result.evidence))
    throw new Error("만기 일정 계약 불일치");
  return result;
}

export async function getAuthorizedSnapshot(): Promise<AuthorizedSnapshot> {
  const response = await fetch("/api/v1/dashboard/authorized/snapshot", {
    credentials: "same-origin",
    cache: "no-store",
  });
  if (!response.ok) throw new Error("승인된 시장 데이터 조회 실패");
  const data = (await response.json()) as AuthorizedSnapshot;
  if (
    data.meta?.mode !== "market_read" ||
    data.meta.schema_version !== 1 ||
    !Array.isArray(data.data) ||
    !data.meta.versions ||
    typeof data.meta.versions !== "object" ||
    Array.isArray(data.meta.versions) ||
    Object.values(data.meta.versions).some(
      (version) => !Number.isSafeInteger(version) || version < 0,
    )
  )
    throw new Error("시장 데이터 계약 불일치");
  return data;
}

export async function getApprovedMarketSeries(
  seriesId: string,
): Promise<ApprovedMarketPage> {
  if (!/^[A-Za-z0-9_:.-]{1,128}$/.test(seriesId))
    throw new Error("잘못된 지표 ID");
  const response = await fetch(
    "/api/v1/dashboard/authorized/market/" +
      encodeURIComponent(seriesId) +
      "?limit=200",
    { credentials: "same-origin", cache: "no-store" },
  );
  if (!response.ok)
    throw new Error("해당 시계열의 제공 권한 또는 연결을 확인할 수 없습니다.");
  return (await response.json()) as ApprovedMarketPage;
}

export async function hasAuthorizedSession(): Promise<boolean> {
  const response = await fetch("/api/v1/auth/session", {
    credentials: "same-origin",
    cache: "no-store",
  });
  if (
    response.status === 401 ||
    response.status === 403 ||
    response.status === 503
  ) {
    return false;
  }
  if (!response.ok) return false;
  const payload: { meta?: { authenticated?: boolean } } = await response.json();
  return payload.meta?.authenticated === true;
}

export async function getOfficialEvents(): Promise<OfficialEventsPage> {
  const response = await fetch("/api/v1/dashboard/official-events?limit=30", {
    credentials: "same-origin",
    cache: "no-store",
  });
  if (!response.ok)
    throw new Error("공식 데이터 권한 또는 연결을 확인할 수 없습니다.");
  return (await response.json()) as OfficialEventsPage;
}

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
