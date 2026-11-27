import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { getCorporateGuidance, getExpiryCalendar, getSeibroTop50 } from "./api";
import { useAuthorizedSession } from "./authorized-live";

export function SeibroPanel() {
  const session = useAuthorizedSession();
  const allowed = session.data === true && !session.isError;
  const [country, setCountry] = useState("US");
  const [period, setPeriod] = useState("1");
  const [basis, setBasis] = useState("4");
  const result = useQuery({
    queryKey: ["authorized", "seibro", country, period, basis],
    queryFn: () => getSeibroTop50(country, period, basis),
    enabled: allowed,
    retry: false,
    refetchInterval: 60_000,
  });
  const snapshot = result.data?.data;
  return (
    <section className="panel" aria-label="해외주식 결제 TOP50">
      <p className="eyebrow">SEIBRO / REVIEWED SETTLEMENTS</p>
      <h2>해외주식 결제 TOP50</h2>
      <p className="subline">
        검수된 결제 통계 · USD · 선택한 기간 및 정렬 기준 · 전체 시장 및 실시간
        주문 통계가 아님
      </p>
      <label>
        국가{" "}
        <select value={country} onChange={(e) => setCountry(e.target.value)}>
          {[
            ["US", "미국"],
            ["ALL", "전체"],
            ["HK", "홍콩"],
            ["CN", "중국"],
            ["JP", "일본"],
            ["VN", "베트남"],
          ].map(([code, name]) => (
            <option key={code} value={code}>
              {name}
            </option>
          ))}
        </select>
      </label>
      <label>
        기간{" "}
        <select value={period} onChange={(e) => setPeriod(e.target.value)}>
          {[
            ["1", "1주"],
            ["2", "1개월"],
            ["3", "3개월"],
            ["4", "6개월"],
            ["5", "1년"],
          ].map(([code, name]) => (
            <option key={code} value={code}>
              {name}
            </option>
          ))}
        </select>
      </label>
      <label>
        순위 기준{" "}
        <select value={basis} onChange={(e) => setBasis(e.target.value)}>
          {[
            ["1", "매수"],
            ["2", "매도"],
            ["3", "합계"],
            ["4", "순매수"],
          ].map(([code, name]) => (
            <option key={code} value={code}>
              {name}
            </option>
          ))}
        </select>
      </label>
      {!allowed ? (
        <p className="panel-empty">인증된 조회 권한이 필요합니다.</p>
      ) : result.isError ? (
        <p role="status" className="panel-empty">
          SEIBro 조회 권한 또는 연결 확인 필요
        </p>
      ) : result.isPending ? (
        <p className="panel-empty">검수된 결제 자료 조회 중…</p>
      ) : !snapshot ? (
        <p className="panel-empty">검수된 결제 자료가 없습니다.</p>
      ) : (
        <>
          <p className="subline">
            기준일 {snapshot.as_of_date_kst} · 기간{" "}
            {snapshot.period_start ?? "미확인"} ~{" "}
            {snapshot.period_end ?? "미확인"} · {snapshot.row_count}개 · 수정{" "}
            {snapshot.revision} · 자동 주문 사용 금지
          </p>
          <p className="subline">
            {snapshot.capture_mode === "browser_capture"
              ? "브라우저 수집"
              : "수동 등록"}
            {snapshot.amount_coverage === "buy_only"
              ? " · 매수 금액만 관측"
              : ""}
            {snapshot.amount_coverage === "sell_only"
              ? " · 매도 금액만 관측"
              : ""}
            {snapshot.derived_amount
              ? ` · 산술 계산: ${snapshot.derived_amount}`
              : ""}
            {" · —는 관측되지 않은 금액"}
          </p>
          <div className="official-events-table-wrap">
            <table className="official-events-table">
              <thead>
                <tr>
                  {[
                    "순위",
                    "종목",
                    "ISIN",
                    "매수 결제",
                    "매도 결제",
                    "순매수 결제",
                    "합계",
                  ].map((text) => (
                    <th key={text} scope="col">
                      {text}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {snapshot.rows.map((row) => (
                  <tr key={row.isin}>
                    <td>{row.rank}</td>
                    <td>{row.security_name}</td>
                    <td>{row.isin}</td>
                    <td>{row.buy_settlement_usd ?? "—"}</td>
                    <td>{row.sell_settlement_usd ?? "—"}</td>
                    <td>{row.net_buy_settlement_usd ?? "—"}</td>
                    <td>{row.gross_settlement_usd ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  );
}

export function CorporateGuidancePanel() {
  const session = useAuthorizedSession();
  const allowed = session.data === true && !session.isError;
  const result = useQuery({
    queryKey: ["authorized", "guidance"],
    queryFn: getCorporateGuidance,
    enabled: allowed,
    retry: false,
    refetchInterval: 60_000,
  });
  return (
    <section className="panel" aria-label="기업 실적 가이던스">
      <p className="eyebrow">ISSUER OUTLOOK / SEC EDGAR</p>
      <h2>기업 실적 가이던스</h2>
      <p className="subline">
        기업 자체 전망 · GAAP / 조정 지표 · 실적 및 애널리스트 컨센서스와 구분
      </p>
      {!allowed ? (
        <p className="panel-empty">인증된 조회 권한이 필요합니다.</p>
      ) : result.isError ? (
        <p className="panel-empty" role="status">
          가이던스 연결 또는 권한 확인 필요
        </p>
      ) : result.isPending ? (
        <p className="panel-empty">검수된 공시 조회 중…</p>
      ) : !result.data.data.length ? (
        <p className="panel-empty">검수된 기업 전망이 없습니다.</p>
      ) : (
        <div className="official-events-table-wrap">
          <table className="official-events-table">
            <thead>
              <tr>
                {[
                  "CIK",
                  "회계기간",
                  "지표",
                  "회계 기준",
                  "전망 범위",
                  "최초 확인",
                  "원본",
                ].map((text) => (
                  <th key={text} scope="col">
                    {text}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {result.data.data.map((row) => (
                <tr
                  key={[
                    row.cik,
                    row.accession,
                    row.fiscal_period,
                    row.metric,
                    row.basis,
                  ].join(":")}
                >
                  <td>{row.cik}</td>
                  <td>{row.fiscal_period}</td>
                  <td>{row.metric}</td>
                  <td>{row.basis}</td>
                  <td>
                    {row.low} ~ {row.high} {row.unit}
                  </td>
                  <td>{row.first_seen_at}</td>
                  <td>
                    <a
                      href={row.source_url}
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      SEC 원문
                    </a>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

export function ExpiryCalendarPanel() {
  const [date, setDate] = useState("");
  const session = useAuthorizedSession();
  const allowed = session.data === true && !session.isError;
  const result = useQuery({
    queryKey: ["authorized", "expiry", date],
    queryFn: () => getExpiryCalendar(date),
    enabled: allowed,
    retry: false,
    refetchInterval: 60_000,
  });
  return (
    <section className="panel" aria-label="파생상품 만기 일정">
      <p className="eyebrow">EXPIRY / SESSION EVIDENCE</p>
      <h2>파생상품 만기 일정</h2>
      <p className="subline">
        기본 일정은 분기 셋째 금요일을 미국 주식시장 휴장일에 맞춰 이전 거래일로
        보정한 예상치입니다. 계약별 확정 근거는 별도로 표시합니다.
      </p>
      <label>
        조회 후보일{" "}
        <input
          type="date"
          value={
            date ||
            (allowed ? (result.data?.projection?.nominal_date ?? "") : "")
          }
          onChange={(event) => setDate(event.target.value)}
        />
      </label>
      <button type="button" onClick={() => setDate("")}>
        다음 만기 자동 선택
      </button>
      {!allowed ? (
        <p className="panel-empty">인증된 조회 권한이 필요합니다.</p>
      ) : result.isError ? (
        <p className="panel-empty" role="status">
          만기 일정 연결 또는 권한 확인 필요
        </p>
      ) : result.isPending ? (
        <p className="panel-empty">예상 만기 및 공식 근거 조회 중…</p>
      ) : (
        <>
          {result.data.projection && (
            <p className="subline">
              규칙 기반 예상 만기:{" "}
              {result.data.projection.estimated_date ?? "일정 미확인"}
              {" · 달력 DTE: "}
              {result.data.projection.calendar_days ?? "—"}
              {" · 주식시장 거래일 DTE: "}
              {result.data.projection.equity_session_days ?? "—"}
              {" · 상품별 실제 만기와 다를 수 있음"}
              {result.data.projection.nominal_date !==
                result.data.projection.estimated_date &&
              result.data.projection.estimated_date
                ? " · 휴장일 보정"
                : ""}
            </p>
          )}
          <div className="official-events-table-wrap">
            <table className="official-events-table">
              <thead>
                <tr>
                  {[
                    "확인 세션",
                    "판정",
                    "제품군 근거",
                    "달력 DTE",
                    "거래 세션 DTE",
                  ].map((text) => (
                    <th key={text} scope="col">
                      {text}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {result.data.sessions.map((row, index) => (
                  <tr key={row.session_date ?? index}>
                    <td>{row.session_date ?? "미확정"}</td>
                    <td>
                      {row.event_type}
                      {row.conflicted ? " · 근거 충돌" : ""}
                    </td>
                    <td>
                      {Object.entries(row.family_status).map(
                        ([family, status]) => (
                          <div key={family}>
                            {family}: {status}
                          </div>
                        ),
                      )}
                    </td>
                    <td>{row.calendar_days_to_session ?? "—"}</td>
                    <td>{row.trading_days_to_session ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {result.data.evidence.length > 0 && (
            <div className="official-events-table-wrap">
              <table className="official-events-table">
                <thead>
                  <tr>
                    {[
                      "제품군",
                      "계약",
                      "명목 만기",
                      "최종 거래",
                      "처리",
                      "결제",
                      "달력일 DTE",
                      "거래일 DTE",
                      "공식 원본",
                    ].map((text) => (
                      <th key={text} scope="col">
                        {text}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {result.data.evidence.map(
                    ({
                      claim,
                      revision,
                      calendar_days_to_expiry,
                      trading_days_to_expiry,
                    }) => (
                      <tr key={claim.evidence_key + ":" + revision}>
                        <td>{claim.family}</td>
                        <td>{claim.contract_ref ?? "—"}</td>
                        <td>{claim.nominal_expiry_date ?? "—"}</td>
                        <td>
                          {claim.last_trade_at ?? claim.last_trade_date ?? "—"}
                        </td>
                        <td>
                          {claim.processing_at ?? claim.processing_date ?? "—"}
                        </td>
                        <td>
                          {claim.settlement_at ?? claim.settlement_date ?? "—"}
                        </td>
                        <td>{calendar_days_to_expiry ?? "—"}</td>
                        <td>{trading_days_to_expiry ?? "—"}</td>
                        <td>
                          <a
                            href={claim.source_url}
                            target="_blank"
                            rel="noopener noreferrer"
                          >
                            {claim.source_id}
                          </a>
                        </td>
                      </tr>
                    ),
                  )}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </section>
  );
}
