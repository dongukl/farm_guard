// 백엔드의 webcam.status 값을 화면에 보여줄 한국어 라벨로 바꾼다.
export const WEBCAM_STATUS_LABEL = {
  detected: '감지',
  not_detected: '감지 안됨'
};

// 백엔드의 amr.status 값을 화면 카드에서 읽기 쉬운 문구로 바꾼다.
export const AMR_STATUS_LABEL = {
  tower_detected: '감지',
  undock: '충전 도크 분리 및 출동',
  herding_active: '퇴치 시작',
  mission_complete: '야생동물 퇴치 완료 · 복귀 시작',
  dock_complete: '도킹 완료 및 충전 대기 중'
};

export function formatAmrStatusLabel(robot) {
  if (robot?.status === 'dock_complete' && robot?.name) {
    return `${robot.name} 도킹 완료 및 충전 대기 중`;
  }
  return AMR_STATUS_LABEL[robot?.status] || '-';
}

export function webcamStatusClass(status) {
  // 웹캠은 감지 여부에 따라 위험/정상 색만 고르면 된다.
  return status === 'detected' ? 'danger' : 'success';
}

export function amrStatusClass(status) {
  // AMR은 새 5단계를 관제 톤에 맞춰 위험/진행/완료 색으로 구분한다.
  if (status === 'tower_detected') return 'danger';
  if (status === 'undock') return 'warning';
  if (status === 'herding_active') return 'danger';
  if (status === 'mission_complete') return 'info';
  if (status === 'dock_complete') return 'success';
  return 'neutral';
}
