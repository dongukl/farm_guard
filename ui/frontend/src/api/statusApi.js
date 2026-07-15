import { apiGet, apiPatch, apiPost } from './client.js';

// 이 파일은 화면이 실제로 쓰는 서비스 단위 API만 모아둔다.
// 각 함수 이름은 화면 코드가 읽기 쉬운 도메인 용어를 쓰도록 맞춘다.
export function fetchSystemStatus() {
  // 대시보드가 읽는 live snapshot 전체를 가져온다.
  return apiGet('/api/status');
}

export function fetchReport() {
  // 통합 보고서 화면이 1초 폴링하는 현재 보고서 상태를 가져온다.
  return apiGet('/api/report');
}

// 저장된 통합 보고서 목록을 가져온다.
// 응답은 최신순 배열이며 각 항목에는 title, created_at, completed_steps, report가 포함된다.
export function fetchSavedReports() {
  // 저장된 보고서 목록은 최신순으로 내려온다.
  return apiGet('/api/reports');
}

// 목록에서 특정 보고서를 선택했을 때 상세 데이터를 다시 조회한다.
// 목록 응답에도 report가 있지만, 상세 화면은 항상 서버의 최신 단일 조회 결과를 기준으로 렌더링한다.
export function fetchSavedReport(reportId) {
  // 목록에서 선택한 보고서의 최신 단일 상세를 다시 읽는다.
  return apiGet(`/api/reports/${reportId}`);
}

// 저장된 보고서의 제목만 수정한다.
export function updateSavedReportTitle(reportId, title) {
  // 저장된 보고서의 제목만 수정한다.
  return apiPatch(`/api/reports/${reportId}/title`, { title });
}

// 저장된 보고서를 백엔드의 현재 live report/status 상태로 복원한다.
// 복원 후 통합 보고서 화면으로 이동하면 /api/report 폴링 결과가 복원된 값으로 표시된다.
export function restoreSavedReport(reportId) {
  // 저장 보고서를 현재 live state로 되돌린다.
  return apiPost(`/api/reports/${reportId}/restore`);
}

export function simulateEvent(eventName) {
  // mock 시나리오 버튼이 백엔드의 상태 전환 엔드포인트를 호출한다.
  return apiPost(`/api/simulate/${eventName}`);
}

export function resetScenario() {
  // 시뮬레이션 상태를 초기값으로 되돌린다.
  return apiPost('/api/simulate/reset');
}
