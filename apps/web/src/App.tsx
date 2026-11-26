import { useQuery } from "@tanstack/react-query";
import { Link, Route, Routes } from "react-router";
import { getHealth } from "./api";

export function FixtureHome() {
  const health = useQuery({
    queryKey: ["fixture", "health"],
    queryFn: getHealth,
    retry: false,
  });
  return (
    <main className="mx-auto max-w-3xl px-5 py-12">
      <p className="text-sm text-slate-400">AUTO-AXE / PHASE 0</p>
      <h1 className="my-4 text-3xl font-semibold">개발 환경</h1>
      <p>합성 데이터 전용. 실제 시장 데이터와 주문 기능은 비활성 상태입니다.</p>
      <section
        className="mt-6 rounded-lg border border-slate-700 bg-slate-900 p-5"
        aria-label="시스템 상태"
      >
        <h2 className="text-lg font-medium">API 상태</h2>
        <p role="status" className="mt-3">
          {health.isPending
            ? "확인 중"
            : health.isError
              ? "연결 불가"
              : health.data.data.environment === "fixture" &&
                  !health.data.data.live_enabled
                ? "개발 API 연결됨 (합성 데이터)"
                : "알 수 없는 환경"}
        </p>
        <p className="mt-2 text-sm text-slate-400">LIVE: OFF · 외부 MCP: OFF</p>
      </section>
      <Link className="mt-4 inline-block underline" to="/about">
        개발 범위
      </Link>
    </main>
  );
}

export function App() {
  return (
    <Routes>
      <Route path="/" element={<FixtureHome />} />
      <Route
        path="/about"
        element={
          <main className="p-8">
            <h1>Phase 0 개발 기반</h1>
            <p>운영 대시보드는 Phase 2에서 구현합니다.</p>
            <Link to="/">돌아가기</Link>
          </main>
        }
      />
      <Route
        path="*"
        element={
          <main className="p-8">
            <h1>페이지 없음</h1>
            <Link to="/">돌아가기</Link>
          </main>
        }
      />
    </Routes>
  );
}
