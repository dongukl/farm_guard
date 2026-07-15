import { Navigate, Route, Routes } from 'react-router-dom';
import LoginPage from './pages/LoginPage.jsx';
import MunicipalDashboardPage from './pages/MunicipalDashboardPage.jsx';
import CameraMonitorPage from './pages/CameraMonitorPage.jsx';
import IntegratedReportPage from './pages/IntegratedReportPage.jsx';
import SavedReportsPage from './pages/SavedReportsPage.jsx';
import ReportAnalyticsPage from './pages/ReportAnalyticsPage.jsx';
import Layout from './components/layout/Layout.jsx';
import { isLoggedIn } from './utils/auth.js';

// 로그인 여부에 따라 내부 화면 접근을 제어한다.
// 이 프로젝트는 모든 내부 페이지를 하나의 보호된 Layout 아래에 둔다.
function ProtectedRoute({ children }) {
  // 로그인 토큰이 없으면 내부 화면 접근을 막고 로그인 페이지로 보낸다.
  // 저장된 보고서 페이지도 같은 Layout 아래에 있으므로 동일한 보호 정책을 적용받는다.
  if (!isLoggedIn()) {
    return <Navigate to="/login" replace />;
  }
  return children;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        path="/"
        element={
          <ProtectedRoute>
            <Layout />
          </ProtectedRoute>
        }
      >
        {/* 루트 접속 시에는 지자체 관리 화면을 기본 진입점으로 보낸다. */}
        <Route index element={<Navigate to="/dashboard" replace />} />
        <Route path="dashboard" element={<MunicipalDashboardPage />} />
        <Route path="cameras" element={<CameraMonitorPage />} />
        <Route path="report" element={<IntegratedReportPage />} />

        {/* SQLite에 저장된 보고서 목록/상세/불러오기 화면이다. */}
        <Route path="saved-reports" element={<SavedReportsPage />} />

        {/* 저장된 보고서를 연/월/일 단위로 집계하고 해결/점검 필요 현황을 보여주는 화면이다. */}
        <Route path="analytics" element={<ReportAnalyticsPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/dashboard" replace />} />
    </Routes>
  );
}
