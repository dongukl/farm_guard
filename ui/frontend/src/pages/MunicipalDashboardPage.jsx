import { useCallback } from 'react';
import WebcamStatusCard from '../components/dashboard/WebcamStatusCard.jsx';
import AmrStatusCard from '../components/dashboard/AmrStatusCard.jsx';
import usePolling from '../hooks/usePolling.js';
import { fetchSystemStatus, resetScenario } from '../api/statusApi.js';

export default function MunicipalDashboardPage() {
  // 대시보드는 현재 live snapshot을 1초마다 읽어서 카드 상태를 갱신한다.
  const fetcher = useCallback(() => fetchSystemStatus(), []);
  const { data, error, loading } = usePolling(fetcher, 1000);

  const reset = async () => {
    // 시연 버튼은 백엔드 시나리오 상태를 처음부터 다시 재현하게 한다.
    await resetScenario();
  };

  if (loading) return <div className="card">상태 정보를 불러오는 중입니다.</div>;
  if (error) return <div className="card error-box">백엔드 연결 실패: {error.message}</div>;

  return (
    <div className="page-stack">
      <div className="page-heading">
        <div>
          <p className="eyebrow">Municipal Dashboard</p>
          <h2>지자체 관리 화면</h2>
          <p>TOWER_DETECTED부터 DOCK_COMPLETE까지 현재 관제 상태를 한 화면에서 확인합니다.</p>
        </div>
        <div className="button-row">
          <button className="secondary-button" onClick={reset}>시나리오 초기화</button>
        </div>
      </div>

      <div className="grid two-cols">
        <WebcamStatusCard webcam={data.webcam} />
        <AmrStatusCard robot={data.amr} />
      </div>
    </div>
  );
}
