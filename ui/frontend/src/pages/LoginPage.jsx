import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { login } from '../utils/auth.js';

const LOGO_SRC = '/images/farmguard_logo-removebg-preview2.png';

export default function LoginPage() {
  const navigate = useNavigate();
  const [username, setUsername] = useState('admin');
  const [password, setPassword] = useState('1234');
  const [error, setError] = useState('');

  const handleSubmit = (event) => {
    event.preventDefault();
    const ok = login(username, password);
    if (!ok) {
      setError('아이디 또는 비밀번호가 올바르지 않습니다.');
      return;
    }
    navigate('/dashboard', { replace: true });
  };

  return (
    <div className="login-page">
      <img src={LOGO_SRC} alt="FarmGuard Logo" className="login-background-logo" />
      <form className="login-card" onSubmit={handleSubmit}>
        <div className="login-brand">
          <div className="login-copy">
            <span className="login-kicker">FIELD SECURITY CONTROL</span>
            <h1>FarmGuard</h1>
            <p>유해동물 감지 및 AMR 관제 시스템</p>
          </div>
        </div>

        <label>
          아이디
          <input value={username} onChange={(e) => setUsername(e.target.value)} placeholder="admin" />
        </label>
        <label>
          비밀번호
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="1234" />
        </label>

        {error && <div className="error-box">{error}</div>}

        <button className="primary-button" type="submit">로그인</button>
        <div className="login-hint">테스트 계정: admin / 1234</div>
      </form>
    </div>
  );
}
