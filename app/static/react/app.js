/* ==============================================
   AI Video Factory — React SPA
   OPA Business Style · Light Theme
   ============================================== */

const { useState, useEffect, useRef, useCallback } = React;

// =============================================
// Utility Helpers
// =============================================

function formatTime(isoStr) {
    if (!isoStr) return '—';
    const d = new Date(isoStr);
    return d.toLocaleString('vi-VN', { hour: '2-digit', minute: '2-digit', day: '2-digit', month: '2-digit' });
}

// =============================================
// Toast System
// =============================================

let toastIdCounter = 0;

function ToastContainer({ toasts, removeToast }) {
    return (
        <div className="toast-container">
            {toasts.map(t => (
                <div key={t.id} className={`toast toast-${t.type}`} onClick={() => removeToast(t.id)}>
                    {t.message}
                </div>
            ))}
        </div>
    );
}

// =============================================
// Loading Overlay
// =============================================

function LoadingOverlay({ show, text }) {
    return (
        <div className={`loading-overlay ${show ? 'show' : ''}`}>
            <div className="loading-content">
                <div className="spinner" style={{ width: 40, height: 40, borderWidth: 3, marginBottom: '0.75rem' }}></div>
                <p className="text-muted">{text || 'Đang xử lý...'}</p>
            </div>
        </div>
    );
}

// =============================================
// Navbar
// =============================================

function Navbar({ currentPage, onNavigate }) {
    return (
        <nav className="navbar">
            <div className="container">
                <a href="#" className="navbar-brand" onClick={e => { e.preventDefault(); onNavigate('dashboard'); }}>
                    <span className="logo-icon">⚡</span>
                    AI Video Factory
                </a>
                <div className="navbar-links">
                    <a
                        className={currentPage === 'dashboard' ? 'active' : ''}
                        onClick={() => onNavigate('dashboard')}
                    >
                        Dashboard
                    </a>
                    <a
                        className={currentPage === 'workflow-builder' ? 'active' : ''}
                        onClick={() => onNavigate('workflow-builder')}
                    >
                        🔨 Workflow
                    </a>
                    <a
                        className={currentPage === 'review' ? 'active' : ''}
                        onClick={() => onNavigate('review')}
                    >
                        Review
                    </a>
                </div>
            </div>
        </nav>
    );
}

// =============================================
// Scrape Panel (Phase 0)
// =============================================

function ScrapePanel({ onScrapeResult, addToast, setLoading }) {
    const [activeTab, setActiveTab] = useState('single');
    const [url, setUrl] = useState('');
    const [scraping, setScraping] = useState(false);
    const [result, setResult] = useState(null);
    const [bulkResults, setBulkResults] = useState([]);

    // Google Sheet state
    const [sheetUrl, setSheetUrl] = useState('');
    const [sheetPreview, setSheetPreview] = useState(null);
    const [sheetLoading, setSheetLoading] = useState(false);
    const [sheetCrawling, setSheetCrawling] = useState(false);
    const [sheetResults, setSheetResults] = useState([]);
    const [sheetProgress, setSheetProgress] = useState({ current: 0, total: 0 });

    async function handleScrape() {
        if (!url.trim()) { addToast('Vui lòng nhập URL', 'error'); return; }
        setScraping(true);
        try {
            const res = await fetch('/api/scrape', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ url: url.trim() }),
            });
            const data = await res.json();
            if (data.success) {
                setResult(data);
                onScrapeResult(data);
                addToast('Crawl và phân tích thành công!', 'success');
            } else {
                addToast(data.detail || 'Không thể crawl URL', 'error');
            }
        } catch (e) {
            addToast('Lỗi kết nối server', 'error');
        } finally {
            setScraping(false);
        }
    }

    async function handleBulkFile(e) {
        const file = e.target.files[0];
        if (!file) return;
        setLoading(true, `Đang cào dữ liệu từ ${file.name}...`);
        const formData = new FormData();
        formData.append('file', file);
        try {
            const res = await fetch('/api/scrape/bulk', { method: 'POST', body: formData });
            const data = await res.json();
            if (data.success) {
                setBulkResults(data.results);
                addToast(`Đã cào xong ${data.results.length} sản phẩm!`, 'success');
            } else {
                addToast(data.detail || 'Lỗi import file', 'error');
            }
        } catch (e) {
            addToast('Lỗi hệ thống khi xử lý file', 'error');
        } finally {
            setLoading(false);
            e.target.value = '';
        }
    }

    // --- Google Sheet handlers ---

    async function handleSheetPreview() {
        if (!sheetUrl.trim()) { addToast('Vui lòng dán link Google Sheet', 'error'); return; }
        if (!sheetUrl.includes('docs.google.com/spreadsheets')) {
            addToast('Link không hợp lệ — vui lòng dán link Google Sheets', 'error');
            return;
        }
        setSheetLoading(true);
        setSheetPreview(null);
        setSheetResults([]);
        try {
            const res = await fetch('/api/scrape/sheet/preview', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ sheet_url: sheetUrl.trim() }),
            });
            const data = await res.json();
            if (data.success) {
                setSheetPreview(data);
                addToast(`Tìm thấy ${data.total_links} link — ${data.to_crawl} cần crawl`, 'success');
            } else {
                addToast(data.detail || 'Không thể đọc Google Sheet', 'error');
            }
        } catch (e) {
            addToast('Lỗi kết nối server', 'error');
        } finally {
            setSheetLoading(false);
        }
    }

    // Silent refresh — only updates preview data, preserves crawl results
    async function refreshSheetPreview() {
        try {
            const res = await fetch('/api/scrape/sheet/preview', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ sheet_url: sheetUrl.trim() }),
            });
            const data = await res.json();
            if (data.success) {
                setSheetPreview(data);
            }
        } catch (e) {
            // Silent fail
        }
    }

    async function handleSheetCrawl() {
        if (!sheetPreview || sheetPreview.to_crawl === 0) {
            addToast('Không có link nào cần crawl', 'error');
            return;
        }
        setSheetCrawling(true);
        setSheetResults([]);
        setSheetProgress({ current: 0, total: sheetPreview.to_crawl });
        try {
            const res = await fetch('/api/scrape/sheet', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ sheet_url: sheetUrl.trim() }),
            });
            const data = await res.json();
            if (data.success) {
                setSheetResults(data.results || []);
                setSheetProgress({ current: data.total, total: data.total });
                const successCount = (data.results || []).filter(r => r.success).length;
                addToast(`Hoàn tất! ${successCount}/${data.total} link crawl thành công. Trạng thái đã được cập nhật trên Sheet.`, 'success');
                // Refresh preview to show updated statuses (without clearing results)
                refreshSheetPreview();
            } else {
                addToast(data.detail || 'Lỗi crawl từ Google Sheet', 'error');
            }
        } catch (e) {
            addToast('Lỗi hệ thống khi crawl từ Sheet', 'error');
        } finally {
            setSheetCrawling(false);
        }
    }

    function useBulkItem(item) {
        onScrapeResult(item);
        addToast(`Đã chọn: ${(item.title || '').substring(0, 30)}...`, 'info');
    }

    return (
        <div className="card" id="phase0-card">
            <div className="card-header">
                <span className="phase-badge">Phase 0</span>
                <h3>🔍 Săn Nội Dung (Auto-Crawl)</h3>
            </div>

            <div className="tab-headers">
                <button className={`tab-btn ${activeTab === 'single' ? 'active' : ''}`} onClick={() => setActiveTab('single')}>Đơn lẻ (Single)</button>
                <button className={`tab-btn ${activeTab === 'bulk' ? 'active' : ''}`} onClick={() => setActiveTab('bulk')}>Hàng loạt (Bulk)</button>
                <button className={`tab-btn ${activeTab === 'sheet' ? 'active' : ''}`} onClick={() => setActiveTab('sheet')}>📊 Google Sheet</button>
            </div>

            {activeTab === 'single' && (
                <div className="form-group">
                    <label>URL bài viết / sản phẩm</label>
                    <div style={{ display: 'flex', gap: '0.75rem' }}>
                        <input
                            type="text"
                            className="form-input"
                            placeholder="Dán link sản phẩm hoặc bài viết vào đây..."
                            value={url}
                            onChange={e => setUrl(e.target.value)}
                            onKeyDown={e => e.key === 'Enter' && handleScrape()}
                            style={{ flex: 1 }}
                        />
                        <button className="btn btn-primary" disabled={scraping} onClick={handleScrape}>
                            {scraping && <span className="spinner"></span>}
                            Auto-Crawl
                        </button>
                    </div>
                </div>
            )}

            {activeTab === 'bulk' && (
                <div className="form-group">
                    <label>Import file CSV/Excel (chứa cột URL)</label>
                    <div className="dropzone" onClick={() => document.getElementById('bulk-file-input').click()}>
                        <input type="file" id="bulk-file-input" accept=".csv,.xlsx,.xls" onChange={handleBulkFile} style={{ display: 'none' }} />
                        <div className="dropzone-icon">📊</div>
                        <div className="dropzone-text">Kéo thả file hoặc <strong>click để chọn CSV/Excel</strong></div>
                    </div>
                </div>
            )}

            {/* ===== Google Sheet Tab ===== */}
            {activeTab === 'sheet' && (
                <div>
                    <div className="form-group">
                        <label>Link Google Sheet</label>
                        <div style={{ display: 'flex', gap: '0.75rem' }}>
                            <input
                                type="text"
                                className="form-input"
                                placeholder="https://docs.google.com/spreadsheets/d/xxxxx/edit"
                                value={sheetUrl}
                                onChange={e => setSheetUrl(e.target.value)}
                                onKeyDown={e => e.key === 'Enter' && handleSheetPreview()}
                                style={{ flex: 1 }}
                                id="sheet-url-input"
                            />
                            <button className="btn btn-primary" disabled={sheetLoading} onClick={handleSheetPreview} id="sheet-preview-btn">
                                {sheetLoading && <span className="spinner"></span>}
                                🔍 Preview
                            </button>
                        </div>
                        <div className="sheet-hint">
                            Sheet cần có cột chứa link (URL/Link) và cột trạng thái (Status/Trạng thái). 
                            Nhớ share Sheet với email Service Account.
                        </div>
                    </div>

                    {/* Sheet Preview */}
                    {sheetPreview && (
                        <div className="sheet-preview-box">
                            <div className="sheet-preview-header">
                                <div className="sheet-preview-title">
                                    <span className="sheet-icon">📋</span>
                                    <div>
                                        <strong>{sheetPreview.sheet_title}</strong>
                                        <span className="text-muted" style={{ fontSize: '0.8rem', display: 'block' }}>
                                            {sheetPreview.total_links} link · {sheetPreview.to_crawl} sẵn sàng · {sheetPreview.to_skip} bỏ qua
                                        </span>
                                    </div>
                                </div>
                                <button
                                    className="btn btn-success"
                                    disabled={sheetCrawling || sheetPreview.to_crawl === 0}
                                    onClick={handleSheetCrawl}
                                    id="sheet-crawl-btn"
                                >
                                    {sheetCrawling && <span className="spinner"></span>}
                                    🚀 Crawl {sheetPreview.to_crawl} link
                                </button>
                            </div>

                            {/* Progress bar */}
                            {sheetCrawling && (
                                <div className="sheet-progress">
                                    <div className="sheet-progress-bar">
                                        <div
                                            className="sheet-progress-fill"
                                            style={{ width: sheetProgress.total > 0 ? `${(sheetProgress.current / sheetProgress.total) * 100}%` : '0%' }}
                                        ></div>
                                    </div>
                                    <span className="sheet-progress-text">Đang crawl... vui lòng chờ</span>
                                </div>
                            )}

                            {/* Stats summary */}
                            <div className="sheet-stats">
                                <div className="sheet-stat">
                                    <span className="sheet-stat-value" style={{ color: 'var(--accent-primary)' }}>{sheetPreview.total_links}</span>
                                    <span className="sheet-stat-label">Tổng link</span>
                                </div>
                                <div className="sheet-stat">
                                    <span className="sheet-stat-value" style={{ color: 'var(--accent-secondary)' }}>{sheetPreview.to_crawl}</span>
                                    <span className="sheet-stat-label">Sẵn sàng</span>
                                </div>
                                <div className="sheet-stat">
                                    <span className="sheet-stat-value" style={{ color: 'var(--text-muted)' }}>{sheetPreview.to_skip}</span>
                                    <span className="sheet-stat-label">Bỏ qua</span>
                                </div>
                            </div>

                            {/* Link list */}
                            <div style={{ overflowX: 'auto', maxHeight: '400px', overflowY: 'auto' }}>
                                <table className="data-table">
                                    <thead>
                                        <tr>
                                            <th style={{ width: 50 }}>#</th>
                                            <th>URL</th>
                                            <th style={{ width: 140 }}>Trạng thái</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {(sheetPreview.links || []).map((link, i) => (
                                            <tr key={i} style={{ opacity: link.should_crawl ? 1 : 0.5 }}>
                                                <td style={{ color: 'var(--text-muted)', fontSize: '0.8rem' }}>{link.row}</td>
                                                <td>
                                                    <a href={link.url} target="_blank" rel="noopener noreferrer"
                                                       style={{ color: 'var(--accent-primary)', textDecoration: 'none', fontSize: '0.85rem', wordBreak: 'break-all' }}>
                                                        {link.url.length > 80 ? link.url.substring(0, 80) + '…' : link.url}
                                                    </a>
                                                </td>
                                                <td>
                                                    {link.should_crawl
                                                        ? <span className="badge badge-sheet-ready">{link.status || 'Sẵn sàng'}</span>
                                                        : <span className="badge badge-sheet-done">{link.status}</span>
                                                    }
                                                </td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            </div>
                        </div>
                    )}

                    {/* Sheet Crawl Results */}
                    {sheetResults.length > 0 && (
                        <div className="result-box show" style={{ marginTop: '1rem' }}>
                            <h3 style={{ color: 'var(--accent-primary)', marginBottom: '1rem', fontSize: '0.95rem' }}>
                                ✅ Kết quả crawl ({sheetResults.filter(r => r.success).length}/{sheetResults.length})
                            </h3>
                            <div style={{ overflowX: 'auto' }}>
                                <table className="data-table">
                                    <thead>
                                        <tr>
                                            <th>Ảnh</th>
                                            <th>Sản phẩm</th>
                                            <th>Giá</th>
                                            <th>Trạng thái</th>
                                            <th>Hành động</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {sheetResults.map((item, i) => item.error ? (
                                            <tr key={i} style={{ opacity: 0.5 }}>
                                                <td colSpan="4" style={{ color: 'var(--accent-danger)' }}>❌ {item.source_url}</td>
                                                <td><a href={item.source_url} target="_blank" className="btn btn-outline btn-sm">Link</a></td>
                                            </tr>
                                        ) : (
                                            <tr key={i}>
                                                <td>
                                                    {item.image_url
                                                        ? <img src={item.image_url} alt="" style={{ width: 44, height: 44, objectFit: 'cover', borderRadius: 6 }} />
                                                        : <span className="text-muted" style={{ fontSize: '0.75rem' }}>—</span>
                                                    }
                                                </td>
                                                <td className="job-title">{item.title}</td>
                                                <td style={{ color: 'var(--accent-danger)', fontWeight: 600 }}>{item.price}</td>
                                                <td><span className="badge badge-approved">Success</span></td>
                                                <td><button className="btn btn-primary btn-sm" onClick={() => useBulkItem(item)}>⚡ Tạo Video</button></td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            </div>
                        </div>
                    )}
                </div>
            )}



            {/* Single Result */}
            {result && activeTab === 'single' && (
                <div className="result-box show">
                    <h3 style={{ color: 'var(--accent-primary)', marginBottom: '1rem', fontSize: '0.95rem' }}>📝 Kết quả LLM</h3>
                    <div className="product-preview">
                        <div className="product-img">
                            {result.image_url
                                ? <img src={result.image_url} alt="Product" />
                                : <span className="text-muted" style={{ fontSize: '0.8rem' }}>No Image</span>}
                        </div>
                        <div className="product-info">
                            <div className="product-title">{result.title || 'Untitled'}</div>
                            <div className="product-price">{result.price || 'Liên hệ'}</div>
                            <div className="product-desc">{result.description || ''}</div>
                        </div>
                    </div>
                    <div className="form-group">
                        <label>Kịch bản TTS</label>
                        <textarea className="form-textarea" rows="3" readOnly value={result.script || ''}></textarea>
                    </div>
                    <div className="form-group">
                        <label>Video Prompts</label>
                        <textarea className="form-textarea" rows="3" readOnly value={(result.video_prompts || []).join('\n')}></textarea>
                    </div>
                </div>
            )}

            {/* Bulk Results */}
            {bulkResults.length > 0 && activeTab === 'bulk' && (
                <div className="result-box show" style={{ marginTop: '1rem' }}>
                    <h3 style={{ color: 'var(--accent-primary)', marginBottom: '1rem', fontSize: '0.95rem' }}>
                        📋 Danh sách ({bulkResults.length})
                    </h3>
                    <div style={{ overflowX: 'auto' }}>
                        <table className="data-table">
                            <thead>
                                <tr>
                                    <th>Ảnh</th>
                                    <th>Sản phẩm</th>
                                    <th>Giá</th>
                                    <th>Trạng thái</th>
                                    <th>Hành động</th>
                                </tr>
                            </thead>
                            <tbody>
                                {bulkResults.map((item, i) => item.error ? (
                                    <tr key={i} style={{ opacity: 0.5 }}>
                                        <td colSpan="4" style={{ color: 'var(--accent-danger)' }}>❌ {item.source_url}</td>
                                        <td><a href={item.source_url} target="_blank" className="btn btn-outline btn-sm">Link</a></td>
                                    </tr>
                                ) : (
                                    <tr key={i}>
                                        <td><img src={item.image_url} alt="" style={{ width: 44, height: 44, objectFit: 'cover', borderRadius: 6 }} /></td>
                                        <td className="job-title">{item.title}</td>
                                        <td style={{ color: 'var(--accent-danger)', fontWeight: 600 }}>{item.price}</td>
                                        <td><span className="badge badge-approved">Success</span></td>
                                        <td><button className="btn btn-primary btn-sm" onClick={() => useBulkItem(item)}>⚡ Tạo Video</button></td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                </div>
            )}
        </div>
    );
}

// =============================================
// Submit Panel (Phase 1-2)
// =============================================

function SubmitPanel({ prefill, addToast, setLoading, onJobCreated }) {
    const [title, setTitle] = useState('');
    const [imageUrl, setImageUrl] = useState('');
    const [prompt, setPrompt] = useState('');
    const [script, setScript] = useState('');
    const [model, setModel] = useState('kling-3.0');
    const [mode, setMode] = useState('i2v');
    const [quality, setQuality] = useState('1080p');
    const [duration, setDuration] = useState(5);
    const [ratio, setRatio] = useState('9:16');
    const [preview, setPreview] = useState('');
    const [submitting, setSubmitting] = useState(false);

    // Workflow state
    const [workflows, setWorkflows] = useState([]);
    const [workflowId, setWorkflowId] = useState('default');
    const [personImageUrl, setPersonImageUrl] = useState('');
    const [personPreview, setPersonPreview] = useState('');
    const [bgImageUrl, setBgImageUrl] = useState('');
    const [bgPreview, setBgPreview] = useState('');

    // Load available workflows
    useEffect(() => {
        fetch('/api/workflows').then(r => r.json()).then(data => {
            if (data.success) setWorkflows(data.workflows);
        }).catch(() => {});
    }, []);

    // Prefill from scrape
    useEffect(() => {
        if (prefill) {
            setTitle(prefill.title || '');
            setScript(prefill.script || '');
            if (prefill.video_prompts && prefill.video_prompts.length > 0) {
                setPrompt(prefill.video_prompts[0]);
            }
            if (prefill.image_url) {
                setImageUrl(prefill.image_url);
                setPreview(prefill.image_url);
            }
        }
    }, [prefill]);

    function handleModelChange(val) {
        setModel(val);
        if (val === 'veo-3-fast') {
            setMode('t2v');
        } else {
            setMode('i2v');
        }
    }

    async function uploadImage(file, setUrl, setPreviewFn, label) {
        if (!file || !file.type.startsWith('image/')) {
            addToast('Chỉ chấp nhận file ảnh', 'error');
            return;
        }
        const reader = new FileReader();
        reader.onload = (ev) => setPreviewFn(ev.target.result);
        reader.readAsDataURL(file);
        setLoading(true, `Đang upload ${label}...`);
        const formData = new FormData();
        formData.append('file', file);
        try {
            const res = await fetch('/api/upload', { method: 'POST', body: formData });
            const data = await res.json();
            if (data.success) {
                setUrl(data.url);
                addToast(`Upload ${label} thành công: ${(data.size / 1024).toFixed(0)} KB`, 'success');
            } else {
                addToast(data.detail || `Upload ${label} thất bại`, 'error');
            }
        } catch (e) {
            addToast('Lỗi upload', 'error');
        } finally {
            setLoading(false);
        }
    }

    function handleFileUpload(e) {
        uploadImage(e.target.files[0], setImageUrl, setPreview, 'ảnh nguồn');
    }
    function handlePersonUpload(e) {
        uploadImage(e.target.files[0], setPersonImageUrl, setPersonPreview, 'ảnh nhân vật');
    }
    function handleBgUpload(e) {
        uploadImage(e.target.files[0], setBgImageUrl, setBgPreview, 'ảnh background');
    }

    async function handleSubmit() {
        if (!prompt.trim()) { addToast('Vui lòng nhập prompt tạo video', 'error'); return; }

        // Validate required inputs for selected workflow
        const wf = workflows.find(w => w.id === workflowId);
        if (wf && wf.required_inputs) {
            if (wf.required_inputs.includes('image_url') && !imageUrl) {
                addToast('Workflow này yêu cầu ảnh nguồn', 'error'); return;
            }
            if (wf.required_inputs.includes('person_image_url') && !personImageUrl) {
                addToast('Workflow này yêu cầu ảnh nhân vật', 'error'); return;
            }
            if (wf.required_inputs.includes('background_image_url') && !bgImageUrl) {
                addToast('Workflow này yêu cầu ảnh background', 'error'); return;
            }
        }

        setSubmitting(true);
        try {
            const res = await fetch('/api/submit', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    title: title || 'Video Job',
                    image_url: imageUrl || null,
                    person_image_url: personImageUrl || null,
                    background_image_url: bgImageUrl || null,
                    prompt: prompt.trim(),
                    script_text: script || null,
                    workflow_id: workflowId,
                    model, mode, quality,
                    duration: parseInt(duration) || 5,
                    aspect_ratio: ratio,
                }),
            });
            const data = await res.json();
            if (data.success) {
                addToast(`Job #${data.job.id} (${workflowId}) đã được đưa vào hàng đợi! 🚀`, 'success');
                onJobCreated();
                setPrompt('');
                setScript('');
                setTitle('');
            } else {
                addToast(data.detail || 'Không thể tạo job', 'error');
            }
        } catch (e) {
            addToast('Lỗi kết nối server', 'error');
        } finally {
            setSubmitting(false);
        }
    }

    const selectedWf = workflows.find(w => w.id === workflowId);
    const needsPerson = selectedWf && selectedWf.required_inputs && selectedWf.required_inputs.includes('person_image_url');
    const needsBg = selectedWf && selectedWf.required_inputs && selectedWf.required_inputs.includes('background_image_url');

    const modeOptions = model === 'veo-3-fast'
        ? [['t2v', 'Text-to-Video'], ['i2v', 'Image-to-Video'], ['r2v', 'Reference-to-Video']]
        : [['i2v', 'Image-to-Video']];

    return (
        <div className="card" id="phase1-card">
            <div className="card-header">
                <span className="phase-badge">Phase 1-2</span>
                <h3>🎬 Tạo Video (Input & Submit)</h3>
            </div>

            {/* Workflow Selector */}
            <div className="form-group">
                <label>🔀 Workflow</label>
                <select className="form-select" value={workflowId} onChange={e => setWorkflowId(e.target.value)} id="workflow-select">
                    {workflows.map(wf => (
                        <option key={wf.id} value={wf.id}>{wf.name} ({wf.steps.length} steps)</option>
                    ))}
                </select>
                {selectedWf && selectedWf.description && (
                    <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginTop: '0.35rem', padding: '0.5rem 0.75rem', background: 'var(--bg-secondary)', borderRadius: 8 }}>
                        📋 {selectedWf.description}
                        <div style={{ marginTop: '0.25rem', display: 'flex', gap: '0.35rem', flexWrap: 'wrap' }}>
                            {selectedWf.steps.map((s, i) => (
                                <span key={i} style={{ background: 'var(--accent-primary)', color: '#fff', padding: '2px 8px', borderRadius: 12, fontSize: '0.7rem' }}>{s}</span>
                            ))}
                        </div>
                    </div>
                )}
            </div>

            {/* Upload Image */}
            <div className="form-group">
                <label>🖼️ Ảnh nguồn (Start Frame)</label>
                <div className="dropzone" style={{ position: 'relative' }}>
                    <input type="file" accept="image/*" onChange={handleFileUpload} style={{ position: 'absolute', inset: 0, opacity: 0, cursor: 'pointer' }} />
                    {preview
                        ? <div className="dropzone-preview"><img src={preview} alt="Preview" /></div>
                        : <>
                            <div className="dropzone-icon">📁</div>
                            <div className="dropzone-text">Kéo thả ảnh vào đây hoặc <strong>click để chọn file</strong></div>
                        </>
                    }
                </div>
            </div>

            {/* Person Image — shown for workflows that need it */}
            {needsPerson && (
                <div className="form-group">
                    <label>👤 Ảnh nhân vật (Person)</label>
                    <div className="dropzone" style={{ position: 'relative' }}>
                        <input type="file" accept="image/*" onChange={handlePersonUpload} style={{ position: 'absolute', inset: 0, opacity: 0, cursor: 'pointer' }} />
                        {personPreview
                            ? <div className="dropzone-preview"><img src={personPreview} alt="Person" /></div>
                            : <>
                                <div className="dropzone-icon">👤</div>
                                <div className="dropzone-text">Upload ảnh nhân vật <strong>(sẽ được ghép vào video)</strong></div>
                            </>
                        }
                    </div>
                </div>
            )}

            {/* Background Image — shown for workflows that need it */}
            {needsBg && (
                <div className="form-group">
                    <label>🏞️ Ảnh Background</label>
                    <div className="dropzone" style={{ position: 'relative' }}>
                        <input type="file" accept="image/*" onChange={handleBgUpload} style={{ position: 'absolute', inset: 0, opacity: 0, cursor: 'pointer' }} />
                        {bgPreview
                            ? <div className="dropzone-preview"><img src={bgPreview} alt="Background" /></div>
                            : <>
                                <div className="dropzone-icon">🏞️</div>
                                <div className="dropzone-text">Upload ảnh nền <strong>(background cho scene)</strong></div>
                            </>
                        }
                    </div>
                </div>
            )}

            {/* Config Grid */}
            <div className="form-row">
                <div className="form-group">
                    <label>AI Model</label>
                    <select className="form-select" value={model} onChange={e => handleModelChange(e.target.value)}>
                        <option value="kling-3.0">Kling 3.0 (I2V)</option>
                        <option value="kling-motion">Kling Motion (I2V)</option>
                        <option value="veo-3-fast">Veo 3 Fast (T2V/I2V/R2V)</option>
                    </select>
                </div>
                <div className="form-group">
                    <label>Chế độ</label>
                    <select className="form-select" value={mode} onChange={e => setMode(e.target.value)}>
                        {modeOptions.map(([val, label]) => <option key={val} value={val}>{label}</option>)}
                    </select>
                </div>
            </div>

            <div className="form-row">
                <div className="form-group">
                    <label>Chất lượng</label>
                    <select className="form-select" value={quality} onChange={e => setQuality(e.target.value)}>
                        <option value="1080p">1080p</option>
                        <option value="720p">720p</option>
                    </select>
                </div>
                <div className="form-group">
                    <label>Thời lượng (giây)</label>
                    <input type="number" className="form-input" value={duration} onChange={e => setDuration(e.target.value)} min="3" max="15" />
                </div>
            </div>

            <div className="form-row">
                <div className="form-group">
                    <label>Tỷ lệ khung hình</label>
                    <select className="form-select" value={ratio} onChange={e => setRatio(e.target.value)}>
                        <option value="9:16">9:16 (TikTok/Shorts)</option>
                        <option value="16:9">16:9 (YouTube)</option>
                        <option value="1:1">1:1 (Instagram)</option>
                    </select>
                </div>
                <div className="form-group">
                    <label>Tiêu đề Job</label>
                    <input type="text" className="form-input" placeholder="Tên video / mô tả ngắn" value={title} onChange={e => setTitle(e.target.value)} />
                </div>
            </div>

            {/* Prompt & Script */}
            <div className="form-group">
                <label>Prompt tạo Video *</label>
                <textarea className="form-textarea" rows="3" placeholder="Mô tả cảnh video cần tạo bằng tiếng Anh..." value={prompt} onChange={e => setPrompt(e.target.value)}></textarea>
            </div>

            <div className="form-group">
                <label>Kịch bản TTS (tiếng Việt, để trống nếu không cần)</label>
                <textarea className="form-textarea" rows="3" placeholder="Kịch bản đọc bằng giọng tiếng Việt..." value={script} onChange={e => setScript(e.target.value)}></textarea>
            </div>

            <button className="btn btn-success btn-lg w-full" style={{ marginTop: '0.5rem' }} disabled={submitting} onClick={handleSubmit}>
                {submitting && <span className="spinner"></span>}
                🚀 Đưa vào hàng đợi xử lý
            </button>
        </div>
    );
}

// =============================================
// Google Drive Tab Content
// =============================================

function DriveTabContent({ addToast, onImportedImages, nodeCount, nodeLabels }) {
    const [driveUrl, setDriveUrl] = useState('');
    const [loading, setLoading] = useState(false);
    const [driveData, setDriveData] = useState(null);
    const [selected, setSelected] = useState([]);
    const [importing, setImporting] = useState(false);
    const [importedImages, setImportedImages] = useState([]);
    const [targetNodeIdx, setTargetNodeIdx] = useState('auto');

    async function handlePreview() {
        if (!driveUrl.trim()) { addToast('Vui lòng dán link folder Google Drive', 'error'); return; }
        if (!driveUrl.includes('drive.google.com')) { addToast('Link không hợp lệ', 'error'); return; }
        setLoading(true);
        setDriveData(null);
        setSelected([]);
        setImportedImages([]);
        try {
            const res = await fetch('/api/drive/preview', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ folder_url: driveUrl.trim() }),
            });
            const data = await res.json();
            if (data.success) {
                setDriveData(data);
                addToast(`Tìm thấy ${data.total_images} ảnh — ${data.pending} chưa xử lý`, 'success');
            } else {
                addToast(data.detail || 'Không thể đọc folder', 'error');
            }
        } catch (e) {
            addToast('Lỗi kết nối server', 'error');
        } finally {
            setLoading(false);
        }
    }

    function toggleSelect(fileId) {
        setSelected(prev => prev.includes(fileId) ? prev.filter(id => id !== fileId) : [...prev, fileId]);
    }

    function selectAll() {
        if (!driveData) return;
        const pendingIds = driveData.images.filter(img => img.status !== 'done').map(img => img.drive_file_id);
        setSelected(pendingIds);
    }

    function deselectAll() {
        setSelected([]);
    }

    async function handleImport() {
        if (selected.length === 0) { addToast('Chọn ít nhất 1 ảnh', 'error'); return; }
        setImporting(true);
        try {
            const formData = new FormData();
            formData.append('folder_url', driveUrl.trim());
            formData.append('file_ids', selected.join(','));
            const res = await fetch('/api/drive/import', { method: 'POST', body: formData });
            const data = await res.json();
            if (data.success) {
                const successResults = (data.results || []).filter(r => r.success && r.image_url);
                addToast(`Import thành công ${successResults.length}/${data.total} ảnh`, 'success');
                const finalResults = successResults.map(r => ({ url: r.image_url, name: r.file_name || 'Drive Image', targetNodeIdx: targetNodeIdx }));
                setImportedImages(finalResults);
                // Auto pass all imported images to parent
                if (onImportedImages && finalResults.length > 0) {
                    onImportedImages(finalResults);
                }
                handlePreview(); // Refresh status
            } else {
                addToast(data.detail || 'Lỗi import', 'error');
            }
        } catch (e) {
            addToast('Lỗi kết nối', 'error');
        } finally {
            setImporting(false);
        }
    }

    const statusColors = { pending: { bg: '#eef4ff', color: '#155eef' }, done: { bg: '#e6f9f0', color: '#067647' }, processing: { bg: '#fff8e6', color: '#b54708' }, failed: { bg: '#fef3f2', color: '#b42318' } };
    const pendingCount = driveData ? driveData.images.filter(img => img.status !== 'done').length : 0;

    return (
        <div>
            <div className="form-group">
                <label>Link folder Google Drive</label>
                <div style={{ display: 'flex', gap: '0.75rem' }}>
                    <input type="text" className="form-input" placeholder="https://drive.google.com/drive/folders/xxxxx" value={driveUrl} onChange={e => setDriveUrl(e.target.value)} onKeyDown={e => e.key === 'Enter' && handlePreview()} style={{ flex: 1 }} id="drive-url-input" />
                    <button className="btn btn-primary" disabled={loading} onClick={handlePreview} id="drive-preview-btn">
                        {loading && <span className="spinner"></span>}
                        🔍 Preview
                    </button>
                </div>
                <div className="sheet-hint">Folder cần được share với email Service Account. Ảnh sau khi import sẽ được tự động gán vào các Node trong Workflow.</div>
            </div>

            {driveData && (
                <div>
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.75rem', flexWrap: 'wrap', gap: '0.5rem' }}>
                        <div>
                            <strong>📁 {driveData.folder_name}</strong>
                            <span className="text-muted" style={{ fontSize: '0.8rem', marginLeft: '0.5rem' }}>{driveData.total_images} ảnh · {driveData.pending} chưa xử lý · {driveData.done} đã xong</span>
                        </div>
                        <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
                            <button className="btn btn-outline btn-sm" onClick={selected.length === pendingCount ? deselectAll : selectAll}>
                                {selected.length === pendingCount && pendingCount > 0 ? '☐ Bỏ chọn tất cả' : `☑ Chọn tất cả (${pendingCount})`}
                            </button>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '0.25rem' }}>
                                <select className="form-select" style={{ fontSize: '0.8rem', padding: '0.2rem 1.5rem 0.2rem 0.5rem', width: 'auto', border: '1px solid var(--accent-secondary)' }} value={targetNodeIdx} onChange={e => setTargetNodeIdx(e.target.value)}>
                                    <option value="auto">Gán Auto</option>
                                    {Array.from({ length: Math.max(1, nodeCount || 1) }).map((_, i) => (
                                        <option key={i} value={i}>Vào Node {i + 1}</option>
                                    ))}
                                    {nodeCount < 10 && <option value={nodeCount}>Vào Node Mới</option>}
                                </select>
                                <button className="btn btn-success btn-sm" disabled={importing || selected.length === 0} onClick={handleImport} id="drive-import-btn">
                                    {importing && <span className="spinner"></span>}
                                    ⬇️ Import {selected.length} ảnh
                                </button>
                            </div>
                        </div>
                    </div>
                    <div className="drive-grid">
                        {driveData.images.map(img => {
                            const st = statusColors[img.status] || statusColors.pending;
                            const isSelected = selected.includes(img.drive_file_id);
                            return (
                                <div key={img.drive_file_id} className={`drive-img-card ${isSelected ? 'selected' : ''} ${img.status === 'done' ? 'done' : ''}`} onClick={() => img.status !== 'done' && toggleSelect(img.drive_file_id)}>
                                    {img.thumbnail_url ? <img className="drive-img-thumb" src={img.thumbnail_url} alt="" /> : <div className="drive-img-thumb" style={{ background: 'var(--bg-tertiary)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '2rem' }}>🖼️</div>}
                                    <div className="drive-img-name">{img.file_name}</div>
                                    <span className="drive-img-status" style={{ background: st.bg, color: st.color }}>{img.status === 'pending' ? '🟢' : img.status === 'done' ? '✅' : img.status === 'processing' ? '⚡' : '❌'} {img.status}</span>
                                    {isSelected && <span className="drive-img-check">✓</span>}
                                </div>
                            );
                        })}
                    </div>
                </div>
            )}

            {/* Imported images — assign to nodes */}
            {importedImages.length > 0 && (
                <div className="drive-imported-section">
                    <h4 style={{ margin: '1.25rem 0 0.75rem', color: 'var(--accent-secondary)', fontSize: '0.95rem' }}>
                        ✅ Đã import {importedImages.length} ảnh — Ảnh sẽ được gán tự động vào các Node theo thứ tự
                    </h4>
                    <div className="drive-imported-grid">
                        {importedImages.map((img, i) => (
                            <div key={i} className="drive-imported-item">
                                <img src={img.url} alt={img.name} className="drive-imported-thumb" />
                                <div className="drive-imported-label">
                                    <span className="drive-imported-node">Node {(img.targetNodeIdx === 'auto' ? i : parseInt(img.targetNodeIdx) + i) + 1}</span>
                                    <span className="drive-imported-name">{img.name}</span>
                                </div>
                            </div>
                        ))}
                    </div>
                    <div className="sheet-hint" style={{ marginTop: '0.5rem' }}>
                        💡 Chuyển sang tab "🔨 Tạo Workflow" hoặc "▶️ Chạy Workflow" để xem ảnh đã được gán vào các Node.
                    </div>
                </div>
            )}
        </div>
    );
}

// =============================================
// Workflow Builder Page (Luồng 1 + Luồng 2)
// =============================================

function defaultNode() {
    return { category: 'video', model: 'kling-3.0', mode: 'i2v', quality: '1080p', duration: 5, aspect_ratio: '9:16', prompt: '', script_text: '', image_url: '', resolution: '1k', negative_prompt: '' };
}

function WorkflowBuilderPage({ addToast, setLoading }) {
    const [activeTab, setActiveTab] = useState('drive');
    const [nodes, setNodes] = useState([defaultNode()]);
    const [running, setRunning] = useState(false);
    const [jobResult, setJobResult] = useState(null);
    const [showSave, setShowSave] = useState(false);
    const [saveName, setSaveName] = useState('');
    const [saveDesc, setSaveDesc] = useState('');
    const [saving, setSaving] = useState(false);
    const [savedWfs, setSavedWfs] = useState([]);
    const [selectedWf, setSelectedWf] = useState(null);
    const [runnerImages, setRunnerImages] = useState([]);
    const [runnerRunning, setRunnerRunning] = useState(false);
    const [runnerTitle, setRunnerTitle] = useState('');
    const [driveImages, setDriveImages] = useState([]);
    // --- Active jobs tracking (persists across F5 via localStorage) ---
    const [activeJobs, setActiveJobs] = useState([]);
    const activeJobsRef = useRef([]);

    useEffect(() => { activeJobsRef.current = activeJobs; }, [activeJobs]);

    // localStorage helpers
    const STORAGE_KEY = 'avf_active_job_ids';
    function _saveIds(ids) { try { localStorage.setItem(STORAGE_KEY, JSON.stringify(ids)); } catch(e) {} }
    function _loadIds() { try { return JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]'); } catch(e) { return []; } }
    function _addId(id) { const ids = _loadIds(); if (!ids.includes(id)) { ids.push(id); _saveIds(ids); } }
    function _removeId(id) { _saveIds(_loadIds().filter(x => x !== id)); }

    // Poll active jobs for node_statuses
    const pollActiveJobs = useCallback(async (jobIds) => {
        if (!jobIds || jobIds.length === 0) return;
        try {
            const results = await Promise.all(
                jobIds.map(id => fetch('/api/jobs/' + id).then(r => r.json()).catch(() => null))
            );
            const updated = [];
            results.forEach(res => {
                if (!res || !res.success) return;
                const job = res.job;
                updated.push(job);
                if (job.status !== 'queued' && job.status !== 'processing') {
                    _removeId(job.id);
                }
            });
            setActiveJobs(updated);
        } catch (e) { console.error('Poll error:', e); }
    }, []);

    // On mount: restore from localStorage + server
    useEffect(() => {
        async function restore() {
            const savedIds = _loadIds();
            try {
                const res = await fetch('/api/jobs/active');
                const data = await res.json();
                if (data.success && data.jobs) {
                    data.jobs.forEach(job => { if (!savedIds.includes(job.id)) savedIds.push(job.id); });
                }
            } catch (e) {}
            if (savedIds.length > 0) { _saveIds(savedIds); pollActiveJobs(savedIds); }
        }
        restore();
    }, []);

    // Poll interval
    useEffect(() => {
        const iv = setInterval(() => { const ids = _loadIds(); if (ids.length > 0) pollActiveJobs(ids); }, 5000);
        return () => clearInterval(iv);
    }, [pollActiveJobs]);

    function dismissJob(jobId) { _removeId(jobId); setActiveJobs(prev => prev.filter(j => j.id !== jobId)); }

    // Load saved workflows
    useEffect(() => {
        fetch('/api/custom-workflows').then(r => r.json()).then(data => {
            if (data.success) setSavedWfs(data.workflows);
        }).catch(() => {});
    }, [activeTab]);

    // Handle imported images from Drive
    function handleDriveImported(images) {
        setDriveImages(images);
        // Auto-assign to Builder nodes
        const startParam = images[0]?.targetNodeIdx || 'auto';
        setNodes(prev => {
            let updated = [...prev];
            let startIdx = 0;
            if (startParam !== 'auto') {
                startIdx = parseInt(startParam);
            }
            
            // Ensure enough nodes exist for all images
            while (updated.length < startIdx + images.length && updated.length < 10) {
                updated.push(defaultNode());
            }
            // Assign image URLs to nodes
            images.forEach((img, i) => {
                 if (startIdx + i < updated.length) {
                     updated[startIdx + i] = { ...updated[startIdx + i], image_url: img.url };
                 }
            });
            return updated;
        });
        // Also assign to Runner images if a workflow is selected
        if (selectedWf) {
            setRunnerImages(prev => {
                const updated = [...prev];
                images.forEach((img, i) => {
                    const idx = startParam === 'auto' ? i : parseInt(startParam) + i;
                    if (idx < updated.length) updated[idx] = img.url;
                });
                return updated;
            });
        }
        addToast(`✅ ${images.length} ảnh từ Drive đã được gán vào các Node`, 'success');
    }

    // --- Builder helpers ---
    function updateNode(idx, field, value) {
        setNodes(prev => prev.map((n, i) => i === idx ? { ...n, [field]: value } : n));
    }
    function removeNode(idx) {
        if (nodes.length <= 1) return;
        setNodes(prev => prev.filter((_, i) => i !== idx));
    }
    function addNode() {
        if (nodes.length >= 10) { addToast('Tối đa 10 nodes', 'error'); return; }
        setNodes(prev => [...prev, defaultNode()]);
    }

    async function handleUploadForNode(file, idx) {
        if (!file || !file.type.startsWith('image/')) { addToast('Chỉ chấp nhận file ảnh', 'error'); return; }
        const formData = new FormData();
        formData.append('file', file);
        try {
            const res = await fetch('/api/upload', { method: 'POST', body: formData });
            const data = await res.json();
            if (data.success) {
                updateNode(idx, 'image_url', data.url);
                addToast(`Ảnh Node ${idx + 1} uploaded`, 'success');
            }
        } catch (e) {
            addToast('Upload lỗi', 'error');
        }
    }

    async function runWorkflow() {
        if (!nodes[0].prompt.trim()) { addToast('Node 1 cần có Prompt', 'error'); return; }
        setRunning(true);
        setJobResult(null);
        try {
            const res = await fetch('/api/workflow-builder/run', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ title: `Workflow Builder (${nodes.length} nodes)`, nodes }),
            });
            const data = await res.json();
            if (data.success) {
                setJobResult(data.job);
                addToast(`Job #${data.job.id} đang xử lý (${nodes.length} nodes) 🚀`, 'success');
                // Track this job for progress panel
                _addId(data.job.id);
                setActiveJobs(prev => [...prev, data.job]);
            } else {
                addToast(data.detail || 'Lỗi chạy workflow', 'error');
            }
        } catch (e) {
            addToast('Lỗi kết nối', 'error');
        } finally {
            setRunning(false);
        }
    }

    async function saveWorkflow() {
        if (!saveName.trim()) { addToast('Nhập tên workflow', 'error'); return; }
        setSaving(true);
        try {
            const res = await fetch('/api/custom-workflows', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name: saveName.trim(), description: saveDesc.trim(), nodes }),
            });
            const data = await res.json();
            if (data.success) {
                addToast(`Workflow "${saveName}" đã lưu! ✅`, 'success');
                setShowSave(false);
                setSaveName('');
                setSaveDesc('');
            } else {
                addToast(data.detail || 'Lỗi lưu', 'error');
            }
        } catch (e) {
            addToast('Lỗi kết nối', 'error');
        } finally {
            setSaving(false);
        }
    }

    async function deleteWorkflow(wfId) {
        try {
            const res = await fetch(`/api/custom-workflows/${wfId}`, { method: 'DELETE' });
            const data = await res.json();
            if (data.success) {
                addToast('Đã xóa workflow', 'info');
                setSavedWfs(prev => prev.filter(w => w.id !== wfId));
                if (selectedWf && selectedWf.id === wfId) setSelectedWf(null);
            }
        } catch (e) {
            addToast('Lỗi xóa', 'error');
        }
    }

    // --- Runner helpers (Luồng 2) ---
    function selectSavedWf(wf) {
        setSelectedWf(wf);
        // Auto-assign Drive images to runner slots if available
        const images = new Array(wf.nodes.length).fill('');
        driveImages.forEach((img, i) => {
            if (i < images.length) images[i] = img.url;
        });
        setRunnerImages(images);
        setRunnerTitle('');
    }

    async function handleRunnerUpload(file, idx) {
        if (!file || !file.type.startsWith('image/')) { addToast('Chỉ chấp nhận file ảnh', 'error'); return; }
        const formData = new FormData();
        formData.append('file', file);
        try {
            const res = await fetch('/api/upload', { method: 'POST', body: formData });
            const data = await res.json();
            if (data.success) {
                setRunnerImages(prev => prev.map((img, i) => i === idx ? data.url : img));
                addToast(`Ảnh Node ${idx + 1} uploaded`, 'success');
            }
        } catch (e) {
            addToast('Upload lỗi', 'error');
        }
    }

    async function runSavedWf() {
        if (!selectedWf) return;
        setRunnerRunning(true);
        try {
            const res = await fetch(`/api/custom-workflows/${selectedWf.id}/run`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ title: runnerTitle || selectedWf.name, node_images: runnerImages }),
            });
            const data = await res.json();
            if (data.success) {
                addToast(`Job #${data.job.id} đang xử lý workflow "${selectedWf.name}" 🚀`, 'success');
                // Track this job for progress panel
                _addId(data.job.id);
                setActiveJobs(prev => [...prev, data.job]);
            } else {
                addToast(data.detail || 'Lỗi chạy workflow', 'error');
            }
        } catch (e) {
            addToast('Lỗi kết nối', 'error');
        } finally {
            setRunnerRunning(false);
        }
    }

    // --- Render Node Card ---
    function renderNodeCard(node, idx, editable = true) {
        const isFirst = idx === 0;
        const isImage = node.category === 'image';
        const modeOpts = node.model === 'veo-3-fast'
            ? [['t2v', 'Text-to-Video'], ['i2v', 'Image-to-Video']]
            : [['i2v', 'Image-to-Video']];

        return (
            <React.Fragment key={idx}>
                {idx > 0 && (
                    <div className="wf-node-connector">
                        <span className="arrow-down">⬇</span> Output Node {idx} → Input Node {idx + 1}
                    </div>
                )}
                <div className="wf-node">
                    <div className="wf-node-header">
                        <div className="wf-node-title">
                            <span className="wf-node-num">{idx + 1}</span>
                            Node {idx + 1}
                        </div>
                        {editable && !isFirst && <button className="wf-node-remove" onClick={() => removeNode(idx)} title="Xóa node">🗑️</button>}
                    </div>

                    {/* Category Selection */}
                    <div className="form-group">
                        <label>Loại Node</label>
                        {editable ? (
                            <div style={{ display: 'flex', gap: '0.5rem' }}>
                                <button className={`btn btn-sm ${!isImage ? 'btn-primary' : 'btn-outline'}`} onClick={() => { updateNode(idx, 'category', 'video'); updateNode(idx, 'model', 'kling-3.0'); updateNode(idx, 'aspect_ratio', '9:16'); }}>🎬 Tạo Video</button>
                                <button className={`btn btn-sm ${isImage ? 'btn-primary' : 'btn-outline'}`} onClick={() => { updateNode(idx, 'category', 'image'); updateNode(idx, 'model', 'nano-banana-pro'); updateNode(idx, 'aspect_ratio', '1:1'); }}>🖼️ Tạo Ảnh</button>
                            </div>
                        ) : (
                            <div><strong>{isImage ? '🖼️ Tạo Ảnh' : '🎬 Tạo Video'}</strong></div>
                        )}
                    </div>

                    {!isFirst && (
                        <div className="wf-auto-input">
                            📥 Input tự động: Output {isImage ? 'ảnh' : 'video'} từ Node {idx}
                        </div>
                    )}

                    {/* Image Upload */}
                    <div className="form-group">
                        <label>🖼️ {isFirst ? 'Ảnh nguồn' : 'Ảnh tham khảo bổ sung'}</label>
                        {editable ? (
                            <div>
                                <div className="dropzone" style={{ padding: '1rem', position: 'relative' }}>
                                    <input type="file" accept="image/*" onChange={e => handleUploadForNode(e.target.files[0], idx)} style={{ position: 'absolute', inset: 0, opacity: 0, cursor: 'pointer' }} />
                                    {node.image_url
                                        ? <div className="dropzone-preview">
                                            <img src={node.image_url} alt="" />
                                            <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '0.25rem' }}>✅ {node.image_url.includes('r2.') || node.image_url.includes('cloudflare') ? 'Từ Drive' : 'Đã upload'}</div>
                                          </div>
                                        : <div className="dropzone-text">Click để upload ảnh hoặc import từ tab Google Drive</div>
                                    }
                                </div>
                                {node.image_url && (
                                    <button className="btn btn-outline btn-sm" style={{ marginTop: '0.35rem', fontSize: '0.75rem' }} onClick={() => updateNode(idx, 'image_url', '')}>✕ Xóa ảnh</button>
                                )}
                            </div>
                        ) : (
                            <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>Ảnh sẽ được upload khi chạy</div>
                        )}
                    </div>

                    {/* Config */}
                    <div className="form-row">
                        <div className="form-group">
                            <label>AI Model</label>
                            {editable ? (
                                <select className="form-select" value={node.model} onChange={e => { updateNode(idx, 'model', e.target.value); if (e.target.value === 'veo-3-fast') updateNode(idx, 'mode', 't2v'); else if (!isImage) updateNode(idx, 'mode', 'i2v'); }}>
                                    {!isImage ? (
                                        <>
                                            <option value="kling-3.0">Kling 3.0</option>
                                            <option value="kling-motion">Kling Motion</option>
                                            <option value="veo-3-fast">Veo 3 Fast</option>
                                        </>
                                    ) : (
                                        <>
                                            <option value="nano-banana-pro">Nano Banana Pro</option>
                                            <option value="nano-banana-2">Nano Banana 2</option>
                                        </>
                                    )}
                                </select>
                            ) : <div><code style={{ color: 'var(--accent-primary)' }}>{node.model}</code></div>}
                        </div>
                        
                        {!isImage && (
                            <div className="form-group">
                                <label>Chế độ</label>
                                {editable ? (
                                    <select className="form-select" value={node.mode} onChange={e => updateNode(idx, 'mode', e.target.value)}>
                                        {modeOpts.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                                    </select>
                                ) : <div><code>{node.mode}</code></div>}
                            </div>
                        )}
                    </div>

                    {!isImage ? (
                        <div className="form-row">
                            <div className="form-group">
                                <label>Chất lượng</label>
                                {editable ? <select className="form-select" value={node.quality} onChange={e => updateNode(idx, 'quality', e.target.value)}><option value="1080p">1080p</option><option value="720p">720p</option></select> : <div><code>{node.quality}</code></div>}
                            </div>
                            <div className="form-group">
                                <label>Thời lượng (giây)</label>
                                {editable ? <input type="number" className="form-input" value={node.duration} onChange={e => updateNode(idx, 'duration', parseInt(e.target.value) || 5)} min="3" max="15" /> : <div><code>{node.duration}s</code></div>}
                            </div>
                        </div>
                    ) : (
                        <div className="form-row">
                            <div className="form-group">
                                <label>Độ phân giải</label>
                                {editable ? <select className="form-select" value={node.resolution} onChange={e => updateNode(idx, 'resolution', e.target.value)}><option value="1k">1K</option><option value="2k">2K</option><option value="4k">4K</option></select> : <div><code>{node.resolution}</code></div>}
                            </div>
                        </div>
                    )}
                    
                    <div className="form-group">
                        <label>Tỷ lệ</label>
                        {editable ? (
                            <select className="form-select" value={node.aspect_ratio} onChange={e => updateNode(idx, 'aspect_ratio', e.target.value)}>
                                <option value="1:1">1:1</option>
                                <option value="16:9">16:9 (YouTube)</option>
                                <option value="9:16">9:16 (TikTok)</option>
                                {isImage && node.model === 'nano-banana-2' && (
                                    <>
                                        <option value="4:3">4:3</option>
                                        <option value="3:4">3:4</option>
                                    </>
                                )}
                            </select>
                        ) : <div><code>{node.aspect_ratio}</code></div>}
                    </div>

                    <div className="form-group">
                        <label>Prompt tạo {isImage ? 'Ảnh' : 'Video'} {isFirst ? '*' : ''}</label>
                        {editable ? <textarea className="form-textarea" rows="2" placeholder={`Mô tả ${isImage ? 'ảnh' : 'cảnh video'}...`} value={node.prompt} onChange={e => updateNode(idx, 'prompt', e.target.value)}></textarea> : <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', background: 'var(--bg-tertiary)', padding: '0.5rem 0.75rem', borderRadius: '8px' }}>{node.prompt || <span className="text-muted">—</span>}</div>}
                    </div>

                    {isImage && (
                        <div className="form-group">
                            <label>Negative Prompt</label>
                            {editable ? <textarea className="form-textarea" rows="2" placeholder="Những gì không muốn xuất hiện..." value={node.negative_prompt} onChange={e => updateNode(idx, 'negative_prompt', e.target.value)}></textarea> : <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', background: 'var(--bg-tertiary)', padding: '0.5rem 0.75rem', borderRadius: '8px' }}>{node.negative_prompt || <span className="text-muted">—</span>}</div>}
                        </div>
                    )}

                    <div className="form-group">
                        <label>Kịch bản TTS {isImage && '(Chỉ dùng cho bước merge video)'}</label>
                        {editable ? <textarea className="form-textarea" rows="2" placeholder="Kịch bản đọc (tuỳ chọn)..." value={node.script_text} onChange={e => updateNode(idx, 'script_text', e.target.value)}></textarea> : <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>{node.script_text || '(không có)'}</div>}
                    </div>
                </div>
            </React.Fragment>
        );
    }

    return (
        <div className="container" style={{ paddingTop: '1.5rem', paddingBottom: '3rem' }}>
            <div className="page-header">
                <h1>🔨 Workflow Builder</h1>
                <p className="subtitle">Tạo workflow multi-node hoặc chạy workflow đã lưu</p>
            </div>

            <div className="tab-headers" style={{ marginBottom: '1.5rem' }}>
                <button className={`tab-btn ${activeTab === 'drive' ? 'active' : ''}`} onClick={() => setActiveTab('drive')}>📁 Google Drive</button>
                <button className={`tab-btn ${activeTab === 'builder' ? 'active' : ''}`} onClick={() => setActiveTab('builder')}>
                    🔨 Tạo Workflow
                    {driveImages.length > 0 && <span className="tab-badge">{driveImages.length} ảnh</span>}
                </button>
                <button className={`tab-btn ${activeTab === 'runner' ? 'active' : ''}`} onClick={() => setActiveTab('runner')}>▶️ Chạy Workflow đã lưu ({savedWfs.length})</button>
            </div>

            {/* ===== Tab: Google Drive ===== */}
            {/* ===== Workflow Progress Panel ===== */}
            {activeJobs.length > 0 && (
                <div className="card" style={{ borderLeft: '4px solid var(--accent-primary)', marginBottom: '1.5rem' }}>
                    <div className="card-header">
                        <span className="phase-badge" style={{ background: 'linear-gradient(135deg, #6366f1, #8b5cf6)' }}>Live</span>
                        <h3>{'⚡'} Workflow Progress ({activeJobs.filter(j => j.status === 'queued' || j.status === 'processing').length} {'đang chạy'})</h3>
                    </div>
                    {activeJobs.map(job => {
                        const isActive = job.status === 'queued' || job.status === 'processing';
                        const nodeStatuses = job.node_statuses || [];
                        const totalN = job.total_nodes || nodeStatuses.length || 1;
                        const completedN = nodeStatuses.filter(n => n.status === 'completed').length;
                        const progressPct = totalN > 0 ? Math.round((completedN / totalN) * 100) : 0;
                        const isFinalizing = job.status === 'processing' && completedN === totalN;

                        const statusLabel = job.status === 'queued' ? '⏳ Đang chờ...'
                            : job.status === 'processing' ? (isFinalizing ? '⚙️ Đang hoàn tất...' : '⚡ Node ' + (completedN + 1) + '/' + totalN)
                            : job.status === 'rendered' ? 'Rendered'
                            : job.status === 'pending_review' ? '✅ Hoàn tất!'
                            : job.status === 'failed' ? '❌ Thất bại'
                            : job.status;

                        return (
                            <div key={job.id} style={{
                                padding: '1rem 1.25rem',
                                borderBottom: '1px solid var(--border-light)',
                                background: isActive ? 'rgba(99, 102, 241, 0.03)' : 'transparent',
                            }}>
                                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.5rem', flexWrap: 'wrap', gap: '0.5rem' }}>
                                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                                        <strong style={{ color: 'var(--text-primary)' }}>#{job.id}</strong>
                                        <span style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>{job.title || 'Workflow'}</span>
                                        <span className={`badge badge-${job.status}`}>{statusLabel}</span>
                                    </div>
                                    <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
                                        {job.final_video_url && <a href={job.final_video_url} target="_blank" className="btn btn-success btn-sm">🎬 Xem video</a>}
                                        {!isActive && <button className="btn btn-outline btn-sm" onClick={() => dismissJob(job.id)}>✕</button>}
                                    </div>
                                </div>
                                {/* Progress bar */}
                                <div style={{ background: 'var(--bg-tertiary)', borderRadius: 8, height: 6, marginBottom: '0.5rem', overflow: 'hidden' }}>
                                    <div style={{
                                        height: '100%',
                                        width: job.status === 'pending_review' || job.status === 'rendered' ? '100%' : progressPct + '%',
                                        background: job.status === 'failed' ? 'var(--accent-danger)' : 'linear-gradient(90deg, var(--accent-primary), var(--accent-secondary))',
                                        borderRadius: 8,
                                        transition: 'width 0.5s ease',
                                    }}></div>
                                </div>
                                {/* Node status chips */}
                                {nodeStatuses.length > 0 && (
                                    <div style={{ display: 'flex', gap: '0.35rem', flexWrap: 'wrap' }}>
                                        {nodeStatuses.map((ns, idx) => {
                                            const chipIcon = ns.status === 'completed' ? '✅'
                                                : ns.status === 'processing' ? '⚡'
                                                : ns.status === 'failed' ? '❌' : '⏳';
                                            const chipBg = ns.status === 'completed' ? 'rgba(16, 185, 129, 0.1)'
                                                : ns.status === 'processing' ? 'rgba(99, 102, 241, 0.1)'
                                                : ns.status === 'failed' ? 'rgba(239, 68, 68, 0.1)' : 'rgba(148, 163, 184, 0.1)';
                                            const chipColor = ns.status === 'completed' ? '#059669'
                                                : ns.status === 'processing' ? '#4f46e5'
                                                : ns.status === 'failed' ? '#dc2626' : '#94a3b8';
                                            return (
                                                <div key={idx} style={{
                                                    display: 'inline-flex', alignItems: 'center', gap: '0.2rem',
                                                    padding: '0.15rem 0.5rem', borderRadius: 12, fontSize: '0.75rem',
                                                    background: chipBg, color: chipColor, fontWeight: 500,
                                                    border: ns.status === 'processing' ? '1px solid rgba(99,102,241,0.3)' : 'none',
                                                    animation: ns.status === 'processing' ? 'pulse 2s ease-in-out infinite' : 'none',
                                                }}>
                                                    {chipIcon} Node {ns.node}
                                                    {ns.status === 'completed' && ns.thumbnail_url && (
                                                        <img src={ns.thumbnail_url} alt="" style={{ width: 16, height: 16, borderRadius: 3, objectFit: 'cover', marginLeft: 2 }} />
                                                    )}
                                                </div>
                                            );
                                        })}
                                    </div>
                                )}
                            </div>
                        );
                    })}
                </div>
            )}

            <div className="card" style={{ display: activeTab === 'drive' ? 'block' : 'none' }}>
                <div className="card-header">
                    <span className="phase-badge" style={{ background: 'linear-gradient(135deg, #4285f4, #34a853)' }}>Drive</span>
                    <h3>📁 Lấy ảnh từ Google Drive</h3>
                </div>
                <DriveTabContent
                    addToast={addToast}
                    onImportedImages={handleDriveImported}
                    nodeCount={nodes.length}
                />
                {driveImages.length > 0 && (
                    <div style={{ marginTop: '1rem', padding: '0.75rem 1rem', background: 'linear-gradient(135deg, rgba(66,133,244,0.08), rgba(52,168,83,0.08))', borderRadius: 'var(--radius-lg)', border: '1px solid rgba(66,133,244,0.2)' }}>
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '0.5rem' }}>
                            <span style={{ fontSize: '0.85rem', color: 'var(--text-primary)' }}>✅ <strong>{driveImages.length}</strong> ảnh đã sẵn sàng cho Workflow</span>
                            <div style={{ display: 'flex', gap: '0.5rem' }}>
                                <button className="btn btn-primary btn-sm" onClick={() => setActiveTab('builder')}>🔨 Tạo Workflow mới</button>
                                <button className="btn btn-success btn-sm" onClick={() => setActiveTab('runner')} disabled={savedWfs.length === 0}>▶️ Chạy Workflow có sẵn</button>
                            </div>
                        </div>
                    </div>
                )}
            </div>

            {/* ===== Luồng 1: Builder ===== */}
            <div className="card" style={{ display: activeTab === 'builder' ? 'block' : 'none' }}>
                <div className="card-header">
                    <span className="phase-badge">Builder</span>
                    <h3>Tạo workflow mới</h3>
                </div>

                {nodes.map((node, idx) => renderNodeCard(node, idx, true))}

                <button className="wf-add-node-btn" onClick={addNode}>➕ Thêm Node</button>

                <div className="wf-actions">
                    <button className="btn btn-primary btn-lg" style={{ flex: 1 }} disabled={running} onClick={runWorkflow}>
                        {running && <span className="spinner"></span>}
                        ▶️ Chạy Workflow ({nodes.length} nodes)
                    </button>
                    <button className="btn btn-success btn-lg" onClick={() => setShowSave(true)}>
                        💾 Lưu Workflow
                    </button>
                </div>

                {jobResult && (
                    <div className="result-box show" style={{ marginTop: '1rem' }}>
                        <h3 style={{ color: 'var(--accent-secondary)', fontSize: '0.95rem' }}>✅ Job #{jobResult.id} đã được tạo</h3>
                        <p style={{ color: 'var(--text-muted)', fontSize: '0.85rem' }}>Trạng thái: <span className={`badge badge-${jobResult.status}`}>{jobResult.status}</span> — Kiểm tra trong trang Dashboard.</p>
                    </div>
                )}
            </div>

            {/* ===== Luồng 2: Runner ===== */}
            <div style={{ display: activeTab === 'runner' ? 'block' : 'none' }}>
                    <div className="card">
                        <div className="card-header">
                            <span className="phase-badge phase-badge-merge">Runner</span>
                            <h3>Chọn Workflow đã lưu</h3>
                        </div>

                        {savedWfs.length === 0 ? (
                            <div style={{ textAlign: 'center', padding: '2rem', color: 'var(--text-muted)' }}>
                                Chưa có workflow nào. Tạo workflow ở tab "Tạo Workflow" trước.
                            </div>
                        ) : (
                            <div className="wf-selector-grid">
                                {savedWfs.map(wf => (
                                    <div key={wf.id} className={`wf-selector-card ${selectedWf && selectedWf.id === wf.id ? 'selected' : ''}`} onClick={() => selectSavedWf(wf)}>
                                        <h4>⚡ {wf.name}</h4>
                                        {wf.description && <div className="wf-desc">{wf.description}</div>}
                                        <div className="wf-meta">
                                            <span>📊 {wf.node_count} nodes</span>
                                            <span>📅 {formatTime(wf.created_at)}</span>
                                        </div>
                                        <button className="btn btn-danger btn-sm" style={{ marginTop: '0.5rem' }} onClick={e => { e.stopPropagation(); deleteWorkflow(wf.id); }}>🗑️ Xóa</button>
                                    </div>
                                ))}
                            </div>
                        )}
                    </div>

                    {selectedWf && (
                        <div className="card">
                            <div className="card-header">
                                <span className="phase-badge">Config</span>
                                <h3>⚡ {selectedWf.name} — Upload ảnh cho các nodes</h3>
                            </div>

                            <div className="form-group">
                                <label>Tiêu đề Job</label>
                                <input type="text" className="form-input" placeholder={selectedWf.name} value={runnerTitle} onChange={e => setRunnerTitle(e.target.value)} />
                            </div>

                            {selectedWf.nodes.map((node, idx) => (
                                <div key={idx} className="wf-runner-node">
                                    <div className="wf-runner-node-header">
                                        <span className="wf-node-num">{idx + 1}</span>
                                        <strong>Node {idx + 1}</strong>
                                    </div>
                                    <div className="wf-runner-node-config">
                                        <code>{node.model}</code> · <code>{node.mode}</code> · <code>{node.quality}</code> · <code>{node.duration}s</code> · <code>{node.aspect_ratio}</code>
                                    </div>
                                    {node.prompt && <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '0.5rem' }}>Prompt: {(node.prompt || '').substring(0, 100)}{(node.prompt || '').length > 100 ? '...' : ''}</div>}

                                    {idx > 0 && <div className="wf-auto-input" style={{ marginBottom: '0.5rem' }}>📥 Auto: Output từ Node {idx}</div>}

                                    <div className="form-group" style={{ marginBottom: 0 }}>
                                        <label>🖼️ {idx === 0 ? 'Ảnh nguồn' : 'Ảnh bổ sung'}</label>
                                        <div className="dropzone" style={{ padding: '0.75rem', position: 'relative' }}>
                                            <input type="file" accept="image/*" onChange={e => handleRunnerUpload(e.target.files[0], idx)} style={{ position: 'absolute', inset: 0, opacity: 0, cursor: 'pointer' }} />
                                            {runnerImages[idx]
                                                ? <div className="dropzone-preview">
                                                    <img src={runnerImages[idx]} alt="" style={{ maxHeight: '80px' }} />
                                                    <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>✅ {driveImages[idx] && runnerImages[idx] === driveImages[idx].url ? 'Từ Drive' : 'Đã upload'}</div>
                                                  </div>
                                                : <div className="dropzone-text" style={{ fontSize: '0.8rem' }}>Click upload ảnh hoặc import từ tab Drive</div>
                                            }
                                        </div>
                                        {runnerImages[idx] && (
                                            <button className="btn btn-outline btn-sm" style={{ marginTop: '0.35rem', fontSize: '0.75rem' }} onClick={() => setRunnerImages(prev => prev.map((img, i) => i === idx ? '' : img))}>✕ Xóa ảnh</button>
                                        )}
                                    </div>
                                </div>
                            ))}

                            <button className="btn btn-success btn-lg w-full" style={{ marginTop: '0.75rem' }} disabled={runnerRunning} onClick={runSavedWf}>
                                {runnerRunning && <span className="spinner"></span>}
                                🚀 Tạo Video
                            </button>
                        </div>
                    )}
            </div>

            {/* Save Modal */}
            <div className={`save-modal-overlay ${showSave ? 'show' : ''}`} onClick={() => setShowSave(false)}>
                <div className="save-modal" onClick={e => e.stopPropagation()}>
                    <h3 style={{ marginBottom: '1rem' }}>💾 Lưu Workflow</h3>
                    <div className="form-group">
                        <label>Tên Workflow *</label>
                        <input type="text" className="form-input" placeholder="VD: Cinematic Product Showcase" value={saveName} onChange={e => setSaveName(e.target.value)} autoFocus />
                    </div>
                    <div className="form-group">
                        <label>Mô tả (tuỳ chọn)</label>
                        <textarea className="form-textarea" rows="2" placeholder="Mô tả workflow..." value={saveDesc} onChange={e => setSaveDesc(e.target.value)}></textarea>
                    </div>
                    <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: '1rem' }}>Workflow sẽ lưu cấu hình {nodes.length} node(s). Ảnh sẽ không được lưu — bạn sẽ upload ảnh mới khi chạy lại.</div>
                    <div style={{ display: 'flex', gap: '0.75rem', justifyContent: 'flex-end' }}>
                        <button className="btn btn-outline" onClick={() => setShowSave(false)}>Hủy</button>
                        <button className="btn btn-success" disabled={saving} onClick={saveWorkflow}>
                            {saving && <span className="spinner"></span>}
                            💾 Lưu
                        </button>
                    </div>
                </div>
            </div>
        </div>
    );
}

//
// Jobs Table (Live Dashboard)
// =============================================

function JobsTable({ refreshKey }) {
    const [jobs, setJobs] = useState([]);
    const [filter, setFilter] = useState('');

    const loadJobs = useCallback(async () => {
        const url = filter ? `/api/jobs?status=${filter}&limit=50` : '/api/jobs?limit=50';
        try {
            const res = await fetch(url);
            const data = await res.json();
            if (data.success) setJobs(data.jobs);
        } catch (e) {
            console.error('Failed to load jobs:', e);
        }
    }, [filter]);

    useEffect(() => { loadJobs(); }, [loadJobs, refreshKey]);
    useEffect(() => { const id = setInterval(loadJobs, 8000); return () => clearInterval(id); }, [loadJobs]);

    return (
        <div className="card" id="jobs-card">
            <div className="card-header">
                <span className="phase-badge">Live</span>
                <h3>📊 Danh sách Jobs</h3>
                <button className="btn btn-outline btn-sm" onClick={loadJobs}>↻ Refresh</button>
            </div>

            <div style={{ marginBottom: '1rem' }}>
                <select className="form-select" style={{ maxWidth: 200 }} value={filter} onChange={e => setFilter(e.target.value)}>
                    <option value="">Tất cả</option>
                    <option value="queued">Queued</option>
                    <option value="processing">Processing</option>
                    <option value="rendered">Rendered</option>
                    <option value="pending_review">Pending Review</option>
                    <option value="approved">Approved</option>
                    <option value="failed">Failed</option>
                    <option value="rejected">Rejected</option>
                </select>
            </div>

            <div style={{ overflowX: 'auto' }}>
                <table className="data-table">
                    <thead>
                        <tr>
                            <th>ID</th>
                            <th>Tiêu đề</th>
                            <th>Model</th>
                            <th>Workflow</th>
                            <th>Trạng thái</th>
                            <th>Thời gian</th>
                            <th>Hành động</th>
                        </tr>
                    </thead>
                    <tbody>
                        {jobs.length === 0 ? (
                            <tr>
                                <td colSpan="7" className="text-center text-muted" style={{ padding: '2rem' }}>
                                    Chưa có job nào
                                </td>
                            </tr>
                        ) : jobs.map(job => (
                            <tr key={job.id}>
                                <td><strong style={{ color: 'var(--text-primary)' }}>#{job.id}</strong></td>
                                <td className="job-title">{job.title || '—'}</td>
                                <td><code className="font-mono" style={{ color: 'var(--accent-primary)' }}>{job.model}</code></td>
                                <td><code className="font-mono" style={{ color: 'var(--accent-secondary)', fontSize: '0.75rem' }}>{job.workflow_id || 'default'}</code></td>
                                <td><span className={`badge badge-${job.status}`}>{job.status}</span></td>
                                <td className="job-time">{formatTime(job.created_at)}</td>
                                <td>
                                    {job.final_video_url && <a href={job.final_video_url} target="_blank" className="btn btn-outline btn-sm">🎥 Xem</a>}
                                    {job.raw_video_url && !job.final_video_url && <a href={job.raw_video_url} target="_blank" className="btn btn-outline btn-sm">Raw</a>}
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
        </div>
    );
}

// =============================================
// Post-Production: Merge Videos + TikTok Audio
// =============================================

function MergePanel({ addToast }) {
    const [completedJobs, setCompletedJobs] = useState([]);
    const [selectedIds, setSelectedIds] = useState([]);
    const [tiktokUrl, setTiktokUrl] = useState('');
    const [mergeId, setMergeId] = useState(null);
    const [mergeStatus, setMergeStatus] = useState(null);
    const [merging, setMerging] = useState(false);
    const [mergeResult, setMergeResult] = useState(null);
    const [dragIdx, setDragIdx] = useState(null);

    // Load completed jobs that have video URLs
    useEffect(() => {
        async function load() {
            try {
                const res = await fetch('/api/jobs?limit=50');
                const data = await res.json();
                if (data.success) {
                    const withVideo = data.jobs.filter(j => j.raw_video_url || j.final_video_url);
                    setCompletedJobs(withVideo);
                }
            } catch (e) { console.error(e); }
        }
        load();
        const id = setInterval(load, 15000);
        return () => clearInterval(id);
    }, []);

    // Poll merge status
    useEffect(() => {
        if (!mergeId) return;
        const poll = setInterval(async () => {
            try {
                const res = await fetch(`/api/merge/${mergeId}`);
                const data = await res.json();
                if (data.success) {
                    setMergeStatus(data.merge.status);
                    if (data.merge.status === 'done') {
                        setMergeResult(data.merge);
                        setMerging(false);
                        addToast('Ghép video hoàn tất! 🎬', 'success');
                        clearInterval(poll);
                    } else if (data.merge.status === 'failed') {
                        setMerging(false);
                        addToast(data.merge.error_message || 'Ghép video thất bại', 'error');
                        clearInterval(poll);
                    }
                }
            } catch (e) { console.error(e); }
        }, 3000);
        return () => clearInterval(poll);
    }, [mergeId]);

    function toggleSelect(jobId) {
        setSelectedIds(prev => {
            if (prev.includes(jobId)) return prev.filter(id => id !== jobId);
            if (prev.length >= 5) { addToast('Tối đa 5 video', 'error'); return prev; }
            return [...prev, jobId];
        });
    }

    function moveItem(fromIdx, toIdx) {
        setSelectedIds(prev => {
            const arr = [...prev];
            const [item] = arr.splice(fromIdx, 1);
            arr.splice(toIdx, 0, item);
            return arr;
        });
    }

    function handleDragStart(e, idx) {
        setDragIdx(idx);
        e.dataTransfer.effectAllowed = 'move';
    }
    function handleDragOver(e, idx) {
        e.preventDefault();
        e.dataTransfer.dropEffect = 'move';
    }
    function handleDrop(e, toIdx) {
        e.preventDefault();
        if (dragIdx !== null && dragIdx !== toIdx) moveItem(dragIdx, toIdx);
        setDragIdx(null);
    }

    async function handleMerge() {
        if (selectedIds.length === 0) { addToast('Chọn ít nhất 1 video', 'error'); return; }
        setMerging(true);
        setMergeResult(null);
        setMergeStatus('queued');
        try {
            const res = await fetch('/api/merge', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    job_ids: selectedIds,
                    tiktok_url: tiktokUrl.trim() || null,
                }),
            });
            const data = await res.json();
            if (data.success) {
                setMergeId(data.merge.id);
                addToast(`Merge job #${data.merge.id} đang xử lý...`, 'info');
            } else {
                addToast(data.detail || 'Không thể tạo merge job', 'error');
                setMerging(false);
                setMergeStatus(null);
            }
        } catch (e) {
            addToast('Lỗi kết nối server', 'error');
            setMerging(false);
            setMergeStatus(null);
        }
    }

    function resetMerge() {
        setSelectedIds([]);
        setTiktokUrl('');
        setMergeId(null);
        setMergeStatus(null);
        setMergeResult(null);
        setMerging(false);
    }

    const statusLabels = {
        queued: '⏳ Đang chờ...',
        extracting_audio: '🎵 Trích xuất audio TikTok...',
        downloading: '⬇️ Tải video nguồn...',
        merging: '🎬 Đang ghép video + audio...',
        uploading: '☁️ Đang upload kết quả...',
        done: '✅ Hoàn tất!',
        failed: '❌ Thất bại',
    };

    const selectedJobs = selectedIds.map(id => completedJobs.find(j => j.id === id)).filter(Boolean);

    return (
        <div className="card" id="merge-card">
            <div className="card-header">
                <span className="phase-badge phase-badge-merge">Phase 5</span>
                <h3>🎬 Post-Production (Ghép Video)</h3>
            </div>

            {/* Video Selector */}
            <div className="form-group">
                <label>Chọn video để ghép (tối đa 5, nhấn để chọn)</label>
                <div className="merge-video-grid">
                    {completedJobs.length === 0 ? (
                        <div className="merge-empty">Chưa có video nào hoàn thành. Tạo video ở Phase 1-2 trước.</div>
                    ) : completedJobs.map(job => (
                        <div
                            key={job.id}
                            className={`merge-video-card ${selectedIds.includes(job.id) ? 'selected' : ''}`}
                            onClick={() => toggleSelect(job.id)}
                        >
                            <div className="merge-video-thumb">
                                {job.thumbnail_url
                                    ? <img src={job.thumbnail_url} alt="" />
                                    : <div className="merge-thumb-placeholder">🎥</div>
                                }
                                {selectedIds.includes(job.id) && (
                                    <div className="merge-check">
                                        <span>{selectedIds.indexOf(job.id) + 1}</span>
                                    </div>
                                )}
                            </div>
                            <div className="merge-video-info">
                                <div className="merge-video-title">#{job.id} {(job.title || '').slice(0, 30)}</div>
                                <div className="merge-video-meta">{job.model} · {formatTime(job.created_at)}</div>
                            </div>
                        </div>
                    ))}
                </div>
            </div>

            {/* Selected Order (Drag & Drop) */}
            {selectedIds.length > 0 && (
                <div className="form-group">
                    <label>Thứ tự ghép (kéo thả để sắp xếp)</label>
                    <div className="merge-order-list">
                        {selectedJobs.map((job, idx) => (
                            <div
                                key={job.id}
                                className={`merge-order-item ${dragIdx === idx ? 'dragging' : ''}`}
                                draggable
                                onDragStart={(e) => handleDragStart(e, idx)}
                                onDragOver={(e) => handleDragOver(e, idx)}
                                onDrop={(e) => handleDrop(e, idx)}
                                onDragEnd={() => setDragIdx(null)}
                            >
                                <span className="merge-drag-handle">⠿</span>
                                <span className="merge-order-num">{idx + 1}</span>
                                <span className="merge-order-title">#{job.id} — {(job.title || 'Video').slice(0, 40)}</span>
                                <button className="merge-order-remove" onClick={(e) => { e.stopPropagation(); toggleSelect(job.id); }}>✕</button>
                            </div>
                        ))}
                    </div>
                </div>
            )}

            {/* TikTok URL */}
            <div className="form-group">
                <label>Link TikTok (trích xuất âm thanh)</label>
                <div className="input-group">
                    <span className="input-icon">🎵</span>
                    <input
                        type="text"
                        className="form-input"
                        placeholder="https://www.tiktok.com/@user/video/1234567890..."
                        value={tiktokUrl}
                        onChange={e => setTiktokUrl(e.target.value)}
                        disabled={merging}
                    />
                </div>
                <div className="form-hint">Âm thanh từ TikTok sẽ thay thế hoàn toàn audio gốc của video</div>
            </div>

            {/* Action Button */}
            <button
                className={`btn btn-lg w-full ${mergeResult ? 'btn-outline' : 'btn-accent'}`}
                onClick={mergeResult ? resetMerge : handleMerge}
                disabled={merging || (selectedIds.length === 0 && !mergeResult)}
                style={{ marginTop: '0.5rem' }}
            >
                {merging && <span className="spinner"></span>}
                {mergeResult ? '🔄 Ghép video mới' : `🎬 Ghép ${selectedIds.length} video`}
            </button>

            {/* Merge Status */}
            {mergeStatus && mergeStatus !== 'done' && mergeStatus !== 'failed' && (
                <div className="merge-status-bar">
                    <div className="sheet-progress-bar">
                        <div className="sheet-progress-fill" style={{
                            width: mergeStatus === 'queued' ? '10%'
                                : mergeStatus === 'extracting_audio' ? '30%'
                                : mergeStatus === 'downloading' ? '50%'
                                : mergeStatus === 'merging' ? '75%'
                                : mergeStatus === 'uploading' ? '90%' : '100%'
                        }}></div>
                    </div>
                    <div className="sheet-progress-text">{statusLabels[mergeStatus] || mergeStatus}</div>
                </div>
            )}

            {/* Merge Result */}
            {mergeResult && mergeResult.merged_video_url && (
                <div className="merge-result">
                    <div className="merge-result-header">
                        <h4>✅ Video đã ghép xong</h4>
                        <a href={mergeResult.merged_video_url} target="_blank" download className="btn btn-success btn-sm">
                            ⬇ Tải video
                        </a>
                    </div>
                    <div className="merge-result-player">
                        <video
                            controls
                            src={mergeResult.merged_video_url}
                            style={{ width: '100%', maxHeight: '500px', borderRadius: 'var(--radius-lg)' }}
                        ></video>
                    </div>
                </div>
            )}

            {mergeStatus === 'failed' && (
                <div className="merge-error">
                    <strong>❌ Ghép video thất bại</strong>
                    <p>Vui lòng kiểm tra lại link TikTok hoặc thử lại.</p>
                    <button className="btn btn-outline btn-sm" onClick={resetMerge}>Thử lại</button>
                </div>
            )}
        </div>
    );
}

// =============================================
// Dashboard Page
// =============================================

function DashboardPage({ addToast, setLoading }) {
    const [prefill, setPrefill] = useState(null);
    const [jobRefresh, setJobRefresh] = useState(0);

    return (
        <div className="container" style={{ paddingTop: '1.5rem', paddingBottom: '3rem' }}>
            <div className="page-header">
                <h1>Video Production Pipeline</h1>
                <p className="subtitle">Tạo video AI hàng loạt — Từ URL bài viết đến video hoàn chỉnh</p>
            </div>

            <ScrapePanel
                onScrapeResult={(data) => { setPrefill(data); }}
                addToast={addToast}
                setLoading={setLoading}
            />

            <SubmitPanel
                prefill={prefill}
                addToast={addToast}
                setLoading={setLoading}
                onJobCreated={() => setJobRefresh(prev => prev + 1)}
            />

            <MergePanel addToast={addToast} />

            <JobsTable refreshKey={jobRefresh} />
        </div>
    );
}

// =============================================
// Review Page
// =============================================

function ReviewPage({ addToast }) {
    const [stats, setStats] = useState({ pending: 0, approved: 0, rejected: 0, processing: 0 });
    const [pendingJobs, setPendingJobs] = useState([]);
    const [rejectModal, setRejectModal] = useState(null);
    const [rejectReason, setRejectReason] = useState('');

    const loadData = useCallback(async () => {
        try {
            const [pendingRes, approvedRes, rejectedRes, processingRes] = await Promise.all([
                fetch('/api/jobs?status=pending_review&limit=100'),
                fetch('/api/jobs?status=approved&limit=5'),
                fetch('/api/jobs?status=rejected&limit=5'),
                fetch('/api/jobs?status=processing&limit=5'),
            ]);
            const pending = await pendingRes.json();
            const approved = await approvedRes.json();
            const rejected = await rejectedRes.json();
            const processing = await processingRes.json();

            setStats({
                pending: pending.total || 0,
                approved: approved.total || 0,
                rejected: rejected.total || 0,
                processing: processing.total || 0,
            });
            setPendingJobs(pending.jobs || []);
        } catch (e) {
            console.error('Failed to load review data:', e);
        }
    }, []);

    useEffect(() => { loadData(); }, [loadData]);
    useEffect(() => { const id = setInterval(loadData, 10000); return () => clearInterval(id); }, [loadData]);

    async function handleApprove(jobId) {
        try {
            const res = await fetch(`/api/jobs/${jobId}/approve`, { method: 'POST' });
            const data = await res.json();
            if (data.success) {
                addToast(`Job #${jobId} đã được duyệt! ✅`, 'success');
                loadData();
            } else {
                addToast(data.detail || 'Lỗi duyệt video', 'error');
            }
        } catch (e) {
            addToast('Lỗi kết nối server', 'error');
        }
    }

    async function handleReject() {
        if (!rejectModal) return;
        try {
            const res = await fetch(`/api/jobs/${rejectModal}/reject`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ reason: rejectReason }),
            });
            const data = await res.json();
            if (data.success) {
                addToast(`Job #${rejectModal} đã bị từ chối`, 'error');
                setRejectModal(null);
                setRejectReason('');
                loadData();
            } else {
                addToast(data.detail || 'Lỗi', 'error');
            }
        } catch (e) {
            addToast('Lỗi kết nối server', 'error');
        }
    }

    return (
        <div className="container" style={{ paddingTop: '1.5rem', paddingBottom: '3rem' }}>
            <div className="page-header">
                <h1>Quality Gate — Duyệt Video</h1>
                <p className="subtitle">Xem và phê duyệt các video đang chờ kiểm duyệt</p>
            </div>

            {/* Stats */}
            <div style={{ display: 'flex', gap: '1rem', flexWrap: 'wrap', marginBottom: '1.5rem' }}>
                <div className="stat-card">
                    <div className="stat-value" style={{ color: 'var(--accent-warning)' }}>{stats.pending}</div>
                    <div className="stat-label">Chờ duyệt</div>
                </div>
                <div className="stat-card">
                    <div className="stat-value" style={{ color: 'var(--accent-secondary)' }}>{stats.approved}</div>
                    <div className="stat-label">Đã duyệt</div>
                </div>
                <div className="stat-card">
                    <div className="stat-value" style={{ color: 'var(--accent-danger)' }}>{stats.rejected}</div>
                    <div className="stat-label">Từ chối</div>
                </div>
                <div className="stat-card">
                    <div className="stat-value" style={{ color: 'var(--accent-primary)' }}>{stats.processing}</div>
                    <div className="stat-label">Đang xử lý</div>
                </div>
            </div>

            {/* Review Cards */}
            {pendingJobs.length === 0 ? (
                <div className="card">
                    <div className="empty-state">
                        <div className="empty-icon">✅</div>
                        <h3>Không có video nào chờ duyệt</h3>
                        <p>Tất cả đã được xử lý!</p>
                    </div>
                </div>
            ) : pendingJobs.map(job => (
                <div className="review-card" key={job.id}>
                    <div className="card-header">
                        <span className="badge badge-pending_review">Chờ duyệt</span>
                        <h3>Job #{job.id} — {job.title || 'Untitled'}</h3>
                        <span className="text-muted" style={{ fontSize: '0.8rem' }}>{formatTime(job.created_at)}</span>
                    </div>

                    <div className="review-grid">
                        <div>
                            {job.final_video_url ? (
                                <div className="video-preview">
                                    <video controls preload="metadata" poster={job.thumbnail_url || ''}>
                                        <source src={job.final_video_url} type="video/mp4" />
                                    </video>
                                </div>
                            ) : job.raw_video_url ? (
                                <div className="video-preview">
                                    <video controls preload="metadata">
                                        <source src={job.raw_video_url} type="video/mp4" />
                                    </video>
                                </div>
                            ) : (
                                <div style={{ background: 'var(--bg-secondary)', borderRadius: 'var(--radius-xl)', padding: '3rem', textAlign: 'center', border: '1px solid var(--border-light)' }}>
                                    <div style={{ fontSize: '2rem' }}>🎬</div>
                                    <div className="text-muted mt-1">Chưa có video</div>
                                </div>
                            )}
                        </div>

                        <div>
                            <div className="review-meta">
                                <div className="review-meta-label">Model</div>
                                <div className="review-meta-value">
                                    <code className="font-mono" style={{ color: 'var(--accent-primary)' }}>{job.model}</code>
                                    {' · '}{job.mode}{' · '}{job.quality}{' · '}{job.duration}s
                                </div>
                            </div>
                            <div className="review-meta">
                                <div className="review-meta-label">Prompt</div>
                                <div className="review-meta-value">{(job.prompt || '').substring(0, 200)}{(job.prompt || '').length > 200 ? '...' : ''}</div>
                            </div>
                            {job.script_text && (
                                <div className="review-meta">
                                    <div className="review-meta-label">TTS Script</div>
                                    <div className="review-meta-value" style={{ color: 'var(--text-muted)' }}>
                                        {job.script_text.substring(0, 150)}{job.script_text.length > 150 ? '...' : ''}
                                    </div>
                                </div>
                            )}
                            <div style={{ display: 'flex', gap: '0.75rem', marginTop: '1.25rem' }}>
                                <button className="btn btn-success" onClick={() => handleApprove(job.id)}>✅ Approve</button>
                                <button className="btn btn-danger" onClick={() => { setRejectModal(job.id); setRejectReason(''); }}>❌ Reject</button>
                                {job.final_video_url && <a href={job.final_video_url} target="_blank" className="btn btn-outline">⬇️ Download</a>}
                            </div>
                        </div>
                    </div>
                </div>
            ))}

            {/* Reject Modal */}
            <div className={`modal-overlay ${rejectModal ? 'show' : ''}`} onClick={() => setRejectModal(null)}>
                <div className="modal-content" onClick={e => e.stopPropagation()}>
                    <h3 style={{ marginBottom: '1rem' }}>❌ Từ chối Video</h3>
                    <div className="form-group">
                        <label>Lý do từ chối</label>
                        <textarea
                            className="form-textarea"
                            rows="3"
                            placeholder="Nhập lý do từ chối..."
                            value={rejectReason}
                            onChange={e => setRejectReason(e.target.value)}
                        ></textarea>
                    </div>
                    <div style={{ display: 'flex', gap: '0.75rem', justifyContent: 'flex-end' }}>
                        <button className="btn btn-outline" onClick={() => setRejectModal(null)}>Hủy</button>
                        <button className="btn btn-danger" onClick={handleReject}>Xác nhận từ chối</button>
                    </div>
                </div>
            </div>
        </div>
    );
}

// =============================================
// App Root
// =============================================

function App() {
    const [page, setPage] = useState('dashboard');
    const [toasts, setToasts] = useState([]);
    const [loading, setLoadingState] = useState({ show: false, text: '' });

    function addToast(message, type = 'info') {
        const id = ++toastIdCounter;
        setToasts(prev => [...prev, { id, message, type }]);
        setTimeout(() => removeToast(id), 3500);
    }

    function removeToast(id) {
        setToasts(prev => prev.filter(t => t.id !== id));
    }

    function setLoading(show, text = 'Đang xử lý...') {
        setLoadingState({ show, text });
    }

    // Handle browser back/forward
    useEffect(() => {
        const path = window.location.pathname;
        if (path === '/admin') setPage('review');
        else if (path === '/workflow-builder') setPage('workflow-builder');
        else setPage('dashboard');
    }, []);

    function navigate(p) {
        setPage(p);
        const urlMap = { review: '/admin', 'workflow-builder': '/workflow-builder' };
        window.history.pushState({}, '', urlMap[p] || '/');
    }

    function renderPage() {
        switch (page) {
            case 'review': return <ReviewPage addToast={addToast} />;
            case 'workflow-builder': return <WorkflowBuilderPage addToast={addToast} setLoading={setLoading} />;
            default: return <DashboardPage addToast={addToast} setLoading={setLoading} />;
        }
    }

    return (
        <>
            <Navbar currentPage={page} onNavigate={navigate} />
            {renderPage()}
            <ToastContainer toasts={toasts} removeToast={removeToast} />
            <LoadingOverlay show={loading.show} text={loading.text} />
        </>
    );
}

// Mount
const root = ReactDOM.createRoot(document.getElementById('root'));
root.render(<App />);
