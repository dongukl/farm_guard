import { useEffect, useState } from 'react';

function formatStatusTime(value) {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  return date.toLocaleTimeString('ko-KR');
}

export default function CameraPanel({ camera }) {
  const [refreshKey, setRefreshKey] = useState(Date.now());
  const [streamStatus, setStreamStatus] = useState(null);
  const [statusError, setStatusError] = useState('');
  const [deviceOptions, setDeviceOptions] = useState([]);
  const [selectedDevice, setSelectedDevice] = useState('');
  const [isChangingDevice, setIsChangingDevice] = useState(false);
  const [deviceError, setDeviceError] = useState('');

  // 실제 화면 출력은 원래 동작하던 MJPEG stream을 유지하고, 상태 API는 배지/진단 문구에만 쓴다.
  const imageUrl = `${camera.streamUrl}?t=${encodeURIComponent(refreshKey)}`;
  const refreshLabel = camera.streamType === 'mjpeg' ? '재연결' : '새로고침';
  const hasLiveStatus = Boolean(camera.statusUrl);
  const canSelectDevice = hasLiveStatus && camera.deviceOptionsUrl && camera.deviceUrl;
  const statusPollMs = 1500;

  useEffect(() => {
    if (!hasLiveStatus) return undefined;

    let isMounted = true;
    let timerId;

    async function loadStatus() {
      // streamUrl과 별개로 카메라 상태 API를 주기적으로 읽어 진단 문구를 갱신한다.
      try {
        const response = await fetch(`${camera.statusUrl}?t=${Date.now()}`);
        if (!response.ok) {
          throw new Error(`status ${response.status}`);
        }
        const result = await response.json();
        if (isMounted) {
          setStreamStatus(result);
          if (result.device && !isChangingDevice) {
            setSelectedDevice(String(result.device));
          }
          setStatusError('');
        }
      } catch (err) {
        if (isMounted) {
          setStatusError(err.message);
        }
      } finally {
        if (isMounted) {
          timerId = setTimeout(loadStatus, statusPollMs);
        }
      }
    }

    loadStatus();

    return () => {
      isMounted = false;
      clearTimeout(timerId);
    };
  }, [camera.statusUrl, hasLiveStatus, isChangingDevice, refreshKey, statusPollMs]);

  useEffect(() => {
    if (!canSelectDevice) return undefined;

    let isMounted = true;

    async function loadDeviceOptions() {
      // 웹캠은 /dev/video* 목록을 백엔드가 제공하고, 프론트는 그 선택지만 보여준다.
      try {
        const response = await fetch(`${camera.deviceOptionsUrl}?t=${Date.now()}`);
        if (!response.ok) {
          throw new Error(`status ${response.status}`);
        }
        const result = await response.json();
        if (isMounted) {
          setDeviceOptions(result.devices || []);
          setSelectedDevice(String(result.selected ?? '0'));
          setDeviceError('');
        }
      } catch (err) {
        if (isMounted) {
          setDeviceError(`장치 목록 조회 실패: ${err.message}`);
        }
      }
    }

    loadDeviceOptions();

    return () => {
      isMounted = false;
    };
  }, [camera.deviceOptionsUrl, canSelectDevice]);

  async function handleDeviceChange(event) {
    // 사용자가 다른 /dev/video* 번호를 고르면 백엔드에 POST로 전달해서 재캡처한다.
    const nextDevice = event.target.value;
    setSelectedDevice(nextDevice);

    if (!camera.deviceUrl) return;

    setIsChangingDevice(true);
    setDeviceError('');

    try {
      const response = await fetch(camera.deviceUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ device: nextDevice })
      });

      const result = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(result.detail || `status ${response.status}`);
      }

      setStreamStatus(result);
      setRefreshKey(Date.now());
    } catch (err) {
      setDeviceError(`장치 변경 실패: ${err.message}`);
    } finally {
      setIsChangingDevice(false);
    }
  }

  const hasFrame = Boolean(streamStatus?.latest_frame_at);
  const isYoloMode = streamStatus?.mode === 'yolo';
  const detectionCount = Number(streamStatus?.detection_count ?? 0);
  const inferenceMs = streamStatus?.inference_ms;
  const recording = streamStatus?.recording;
  const isDetected = detectionCount > 0;
  const isRecording = Boolean(recording?.active);
  const frameWidth = Number(streamStatus?.latest_frame_width || streamStatus?.width || 640);
  const frameHeight = Number(streamStatus?.latest_frame_height || streamStatus?.height || 480);
  const frameAspectRatio = frameWidth > 0 && frameHeight > 0 ? `${frameWidth} / ${frameHeight}` : '4 / 3';
  const hasError = Boolean(statusError || deviceError || streamStatus?.error);
  const cardStateClass = hasError
    ? 'offline-state'
    : isDetected || isRecording
      ? 'danger-state'
      : hasFrame
        ? 'live-state'
        : 'standby-state';
  const statusText = (() => {
    const sourceLabel = streamStatus?.device || camera.name;
    const yoloSuffix = isYoloMode
      ? ` · YOLO 감지 ${detectionCount}건${inferenceMs ? ` · ${Number(inferenceMs).toFixed(1)}ms` : ''}`
      : '';

    if (!hasLiveStatus) return '';
    if (isChangingDevice) return `${selectedDevice}번 장치 연결 중`;
    if (deviceError) return deviceError;
    if (statusError) return `상태 조회 실패: ${statusError}`;
    if (!streamStatus) return '카메라 상태 확인 중';
    if (streamStatus.error) return streamStatus.error;
    if (!hasFrame) return `${sourceLabel} 프레임 대기 중`;
    return `프레임 수신 중 · ${formatStatusTime(streamStatus.latest_frame_at)}${yoloSuffix}`;
  })();
  const recordingText = recording?.active
    ? `사건 영상 녹화 중 · ${recording.filename || recording.path || ''}`
    : recording?.path
      ? `최근 사건 영상 · ${recording.filename || recording.path}`
      : '';

  return (
    <article className={`card camera-card ${cardStateClass}`}>
      <div className="camera-header">
        <div className="camera-title-block">
          <span className="camera-kicker">{camera.kicker || 'FIELD MONITOR'}</span>
          <h2>{camera.name}</h2>
          <p>{camera.description}</p>
        </div>
        <div className="camera-actions">
          {canSelectDevice && (
            <label className="camera-device-select">
              <span>장치</span>
              <select value={selectedDevice} onChange={handleDeviceChange} disabled={isChangingDevice}>
                {deviceOptions.length === 0 && <option value="">조회 중</option>}
                {deviceOptions.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}{option.available ? '' : ' · 미감지'}
                  </option>
                ))}
              </select>
            </label>
          )}
          <button className="secondary-button small" onClick={() => setRefreshKey(Date.now())}>{refreshLabel}</button>
        </div>
      </div>
      <div className="camera-frame" style={{ '--camera-aspect-ratio': frameAspectRatio }}>
        <img src={imageUrl} alt={`${camera.name} 화면`} />
        <div className="camera-chip-row">
          <div className="live-chip">LIVE</div>
          {isDetected && <span className="status-badge danger">감지 경보</span>}
          {isRecording && <span className="status-badge warning">사건 녹화 중</span>}
          {!isDetected && hasFrame && <span className="status-badge success">정상 수신</span>}
        </div>
        <div className="camera-nameplate">{camera.name}</div>
        {hasLiveStatus && !hasFrame && (
          <div className="camera-stream-message">
            <strong>영상 대기</strong>
            <span>{statusText}</span>
          </div>
        )}
      </div>
      {hasLiveStatus && (
        <div className={hasFrame ? 'camera-status-line success' : 'camera-status-line warning'}>
          <span>{statusText}</span>
          {recordingText && <small>{recordingText}</small>}
        </div>
      )}
    </article>
  );
}
