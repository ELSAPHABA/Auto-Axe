import { Link, NavLink, Route, Routes } from "react-router";
import { DashboardHome, IndicatorsPage, MarketDetailPage } from "./dashboard";
import { useAuthorizedStream, useAuthorizedSnapshot } from "./authorized-live";

const NAV = [
  { to: "/", label: "시장 대시보드", icon: "◫" },
  { to: "/indicators", label: "전체 지표", icon: "▥" },
  { to: "/groups", label: "주식 그룹", icon: "◈" },
  { to: "/workflows", label: "워크플로", icon: "⌘" },
  { to: "/strategies/friday-close", label: "금요일 전략", icon: "◷" },
  { to: "/settings", label: "설정", icon: "⚙" },
];

function Placeholder({ name }: { name: string }) {
  return (
    <div className="dashboard-view">
      <div className="page-heading">
        <div>
          <p className="eyebrow">PLANNED / FUTURE PHASE</p>
          <h1>{name}</h1>
          <p>해당 기능은 현재 개발 단계에서 활성화되지 않았습니다.</p>
        </div>
      </div>
      <div className="panel panel-empty">
        주문과 자동매매는 비활성 상태입니다. 실제 금융 데이터를 표시하지
        않습니다.
      </div>
    </div>
  );
}

function Shell() {
  const stream = useAuthorizedStream();
  const market = useAuthorizedSnapshot();
  return (
    <div className="app-shell">
      <aside className="sidebar" aria-label="주요 메뉴">
        <Link className="brand" to="/">
          <span className="brand-symbol">A</span>
          <span>
            AUTO<span className="brand-accent">AXE</span>
            <small>MARKET INTELLIGENCE</small>
          </span>
        </Link>
        <p className="nav-heading">WORKSPACE</p>
        <nav className="side-nav">
          {NAV.map(({ to, label, icon }) => (
            <NavLink
              key={to}
              end={to === "/"}
              to={to}
              className={({ isActive }) =>
                "nav-link " + (isActive ? "nav-active" : "")
              }
            >
              <span className="nav-icon" aria-hidden="true">
                {icon}
              </span>
              {label}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-footer">
          <span className="footer-label">DEVELOPMENT ENVIRONMENT</span>
          <strong>
            <span className="status-dot" />{" "}
            {market ? "승인된 시장 데이터" : "Fixture Only"}
          </strong>
          <p>외부 MCP: OFF · LIVE: OFF</p>
          <Link to="/about">개발 범위 확인</Link>
        </div>
      </aside>
      <div className="app-body">
        <header className="topbar">
          <span>시장 데이터 관제 / Phase 2</span>
          <div>
            <span className="topbar-pill">
              {market
                ? stream === "ready"
                  ? "MARKET / CONNECTED"
                  : "MARKET / REST"
                : "DEMO / SYNTHETIC"}
            </span>
            {!market && <a href="/api/v1/auth/login">로그인</a>}
            <span className="topbar-avatar" aria-label="개발 환경">
              DEV
            </span>
          </div>
        </header>
        <main id="main-content">
          <Routes>
            <Route path="/" element={<DashboardHome />} />
            <Route path="/indicators" element={<IndicatorsPage />} />
            <Route
              path="/market/:instrumentId"
              element={<MarketDetailPage />}
            />
            <Route path="/groups" element={<Placeholder name="주식 그룹" />} />
            <Route
              path="/workflows"
              element={<Placeholder name="Workflow" />}
            />
            <Route
              path="/strategies/friday-close"
              element={<Placeholder name="금요일 종가 전략" />}
            />
            <Route
              path="/settings"
              element={<Placeholder name="설정 및 권한" />}
            />
            <Route
              path="/about"
              element={
                <div className="dashboard-view">
                  <div className="page-heading">
                    <div>
                      <p className="eyebrow">ABOUT / DEVELOPMENT</p>
                      <h1>Phase 2 개발 기반</h1>
                      <p>실제 시장 공급자와 주문 기능은 차단되어 있습니다.</p>
                    </div>
                  </div>
                  <div className="panel">
                    현재 화면은 합성 데이터 및 소스 등록 상태만 제공합니다.
                    공급자 이용권·본인 인증·실거래 연결은 추가 검증 대상입니다.
                  </div>
                </div>
              }
            />
            <Route
              path="*"
              element={
                <div className="dashboard-view">
                  <h1>페이지 없음</h1>
                  <Link to="/">대시보드로 이동</Link>
                </div>
              }
            />
          </Routes>
        </main>
        <footer className="site-footer">영리적 목적의 사용을 금지합니다</footer>
      </div>
    </div>
  );
}

export function App() {
  return <Shell />;
}
