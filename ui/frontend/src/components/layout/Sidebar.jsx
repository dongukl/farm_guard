import { NavLink } from 'react-router-dom';
import { Archive, BarChart3, Camera, FileText, MonitorCog } from 'lucide-react';

const LOGO_SRC = '/images/farmguard_logo-removebg-preview2.png';

// 로그인 후 모든 내부 화면에서 공통으로 보이는 사이드바다.
// 각 메뉴는 같은 Layout 안에서 페이지 전환만 일으킨다.
export default function Sidebar() {
  return (
    <aside className="sidebar">
      <div className="brand">
        <img src={LOGO_SRC} alt="FarmGuard Logo" className="brand-logo" />
        <div className="brand-copy">
          <strong>팜가드봇</strong>
          <span>Farm Guard Bot Control</span>
        </div>
      </div>

      <nav className="nav-menu">
        <NavLink to="/dashboard" className={({ isActive }) => isActive ? 'nav-link active' : 'nav-link'}>
          <MonitorCog size={18} />
          지자체 관리
        </NavLink>
        <NavLink to="/cameras" className={({ isActive }) => isActive ? 'nav-link active' : 'nav-link'}>
          <Camera size={18} />
          실시간 카메라 관제
        </NavLink>
        <NavLink to="/report" className={({ isActive }) => isActive ? 'nav-link active' : 'nav-link'}>
          <FileText size={18} />
          통합 보고서
        </NavLink>

        {/* 저장된 보고서는 SQLite에 저장된 결과를 다시 조회하는 화면이다. */}
        <NavLink to="/saved-reports" className={({ isActive }) => isActive ? 'nav-link active' : 'nav-link'}>
          <Archive size={18} />
          저장된 보고서
        </NavLink>
        <NavLink to="/analytics" className={({ isActive }) => isActive ? 'nav-link active' : 'nav-link'}>
          <BarChart3 size={18} />
          보고서 분석
        </NavLink>
      </nav>
    </aside>
  );
}
