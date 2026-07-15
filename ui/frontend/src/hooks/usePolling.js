import { useEffect, useState } from 'react';

export default function usePolling(fetcher, intervalMs = 1000) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let isMounted = true;
    let timerId;

    async function load() {
      // fetcher를 한 번 호출하고, 성공/실패와 무관하게 다음 polling을 예약한다.
      try {
        const result = await fetcher();
        if (isMounted) {
          setData(result);
          setError(null);
          setLoading(false);
        }
      } catch (err) {
        if (isMounted) {
          setError(err);
          setLoading(false);
        }
      } finally {
        if (isMounted) {
          timerId = setTimeout(load, intervalMs);
        }
      }
    }

    load();

    return () => {
      // 화면이 사라지면 예약된 timeout을 지워 중복 polling을 막는다.
      isMounted = false;
      clearTimeout(timerId);
    };
  }, [fetcher, intervalMs]);

  return { data, error, loading };
}
