// 브라우저 localStorage에 넣는 demo 로그인 플래그다.
const AUTH_KEY = 'wild_boar_amr_auth';

export function login(username, password) {
  // 시연용 인증이므로 admin/1234만 성공 처리한다.
  if (username === 'admin' && password === '1234') {
    localStorage.setItem(AUTH_KEY, 'true');
    return true;
  }
  return false;
}

export function logout() {
  // 로그아웃은 demo 토큰을 지우는 것으로 끝난다.
  localStorage.removeItem(AUTH_KEY);
}

export function isLoggedIn() {
  // 토큰 여부만 확인하고, 실제 서버 인증 검증은 아직 붙이지 않았다.
  return localStorage.getItem(AUTH_KEY) === 'true';
}
