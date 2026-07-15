import { Outlet, useNavigate } from 'react-router-dom';
import { LogOut, ShieldCheck } from 'lucide-react';
import Sidebar from './Sidebar.jsx';
import { logout } from '../../utils/auth.js';

// 내부 화면은 이 Layout 안에서만 렌더링된다.
// Sidebar는 고정으로 유지되고, 실제 페이지 내용만 Outlet으로 바뀐다.
export default function Layout() {
  const navigate = useNavigate();

  const handleLogout = () => {
    // 로그아웃은 demo auth 토큰을 지우고 로그인 화면으로 돌려보낸다.
    logout();
    navigate('/login', { replace: true });
  };

  return (
    <div className="app-shell">
      <Sidebar />
      <main className="main-panel">
        <header className="top-header">
          <div className="header-title">
            <div>
              <p className="header-kicker">FIELD RESPONSE DASHBOARD</p>
              <h1>팜가드봇 관제 시스템</h1>
              <p>AI 비전 기반 멧돼지 감지 · AMR 출동 · 사건 영상/보고서 관리</p>
            </div>
          </div>
          <div className="top-header-actions">
            <div className="header-status-pill">
              <ShieldCheck size={16} />
              관제 연결 상태
            </div>
            <button className="secondary-button" onClick={handleLogout}>
              <LogOut size={16} />
              로그아웃
            </button>
          </div>
        </header>
        <section className="content-area">
          <Outlet />
        </section>
      </main>
    </div>
  );
}
