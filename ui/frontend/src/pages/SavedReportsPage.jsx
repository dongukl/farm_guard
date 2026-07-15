import { useCallback, useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { BarChart3, FileText, RefreshCcw, RotateCcw, Save } from 'lucide-react';
import ReportOperationSummary from '../components/report/ReportOperationSummary.jsx';
import ReportTimeline from '../components/report/ReportTimeline.jsx';
import { fetchSavedReport, fetchSavedReports, restoreSavedReport, updateSavedReportTitle } from '../api/statusApi.js';
import { API_BASE_URL } from '../config/env.js';
import { formatDateTime } from '../utils/formatDate.js';
import { REPORT_STEPS } from '../utils/reportAnalysis.js';

// 통합 보고서 타임라인의 전체 단계 수이다.
// 백엔드 completed_steps와 함께 "4/5" 진행도 배지를 만드는 데 사용한다.
const TOTAL_STEPS = REPORT_STEPS.length;

function buildApiMediaUrl(path) {
  if (!path) return '';
  if (/^https?:\/\//i.test(path)) return path;
  return `${API_BASE_URL}${path}`;
}

export default function SavedReportsPage() {
  const navigate = useNavigate();

  // reports: 왼쪽 목록에 표시할 저장 보고서 배열이다.
  // selectedId: 사용자가 현재 선택한 보고서 id이다.
  // selectedReport: 오른쪽 상세 패널에 표시할 단일 보고서 데이터이다.
  const [reports, setReports] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [selectedReport, setSelectedReport] = useState(null);

  // 목록 조회, 상세 조회, 복원 요청은 각각 다른 비동기 흐름이라 상태를 분리했다.
  // 이렇게 하면 목록 새로고침 중에도 상세 영역이나 복원 버튼의 상태를 독립적으로 보여줄 수 있다.
  const [loadingList, setLoadingList] = useState(true);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [error, setError] = useState('');
  const [restoreError, setRestoreError] = useState('');
  const [restoring, setRestoring] = useState(false);
  const [titleDraft, setTitleDraft] = useState('');
  const [titleSaving, setTitleSaving] = useState(false);
  const [titleError, setTitleError] = useState('');
  const [titleMessage, setTitleMessage] = useState('');

  const loadReports = useCallback(async () => {
    // 저장된 보고서 목록을 최신순으로 다시 가져온다.
    // 최초 진입, 새로고침 버튼 클릭, 저장 후 재방문 시 모두 같은 함수를 사용한다.
    setLoadingList(true);
    setError('');

    try {
      const list = await fetchSavedReports();
      setReports(list);

      // 기존에 선택한 보고서가 새 목록에도 있으면 선택을 유지한다.
      // 삭제 API는 아직 없지만, 향후 삭제 기능이 추가돼도 첫 번째 항목으로 자연스럽게 이동한다.
      setSelectedId((currentId) => {
        if (currentId && list.some((report) => report.id === currentId)) {
          return currentId;
        }
        return list[0]?.id ?? null;
      });
    } catch (err) {
      setError(err.message);
    } finally {
      setLoadingList(false);
    }
  }, []);

  useEffect(() => {
    // 페이지가 처음 열릴 때 저장된 보고서 목록을 로드한다.
    loadReports();
  }, [loadReports]);

  useEffect(() => {
    // 선택된 id가 없으면 상세 패널을 비운다.
    // 저장된 보고서가 하나도 없을 때 이 경로를 탄다.
    if (!selectedId) {
      setSelectedReport(null);
      return undefined;
    }

    // 사용자가 빠르게 다른 보고서를 클릭하면 이전 요청이 늦게 끝날 수 있다.
    // isMounted 플래그로 이전 요청 결과가 새 선택 상태를 덮어쓰지 않게 한다.
    let isMounted = true;

    async function loadDetail() {
      // 선택한 보고서의 전체 내용을 다시 조회한다.
      // 목록 데이터와 상세 데이터의 응답 모양이 같아도 상세 패널은 단일 조회 API를 기준으로 둔다.
      setLoadingDetail(true);
      setError('');
      setRestoreError('');

      try {
        const report = await fetchSavedReport(selectedId);
        if (isMounted) {
          setSelectedReport(report);
          setTitleDraft(report.title);
          setTitleError('');
          setTitleMessage('');
        }
      } catch (err) {
        if (isMounted) {
          setError(err.message);
        }
      } finally {
        if (isMounted) {
          setLoadingDetail(false);
        }
      }
    }

    loadDetail();

    return () => {
      isMounted = false;
    };
  }, [selectedId]);

  const handleTitleUpdate = async (event) => {
    event.preventDefault();
    if (!selectedReport) return;

    const nextTitle = titleDraft.trim();
    if (!nextTitle) {
      setTitleError('보고서 이름을 입력하세요.');
      setTitleMessage('');
      return;
    }

    setTitleSaving(true);
    setTitleError('');
    setTitleMessage('');

    try {
      const updatedReport = await updateSavedReportTitle(selectedReport.id, nextTitle);
      setSelectedReport(updatedReport);
      setTitleDraft(updatedReport.title);
      setReports((currentReports) => currentReports.map((item) => (
        item.id === updatedReport.id ? updatedReport : item
      )));
      setTitleMessage('이름을 수정했습니다.');
    } catch (err) {
      setTitleError(err.message);
    } finally {
      setTitleSaving(false);
    }
  };

  const handleRestore = async () => {
    // 상세 보고서가 로드되지 않았으면 복원할 대상이 없으므로 아무 작업도 하지 않는다.
    if (!selectedReport) return;

    setRestoring(true);
    setRestoreError('');

    try {
      // 백엔드의 /api/reports/{id}/restore는 DB 값을 메모리 live state에 반영한다.
      // 복원이 끝나면 통합 보고서 페이지로 이동해 복원된 결과를 즉시 확인하게 한다.
      const result = await restoreSavedReport(selectedReport.id);
      navigate('/report', {
        state: {
          // 이동 후 "불러온 보고서: ..." 안내를 보여주기 위한 router state이다.
          restoredReportTitle: result.saved_report.title
        }
      });
    } catch (err) {
      setRestoreError(err.message);
    } finally {
      setRestoring(false);
    }
  };

  // selectedReport 전체에는 id/title/created_at 같은 메타데이터도 포함된다.
  // 실제 타임라인과 요약 렌더링에는 중첩된 report 객체만 넘긴다.
  const report = selectedReport?.report;
  const reportVideoUrl = buildApiMediaUrl(selectedReport?.video_url);

  return (
    <div className="page-stack">
      <div className="page-heading">
        <div>
          <p className="eyebrow">Saved Reports</p>
          <h2>저장된 보고서</h2>
          <p>SQLite에 저장된 통합 보고서를 선택해서 다시 불러옵니다.</p>
        </div>
        <div className="button-row">
          <button className="secondary-button icon-button-text" onClick={loadReports} disabled={loadingList}>
            <RefreshCcw size={16} />
            새로고침
          </button>
          <Link className="secondary-button link-button" to="/report">
            <FileText size={16} />
            통합 보고서
          </Link>
          <Link className="secondary-button link-button" to="/analytics">
            <BarChart3 size={16} />
            보고서 분석
          </Link>
        </div>
      </div>

      {error && <div className="card error-box">보고서 조회 실패: {error}</div>}

      <div className="saved-report-grid">
        <article className="card saved-report-list-card">
          {/* 왼쪽 패널: SQLite에 저장된 보고서 목록이다. */}
          <div className="card-title-row">
            <div>
              <h2>보고서 목록</h2>
              <p className="helper-text">{loadingList ? '불러오는 중' : `${reports.length}건 저장됨`}</p>
            </div>
          </div>

          {!loadingList && reports.length === 0 && (
            <div className="empty-state">
              <strong>저장된 보고서가 없습니다.</strong>
              <span>도킹 완료 이벤트가 들어오면 자동 저장됩니다.</span>
            </div>
          )}

          <div className="saved-report-list">
            {reports.map((item) => (
              // 현재 선택된 보고서는 active 클래스로 강조한다.
              // 목록 항목을 클릭하면 selectedId만 바꾸고,
              // 실제 상세 조회는 selectedId를 감시하는 useEffect가 수행한다.
              <button
                className={item.id === selectedId ? 'saved-report-item active' : 'saved-report-item'}
                key={item.id}
                onClick={() => setSelectedId(item.id)}
                type="button"
              >
                <span>
                  <strong>{item.title}</strong>
                  <small>{formatDateTime(item.created_at)}</small>
                </span>
                <em>{item.completed_steps}/{TOTAL_STEPS}</em>
              </button>
            ))}
          </div>
        </article>

        <article className="card saved-report-detail-card">
          {/* 오른쪽 패널: 선택된 보고서의 상세 내용과 불러오기 버튼을 표시한다. */}
          {loadingDetail && <p className="helper-text">선택한 보고서를 불러오는 중입니다.</p>}

          {!loadingDetail && !selectedReport && (
            <div className="empty-state">
              <strong>보고서를 선택하세요.</strong>
              <span>목록에서 저장된 보고서를 고르면 내용이 표시됩니다.</span>
            </div>
          )}

          {!loadingDetail && selectedReport && (
            <div className="page-stack compact">
              <div className="card-title-row">
                <div>
                  <h2>{selectedReport.title}</h2>
                  <p className="helper-text">저장일: {formatDateTime(selectedReport.created_at)}</p>
                </div>
                <button className="primary-button icon-button-text" onClick={handleRestore} disabled={restoring}>
                  <RotateCcw size={16} />
                  {restoring ? '불러오는 중' : '불러오기'}
                </button>
              </div>

              <form className="report-title-edit-form" onSubmit={handleTitleUpdate}>
                <label className="field-label" htmlFor="saved-report-title">보고서 이름</label>
                <input
                  id="saved-report-title"
                  value={titleDraft}
                  onChange={(event) => setTitleDraft(event.target.value)}
                />
                <button className="secondary-button icon-button-text" type="submit" disabled={titleSaving}>
                  <Save size={16} />
                  {titleSaving ? '저장 중' : '이름 저장'}
                </button>
              </form>

              {titleMessage && <p className="success-text">{titleMessage}</p>}
              {titleError && <p className="error-text">이름 수정 실패: {titleError}</p>}
              {restoreError && <p className="error-text">불러오기 실패: {restoreError}</p>}

              <section className="report-video-panel">
                <div className="section-heading-row">
                  <div>
                    <h2>단계별 타임라인</h2>
                    <p className="helper-text">저장된 사건의 5단계 흐름이 시간 순서대로 기록된 상태입니다.</p>
                  </div>
                </div>
                <ReportTimeline report={report} />
              </section>

              <section className="report-video-panel">
                <div className="section-heading-row">
                  <div>
                    <h2>사건 영상</h2>
                    <p className="helper-text">
                      감지부터 도킹 완료까지 저장된 YOLO 처리 영상입니다.
                    </p>
                  </div>
                </div>

                {selectedReport.video_path ? (
                  <div className="report-video-content">
                    <div className="report-video-meta">
                      <span>로컬 저장 경로</span>
                      <strong>{selectedReport.video_path}</strong>
                    </div>
                    {selectedReport.has_video && reportVideoUrl ? (
                      <video controls preload="metadata" src={reportVideoUrl}>
                        저장된 사건 영상을 재생할 수 없습니다.
                      </video>
                    ) : (
                      <p className="error-text">영상 파일을 찾을 수 없습니다. 로컬 경로를 확인하세요.</p>
                    )}
                  </div>
                ) : (
                  <div className="empty-state">
                    <strong>저장된 영상이 없습니다.</strong>
                    <span>감지 후 도킹 완료까지 진행된 보고서에 영상 경로가 저장됩니다.</span>
                  </div>
                )}
              </section>

              {/* 저장된 과거 보고서는 미완료/누락 상태를 운영 점검 대상으로 해석한다. */}
              <ReportOperationSummary report={report} mode="saved" />
            </div>
          )}
        </article>
      </div>
    </div>
  );
}
