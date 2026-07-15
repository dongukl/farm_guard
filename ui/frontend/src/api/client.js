import { API_BASE_URL } from '../config/env.js';

// 모든 화면은 여기서 base URL과 에러 처리를 통일해서 백엔드에 접근한다.
export async function apiGet(path) {
  const response = await fetch(`${API_BASE_URL}${path}`);
  if (!response.ok) {
    throw new Error(`GET ${path} failed: ${response.status}`);
  }
  return response.json();
}

// POST와 PATCH도 같은 방식으로 감싸서 화면 코드가 fetch 세부사항에 직접 의존하지 않게 한다.
export async function apiPost(path, body = {}) {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  });
  if (!response.ok) {
    throw new Error(`POST ${path} failed: ${response.status}`);
  }
  return response.json();
}

export async function apiPatch(path, body = {}) {
  // 일부 화면은 제목 수정처럼 부분 갱신만 필요하므로 PATCH도 공통 래퍼로 둔다.
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  });
  if (!response.ok) {
    throw new Error(`PATCH ${path} failed: ${response.status}`);
  }
  return response.json();
}
