import { useCallback } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { BarChart3, ListChecks } from 'lucide-react';
import ReportOperationSummary from '../components/report/ReportOperationSummary.jsx';
import ReportTimeline from '../components/report/ReportTimeline.jsx';
import usePolling from '../hooks/usePolling.js';
import { fetchReport } from '../api/statusApi.js';

export default function IntegratedReportPage() {
  // 저장된 보고서 화면에서 "불러오기"를 누른 뒤 돌아오면
  // navigate state에 restoredReportTitle이 들어오고, 화면 상단에 안내 문구로 보여준다.
  const location = useLocation();

  // 기존 통합 보고서 화면은 백엔드 live report를 1초마다 폴링한다.
  // 저장된 보고서를 복원하면 백엔드 state["report"]가 바뀌므로 이 폴링 결과도 자동으로 갱신된다.
  const fetcher = useCallback(() => fetchReport(), []);
  const { data, error, loading } = usePolling(fetcher, 1000);

  if (loading) return <div className="card">보고서를 불러오는 중입니다.</div>;
  if (error) return <div className="card error-box">보고서 조회 실패: {error.message}</div>;

  // react-router의 navigate('/report', { state })로 전달된 일회성 안내 값이다.
  const restoredTitle = location.state?.restoredReportTitle;

  return (
    <div className="page-stack">
      <div className="page-heading">
        <div>
          <p className="eyebrow">Integrated Report</p>
          <h2>통합 보고서 화면</h2>
          <p>감지부터 도킹 완료까지 status_event 기반 5단계 흐름을 기록합니다.</p>
        </div>
        <div className="button-row">
          <Link className="secondary-button link-button" to="/analytics">
            <BarChart3 size={16} />
            보고서 분석
          </Link>
          <Link className="secondary-button link-button" to="/saved-reports">
            <ListChecks size={16} />
            저장된 보고서
          </Link>
        </div>
      </div>

      {restoredTitle && (
        <div className="card">
          <p className="success-text">불러온 보고서: {restoredTitle}</p>
        </div>
      )}

      <article className="card">
        <div className="card-title-row">
          <div>
            <h2>단계별 대응 타임라인</h2>
            <p className="helper-text">감지부터 도킹 완료까지 5단계 흐름을 시간 순서로 추적합니다.</p>
          </div>
        </div>
        <ReportTimeline report={data} />
      </article>

      <article className="card">
        <div className="card-title-row">
          <div>
            <h2>동작 흐름 진단 보고서</h2>
            <p className="helper-text">각 동작이 기록됐는지, 다음 동작까지 얼마나 걸렸는지, 전체 흐름이 정상인지 확인합니다.</p>
          </div>
        </div>
        <ReportOperationSummary report={data} mode="live" />
      </article>
    </div>
  );
}
