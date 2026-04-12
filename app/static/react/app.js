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

    async function handleFileUpload(e) {
        const file = e.target.files[0];
        if (!file || !file.type.startsWith('image/')) {
            addToast('Chỉ chấp nhận file ảnh', 'error');
            return;
        }
        // Preview
        const reader = new FileReader();
        reader.onload = (ev) => setPreview(ev.target.result);
        reader.readAsDataURL(file);
        // Upload
        setLoading(true, 'Đang upload ảnh...');
        const formData = new FormData();
        formData.append('file', file);
        try {
            const res = await fetch('/api/upload', { method: 'POST', body: formData });
            const data = await res.json();
            if (data.success) {
                setImageUrl(data.url);
                addToast(`Upload thành công: ${(data.size / 1024).toFixed(0)} KB`, 'success');
            } else {
                addToast(data.detail || 'Upload thất bại', 'error');
            }
        } catch (e) {
            addToast('Lỗi upload', 'error');
        } finally {
            setLoading(false);
        }
    }

    async function handleSubmit() {
        if (!prompt.trim()) { addToast('Vui lòng nhập prompt tạo video', 'error'); return; }
        setSubmitting(true);
        try {
            const res = await fetch('/api/submit', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    title: title || 'Video Job',
                    image_url: imageUrl || null,
                    prompt: prompt.trim(),
                    script_text: script || null,
                    model, mode, quality,
                    duration: parseInt(duration) || 5,
                    aspect_ratio: ratio,
                }),
            });
            const data = await res.json();
            if (data.success) {
                addToast(`Job #${data.job.id} đã được đưa vào hàng đợi! 🚀`, 'success');
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

    const modeOptions = model === 'veo-3-fast'
        ? [['t2v', 'Text-to-Video'], ['i2v', 'Image-to-Video'], ['r2v', 'Reference-to-Video']]
        : [['i2v', 'Image-to-Video']];

    return (
        <div className="card" id="phase1-card">
            <div className="card-header">
                <span className="phase-badge">Phase 1-2</span>
                <h3>🎬 Tạo Video (Input & Submit)</h3>
            </div>

            {/* Upload Image */}
            <div className="form-group">
                <label>Ảnh nguồn (Start Frame cho I2V)</label>
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
                            <th>Trạng thái</th>
                            <th>Thời gian</th>
                            <th>Hành động</th>
                        </tr>
                    </thead>
                    <tbody>
                        {jobs.length === 0 ? (
                            <tr>
                                <td colSpan="6" className="text-center text-muted" style={{ padding: '2rem' }}>
                                    Chưa có job nào
                                </td>
                            </tr>
                        ) : jobs.map(job => (
                            <tr key={job.id}>
                                <td><strong style={{ color: 'var(--text-primary)' }}>#{job.id}</strong></td>
                                <td className="job-title">{job.title || '—'}</td>
                                <td><code className="font-mono" style={{ color: 'var(--accent-primary)' }}>{job.model}</code></td>
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
        else setPage('dashboard');
    }, []);

    function navigate(p) {
        setPage(p);
        const url = p === 'review' ? '/admin' : '/';
        window.history.pushState({}, '', url);
    }

    return (
        <>
            <Navbar currentPage={page} onNavigate={navigate} />
            {page === 'dashboard'
                ? <DashboardPage addToast={addToast} setLoading={setLoading} />
                : <ReviewPage addToast={addToast} />
            }
            <ToastContainer toasts={toasts} removeToast={removeToast} />
            <LoadingOverlay show={loading.show} text={loading.text} />
        </>
    );
}

// Mount
const root = ReactDOM.createRoot(document.getElementById('root'));
root.render(<App />);
