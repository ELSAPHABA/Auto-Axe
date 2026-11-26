import type { paths } from "../../../packages/contracts/generated/api";

export type Health =
  paths["/api/v1/system/health"]["get"]["responses"][200]["content"]["application/json"];
export type QuotePage =
  paths["/api/v1/fixtures/quotes"]["get"]["responses"][200]["content"]["application/json"];

export async function getHealth(): Promise<Health> {
  const response = await fetch("/api/v1/system/health", {
    credentials: "same-origin",
    cache: "no-store",
  });
  if (!response.ok) throw new Error("fixture API unavailable");
  return (await response.json()) as Health;
}
