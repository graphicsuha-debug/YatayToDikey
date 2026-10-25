import { useCallback, useEffect, useRef, useState } from 'react';
import type { PointerEvent } from 'react';
import { ArrowDownToLine, ArrowLeft, ArrowRight, Check, CheckCheck, ChevronDown, CircleHelp, Clapperboard, Crop as CropIcon, Download, Expand, Film, FolderClosed, HardDrive, LayoutPanelTop, LoaderCircle, Maximize, Monitor, Pause, Play, Plus, RotateCcw, ScanFace, Scissors, ShieldCheck, SlidersHorizontal, Smartphone, Sparkles, Upload, Volume2, VolumeX, X } from 'lucide-react';
import VerticalPreview from './VerticalPreview';
import { api, clock } from './types';
import type { Crop, Job, Video } from './types';

const defaultCrop = { x: .025, y: .6, width: .275, height: .36 };
const json = (value: unknown): RequestInit => ({ method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(value) });
const active = (job: Job | null) => !!job && ['queued', 'processing'].includes(job.status);

export default function App() {
  const [page, setPage] = useState<'studio' | 'exports'>('studio');
  const [video, setVideo] = useState<Video | null>(null);
  const [camera, setCamera] = useState<Crop>(defaultCrop);
  const [placement, setPlacement] = useState('auto');
  const [split, setSplit] = useState(.35);
  const [fit, setFit] = useState<'cover' | 'contain'>('cover');
  const [focus, setFocus] = useState(.5);
  const [resolution, setResolution] = useState<720 | 1080>(1080);
  const [fps, setFps] = useState<30 | 60>(30);
  const [muted, setMuted] = useState(false);
  const [start, setStart] = useState(0);
  const [end, setEnd] = useState(0);
  const [time, setTime] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [upload, setUpload] = useState<number | null>(null);
  const [loadingDemo, setLoadingDemo] = useState(true);
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState('');
  const [help, setHelp] = useState(false);
  const [job, setJob] = useState<Job | null>(null);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [server, setServer] = useState<'loading' | 'ready' | 'offline'>('loading');
  const [mediaError, setMediaError] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const source = useRef<HTMLVideoElement>(null);
  const stage = useRef<HTMLDivElement>(null);
  const drag = useRef<{ x: number; y: number; crop: Crop; resize: boolean } | null>(null);
  const duration = video?.duration || 0;
  const busy = upload !== null || loadingDemo;

  const selectVideo = useCallback((item: Video) => {
    setVideo(item); setCamera(item.camera); setPlacement('auto'); setStart(0); setEnd(item.duration);
    setTime(0); setPlaying(false); setJob(null); setMediaError(false); setPage('studio'); setFocus(item.id === 'demo' ? .68 : .5);
  }, []);

  useEffect(() => {
    let cancelled = false;
    const initialize = async () => {
      try {
        const health = await api<{ ok: boolean; ffmpeg: boolean }>('/api/health');
        if (cancelled) return;
        setServer(health.ok && health.ffmpeg ? 'ready' : 'offline');
        if (!health.ffmpeg) { setError('Video işleme bileşeni bulunamadı. FFmpeg kurulumunu kontrol et.'); return; }
        try { const item = await api<Video>('/api/demo'); if (!cancelled) selectVideo(item); }
        catch { /* A missing demo must not prevent opening a real video. */ }
      } catch { if (!cancelled) setServer('offline'); }
      finally { if (!cancelled) setLoadingDemo(false); }
    };
    initialize();
    return () => { cancelled = true; };
  }, [selectVideo]);

  useEffect(() => { setPlaying(false); }, [page]);

  useEffect(() => {
    if (!job || !active(job)) return;
    let disposed = false;
    let failures = 0;
    const timer = window.setInterval(() => {
      api<Job>(`/api/exports/${job.id}`).then(result => {
        failures = 0;
        if (!disposed) { setJob(result); if (result.status === 'failed') setError(result.error || 'Video oluşturulamadı.'); }
      }).catch(() => { if (++failures === 3 && !disposed) setError('Dışa aktarma durumuna ulaşılamıyor. Uygulamanın açık olduğundan emin ol.'); });
    }, 1000);
    return () => { disposed = true; clearInterval(timer); };
  }, [job?.id, job?.status]);

  useEffect(() => {
    if (page !== 'exports') return;
    const refresh = () => api<Job[] | { jobs: Job[] }>('/api/exports').then(data => setJobs(Array.isArray(data) ? data : data.jobs)).catch(() => setError('Çıktılar yüklenemedi.'));
    refresh(); const timer = window.setInterval(refresh, 2500); return () => clearInterval(timer);
  }, [page]);

  const togglePlayback = useCallback(() => {
    const element = source.current;
    if (!element || !video) return;
    if (element.paused) {
      if (element.currentTime >= end || element.currentTime < start) element.currentTime = start;
      element.play().catch(() => setError('Bu video tarayıcıda oynatılamıyor. Dönüştürme işlemini yine de deneyebilirsin.'));
    } else element.pause();
  }, [video, start, end]);

  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setHelp(false);
      if (event.code === 'Space' && !help && page === 'studio' && !['INPUT', 'BUTTON', 'SELECT', 'TEXTAREA', 'A'].includes((event.target as HTMLElement).tagName)) {
        event.preventDefault(); togglePlayback();
      }
    };
    window.addEventListener('keydown', handler); return () => window.removeEventListener('keydown', handler);
  }, [togglePlayback, page, help]);

  function uploadFile(file?: File) {
    if (!file || busy) return;
    if (!/\.(mp4|mov|mkv|webm|avi|m4v|ts|mts)$/i.test(file.name)) { setError('MP4, MOV, MKV, WebM, AVI veya TS formatında bir video seç.'); return; }
    setUpload(0); setError(''); source.current?.pause();
    const request = new XMLHttpRequest();
    request.open('POST', '/api/videos');
    request.upload.onprogress = event => { if (event.lengthComputable) setUpload(Math.round(event.loaded / event.total * 100)); };
    request.onload = () => {
      setUpload(null);
      try {
        const data = JSON.parse(request.responseText);
        if (request.status < 200 || request.status >= 300) throw new Error(typeof data.detail === 'string' ? data.detail : 'Video açılamadı.');
        selectVideo(data); setServer('ready');
      } catch (e) { setError(e instanceof Error ? e.message : 'Video açılamadı.'); }
    };
    request.onerror = () => { setUpload(null); setError('Yerel uygulamaya bağlanılamadı. Başlat dosyasıyla uygulamayı yeniden aç.'); };
    const data = new FormData(); data.append('file', file); request.send(data);
    if (fileRef.current) fileRef.current.value = '';
  }

  async function loadDemo() {
    setLoadingDemo(true); setError('');
    try { selectVideo(await api<Video>('/api/demo')); } catch (e) { setError((e as Error).message); }
    finally { setLoadingDemo(false); }
  }

  function choosePlacement(value: string) {
    setPlacement(value);
    if (value === 'auto') setCamera(video?.camera || defaultCrop);
    else if (value !== 'custom') {
      const width = .275, height = .36;
      setCamera({ x: value.includes('right') ? 1 - width - .025 : .025, y: value.includes('top') ? .04 : .6, width, height });
    }
  }

  function beginDrag(event: PointerEvent, resize: boolean) {
    if (!video) return;
    event.stopPropagation(); event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    drag.current = { x: event.clientX, y: event.clientY, crop: camera, resize };
  }
  function moveDrag(event: PointerEvent) {
    const d = drag.current, bounds = stage.current?.getBoundingClientRect();
    if (!d || !bounds) return;
    const dx = (event.clientX - d.x) / bounds.width, dy = (event.clientY - d.y) / bounds.height;
    setPlacement('custom');
    setCamera(d.resize ? { ...d.crop, width: Math.min(1 - d.crop.x, Math.max(.05, d.crop.width + dx)), height: Math.min(1 - d.crop.y, Math.max(.05, d.crop.height + dy)) } : {
      ...d.crop, x: Math.min(1 - d.crop.width, Math.max(0, d.crop.x + dx)), y: Math.min(1 - d.crop.height, Math.max(0, d.crop.y + dy)),
    });
  }

  async function exportVideo() {
    if (!video || active(job) || submitting) return;
    if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start || start < 0 || end > duration + .01) { setError('Bitiş zamanı başlangıçtan büyük ve video süresi içinde olmalı.'); return; }
    setSubmitting(true); setError('');
    try { setJob(await api<Job>('/api/exports', json({ videoId: video.id, camera, split, fit, focus, start, end, resolution, fps, muted }))); }
    catch (e) { setError((e as Error).message); } finally { setSubmitting(false); }
  }
  async function cancelExport(item: Job) {
    try { const result = await api<Job>(`/api/exports/${item.id}/cancel`, { method: 'POST' }); if (job?.id === item.id) setJob(result); setJobs(prev => prev.map(j => j.id === item.id ? result : j)); }
    catch (e) { setError((e as Error).message); }
  }
  const seek = (value: number) => { if (source.current) source.current.currentTime = value; setTime(value); };
  const downloadUrl = (item: Job) => item.url || `/api/exports/${item.id}/download`;

  return <div className="app-shell">
    <aside className="rail" aria-label="Ana menü">
      <button className="brand-mark" onClick={() => setPage('studio')} aria-label="Dikey stüdyosu"><span /><span /></button>
      <div className="rail-links">
        <button className={`rail-button ${page === 'studio' ? 'selected' : ''}`} onClick={() => setPage('studio')} title="Stüdyo" aria-label="Stüdyo"><LayoutPanelTop size={21} /></button>
        <button className={`rail-button ${page === 'exports' ? 'selected' : ''}`} onClick={() => setPage('exports')} title="Çıktılarım" aria-label="Çıktılarım"><FolderClosed size={21} />{active(job) && <i className="notification-dot" />}</button>
      </div>
      <div className="rail-bottom"><button className="rail-button" onClick={() => setHelp(true)} title="Nasıl çalışır?" aria-label="Nasıl çalışır?"><CircleHelp size={21} /></button><div className="avatar">S</div></div>
    </aside>

    <div className="main-shell">
      <header className="topbar"><a className="wordmark" href="#" onClick={e => { e.preventDefault(); setPage('studio'); }}>dikey<span>.</span></a><div className="breadcrumb"><span>Kişisel stüdyon</span><span>/</span><strong>{page === 'studio' ? 'Video düzenleyici' : 'Çıktılarım'}</strong></div><div className={`local-status ${server === 'offline' ? 'offline' : ''}`}><span />{server === 'ready' ? 'Bilgisayarında çalışıyor' : server === 'offline' ? 'Bağlantı bekleniyor' : 'Stüdyo hazırlanıyor'}</div></header>
      <main>
        {page === 'studio' ? <>
          <section className="page-heading"><div><div className="eyebrow"><span /> YENİ BİR AÇI</div><h1>Yayınından daha fazlasını çıkar<span>.</span></h1><p>Yatay videonu seç. Kameranı yerleştir. Dikey içeriklerin hazır.</p></div><button className="button primary upload-button" onClick={() => fileRef.current?.click()} disabled={busy}><Plus size={18} /> Video seç</button></section>

          <div className={`dropzone ${dragging ? 'dragging' : ''} ${busy ? 'busy' : ''}`} onDragOver={e => { e.preventDefault(); setDragging(true); }} onDragLeave={e => { if (!e.currentTarget.contains(e.relatedTarget as Node)) setDragging(false); }} onDrop={e => { e.preventDefault(); setDragging(false); uploadFile(e.dataTransfer.files[0]); }}>
            <button className="dropzone-action" onClick={() => fileRef.current?.click()} disabled={busy}>
              <span className="upload-icon">{busy ? <LoaderCircle size={20} className="spin" /> : <Upload size={20} />}</span>
              <span><strong>{upload !== null ? upload < 100 ? `Video alınıyor · %${upload}` : 'Kamera alanı analiz ediliyor…' : loadingDemo ? 'Örnek proje açılıyor…' : 'Videonu buraya sürükle veya dosya seç'}</strong><small>{busy ? 'İşlem bu bilgisayarda devam ediyor.' : 'MP4, MOV, MKV, WebM ve daha fazlası'}</small></span>
            </button>
            <div className="dropzone-right"><span className="private-note"><ShieldCheck size={14} /> Dosyaların sende kalır</span><span className="vertical-divider" /><button className="text-button" onClick={loadDemo} disabled={busy}>Örnek projeyi aç <ArrowRight size={15} /></button></div>
            {upload !== null && <div className="upload-line" style={{ width: `${upload}%` }} />}
          </div>

          <div className="editor-grid">
            <section className="source-column">
              <div className="section-title"><div><Monitor size={17} /><h2>Kaynak video</h2><span className="small-badge">{video ? `${video.width} × ${video.height}` : '16:9'}</span></div><span className="section-index">01</span></div>
              <div className="source-card">
                <div className="source-video" ref={stage} style={{ aspectRatio: video ? `${video.width}/${video.height}` : '16/9' }}>
                  <video ref={source} src={video?.url} poster={video?.poster || '/demo-poster.jpg'} playsInline preload="metadata" muted={muted} onPlay={() => setPlaying(true)} onPause={() => setPlaying(false)} onEnded={() => setPlaying(false)} onLoadedData={() => setMediaError(false)} onError={() => { if (video) setMediaError(true); }} onTimeUpdate={e => { const v = e.currentTarget; setTime(v.currentTime); if (v.currentTime >= end && end > 0 && !v.paused) { v.pause(); v.currentTime = start; } }} />
                  <div className="source-corner-label"><span />{video?.id === 'demo' || video?.name?.toLowerCase().includes('örnek') || video?.name?.includes('demo') ? 'ÖRNEK PROJE' : video ? 'KAYNAK' : 'ÖRNEK GÖRÜNÜM'}</div>
                  {video && <div className="camera-selection" style={{ left: `${camera.x * 100}%`, top: `${camera.y * 100}%`, width: `${camera.width * 100}%`, height: `${camera.height * 100}%` }} onPointerDown={e => beginDrag(e, false)} onPointerMove={moveDrag} onPointerUp={() => { drag.current = null; }} onPointerCancel={() => { drag.current = null; }}>
                    <span className="crop-label"><ScanFace size={11} /> KAMERA</span><i className="crop-corner top-left" /><i className="crop-corner top-right" /><i className="crop-corner bottom-left" /><button className="resize-handle" aria-label="Kamera alanını boyutlandır" onPointerDown={e => beginDrag(e, true)} onPointerMove={moveDrag} onPointerUp={() => { drag.current = null; }}><Expand size={13} /></button>
                  </div>}
                  {!video && <button className="empty-play" onClick={loadDemo} aria-label="Örnek videoyu aç"><Play size={25} fill="currentColor" /></button>}
                </div>
                <div className="playback-controls"><button className="icon-button play-button" onClick={togglePlayback} disabled={!video} aria-label={playing ? 'Duraklat' : 'Oynat'}>{playing ? <Pause size={16} fill="currentColor" /> : <Play size={16} fill="currentColor" />}</button><span className="timecode">{clock(time)} <span>/ {clock(duration)}</span></span><input className="seek-range" type="range" min="0" max={duration || 1} step="0.05" value={Math.min(time, duration)} onChange={e => seek(Number(e.target.value))} disabled={!video} aria-label="Videoda gezin" style={{ '--range-progress': `${duration ? time / duration * 100 : 0}%` } as React.CSSProperties} /><button className="icon-button" onClick={() => setMuted(!muted)} aria-label={muted ? 'Sesi aç' : 'Sesi kapat'}>{muted ? <VolumeX size={17} /> : <Volume2 size={17} />}</button><button className="icon-button" onClick={() => source.current?.requestFullscreen().catch(() => setError('Tam ekran açılamadı.'))} disabled={!video} aria-label="Videoyu tam ekran aç"><Maximize size={16} /></button></div>
                <div className="file-info"><div className="file-icon"><Film size={16} /></div><div><strong title={video?.name}>{video?.name || 'İlk videon için her şey hazır'}</strong><span>{video ? `${(video.size / 1048576).toFixed(1)} MB · ${Math.round(video.fps)} FPS · ${clock(video.duration)}` : 'Bir dosya seç veya örnek projeyle başla'}</span></div><span className="file-check">{video && <Check size={16} />}</span></div>
              </div>
              {mediaError && <div className="inline-warning">Bu dosyanın tarayıcı önizlemesi desteklenmiyor. Kare görüntüsü üzerinden kadrajı ayarlayıp MP4 oluşturabilirsin.</div>}
              <div className="camera-tip"><div><ScanFace size={17} /></div><p><strong>{placement === 'custom' ? 'Kamera alanın sana özel.' : video?.detection.mode === 'detected' ? 'Kamera alanı otomatik bulundu.' : 'Kamera alanını birlikte netleştirelim.'}</strong><span>Mor çerçeveyi taşı, köşesinden boyutlandır.</span></p><span className="tip-sparkle"><Sparkles size={16} /></span></div>

              <section className="trim-card"><div className="card-heading"><div><Scissors size={16} /><h3>En iyi anını seç</h3></div><button className="text-button subtle" onClick={() => { setStart(0); setEnd(duration); seek(0); }} disabled={!video}><RotateCcw size={12} /> Sıfırla</button></div><p>Tüm yayını dönüştür veya sadece istediğin kesiti al.</p><div className="trim-inputs"><label><span>Başlangıç <small>(saniye)</small></span><div><input type="number" min="0" max={Math.max(0, end - .1)} step="0.1" value={start} disabled={!video} onChange={e => { const val = Math.max(0, Number(e.target.value)); setStart(val); if (val <= duration) seek(val); }} aria-label="Kesit başlangıcı saniye" /><span>{clock(start)}</span></div></label><span className="trim-arrow"><ArrowRight size={15} /></span><label><span>Bitiş <small>(saniye)</small></span><div><input type="number" min={start + .1} max={duration} step="0.1" value={Number(end.toFixed(3))} disabled={!video} onChange={e => setEnd(Number(e.target.value))} aria-label="Kesit bitişi saniye" /><span>{clock(end)}</span></div></label><div className="clip-duration"><span>Kesit süresi</span><strong>{clock(Math.max(0, end - start))}</strong></div></div></section>
              <div className="workflow-note"><ShieldCheck size={14} /><span>Video işlemleri bilgisayarında yapılır. Buluta yükleme yok.</span></div>
            </section>

            <section className="preview-column"><div className="section-title"><div><Smartphone size={17} /><h2>Dikey önizleme</h2></div><span className="section-index">02</span></div><div className="preview-surface"><div className="preview-format"><span><i /> CANLI ÖNİZLEME</span><span>9:16</span></div><div className="portrait-frame"><VerticalPreview video={video} source={source} camera={camera} split={split} fit={fit} focus={focus} time={time} /><span className="preview-divider" style={{ top: `${split * 100}%` }} /><span className="preview-part camera-part">Kamera</span><span className="preview-part content-part" style={{ top: `calc(${split * 100}% + 10px)` }}>İçerik</span></div><div className="preview-resolution">{resolution} × {resolution === 1080 ? 1920 : 1280}<span>·</span>{fps} FPS</div><div className="platforms"><span>Reels</span><span>Shorts</span><span>TikTok</span></div></div><p className="preview-note"><CheckCheck size={14} /> Bir video, her platforma hazır.</p></section>

            <section className="settings-column"><div className="section-title"><div><SlidersHorizontal size={17} /><h2>Son dokunuşlar</h2></div><span className="section-index">03</span></div><div className="settings-card"><div className="setting-section layout-setting"><div className="setting-label"><span>Düzen</span><span className="purple-badge">9:16</span></div><div className="layout-option"><div className="mini-layout"><span /><span /></div><div><strong>Kamera + İçerik</strong><small>Sen üstte, hikâyen altta.</small></div><span className="selected-check"><Check size={12} strokeWidth={3} /></span></div></div>
              <div className="setting-section"><div className="setting-label"><label htmlFor="camera-position">Kamera alanı</label><ScanFace size={14} /></div><div className="select-wrapper"><select id="camera-position" value={placement} onChange={e => choosePlacement(e.target.value)}><option value="auto">{video?.detection.mode === 'detected' ? 'Otomatik algılandı' : 'Otomatik öneri'}</option><option value="bottom-left">Sol alt köşe</option><option value="bottom-right">Sağ alt köşe</option><option value="top-left">Sol üst köşe</option><option value="top-right">Sağ üst köşe</option><option value="custom">Özel seçim</option></select><ChevronDown size={14} /></div><div className="setting-label split-label"><label htmlFor="split">Kamera yüksekliği</label><span className="value-pill">%{Math.round(split * 100)}</span></div><input id="split" type="range" min="20" max="50" step="1" value={Math.round(split * 100)} onChange={e => setSplit(Number(e.target.value) / 100)} /><div className="range-labels"><span>Daha çok içerik</span><span>Daha çok kamera</span></div></div>
              <div className="setting-section"><div className="setting-label"><span>İçerik kadrajı</span><CropIcon size={14} /></div><div className="segmented"><button className={fit === 'cover' ? 'active' : ''} onClick={() => setFit('cover')}><Expand size={13} /> Ekranı doldur</button><button className={fit === 'contain' ? 'active' : ''} onClick={() => setFit('contain')}><Monitor size={13} /> Tümünü sığdır</button></div>{fit === 'cover' ? <><div className="setting-label focus-label"><label htmlFor="focus">İçerik odağı</label><button className="icon-button tiny" aria-label="İçerik odağını ortala" onClick={() => setFocus(.5)}><RotateCcw size={12} /></button></div><input id="focus" type="range" min="0" max="100" value={focus * 100} onChange={e => setFocus(Number(e.target.value) / 100)} /><div className="range-labels"><span>Sol</span><span>Orta</span><span>Sağ</span></div></> : <p className="setting-help">İçeriğin tamamı görünür, boşluklar koyu zeminle tamamlanır.</p>}</div>
              <div className="setting-section output-setting"><div className="setting-label"><span>Çıktı kalitesi</span><span className="muted-label">MP4</span></div><div className="quality-row"><div className="segmented"><button className={resolution === 1080 ? 'active' : ''} onClick={() => setResolution(1080)}>1080p <span>HD</span></button><button className={resolution === 720 ? 'active' : ''} onClick={() => setResolution(720)}>720p</button></div><div className="select-wrapper fps-select"><select aria-label="Çıktı kare hızı" value={fps} onChange={e => setFps(Number(e.target.value) as 30 | 60)}><option value="30">30 fps</option><option value="60">60 fps</option></select><ChevronDown size={12} /></div></div><button className="audio-toggle" onClick={() => setMuted(!muted)} role="switch" aria-checked={!muted}><span><Volume2 size={14} /> Orijinal sesi koru</span><span className={`toggle ${!muted ? 'on' : ''}`}><i /></span></button></div>
              <div className="export-section">{job?.status === 'completed' ? <><a className="button primary export-button" href={downloadUrl(job)} download><Download size={17} /> Videonu indir</a><button className="text-button export-again" onClick={exportVideo} disabled={submitting}><RotateCcw size={12} /> Yeni ayarlarla oluştur</button></> : <><button className="button primary export-button" onClick={exportVideo} disabled={!video || busy || active(job) || submitting}>{submitting || active(job) ? <LoaderCircle size={17} className="spin" /> : <Sparkles size={17} />}{active(job) ? `Hazırlanıyor · %${Math.round(job?.progress || 0)}` : 'Dikey videoyu oluştur'}</button>{active(job) ? <><div className="export-progress"><span style={{ width: `${job?.progress || 0}%` }} /></div><button className="text-button export-again" onClick={() => job && cancelExport(job)}>İşlemi iptal et</button></> : <div className="export-meta"><span>{clock(Math.max(0, end - start))} süre</span><span>·</span><span>Filigran yok</span></div>}</>}{job?.status === 'cancelled' && <p className="setting-help">Dışa aktarma iptal edildi.</p>}</div>
            </div></section>
          </div>
        </> : <>
          <section className="page-heading"><div><div className="eyebrow"><span /> İÇERİK KÜTÜPHANEN</div><h1>Çıktıların burada<span>.</span></h1><p>Hazırladığın dikey videoları indir, yeni hikâyeni paylaş.</p></div><button className="button primary" onClick={() => setPage('studio')}><Plus size={17} /> Yeni video</button></section>
          <div className="exports-list">{jobs.length ? jobs.map(item => <div className="export-row" key={item.id}><div className="export-file-icon"><Clapperboard size={23} /></div><div className="export-details"><strong>{item.filename || `Dikey video · ${item.id.slice(0, 8)}`}</strong><span>{item.status === 'completed' ? 'MP4 · İndirmeye hazır' : item.status === 'failed' ? item.error || 'Oluşturulamadı' : item.status === 'cancelled' ? 'İptal edildi' : `Oluşturuluyor · %${Math.round(item.progress)}`}</span></div><span className={`job-status ${item.status}`}>{item.status === 'completed' ? <><Check size={13} /> Tamamlandı</> : active(item) ? <><LoaderCircle size={13} className="spin" /> İşleniyor</> : item.status === 'cancelled' ? 'İptal' : 'Hata'}</span>{item.status === 'completed' ? <a className="button secondary" href={downloadUrl(item)} download><ArrowDownToLine size={16} /> İndir</a> : active(item) ? <button className="icon-button" onClick={() => cancelExport(item)} aria-label="Dışa aktarmayı iptal et"><X size={16} /></button> : null}</div>) : <div className="exports-empty"><div><FolderClosed size={33} /></div><h2>İlk dikey videon seni bekliyor.</h2><p>Stüdyoda oluşturduğun videolar burada görünecek.</p><button className="button primary" onClick={() => setPage('studio')}><ArrowLeft size={16} /> Stüdyoya dön</button></div>}</div><p className="exports-note"><HardDrive size={15} /> Oluşturulan videolar bu bilgisayarda saklanır.</p>
        </>}
      </main>
      <footer className="studio-footer author-footer"><span>Bu program <strong>Suha Yar</strong> tarafından yapılmıştır.</span><span>Dikey Studio <span className="tiny-brand">d.</span></span></footer>
    </div>
    <input ref={fileRef} className="hidden-input" type="file" accept="video/*,.mkv,.mov,.avi,.m4v,.ts,.mts" onChange={e => uploadFile(e.target.files?.[0])} aria-label="Video dosyası seç" />
    {error && <div className="toast" role="alert"><CircleHelp size={19} /><span>{error}</span><button className="icon-button" onClick={() => setError('')} aria-label="Uyarıyı kapat"><X size={17} /></button></div>}
    {help && <div className="modal-backdrop" onClick={() => setHelp(false)}><section className="help-modal" role="dialog" aria-modal="true" aria-labelledby="help-title" onClick={e => e.stopPropagation()}><button className="icon-button modal-close" onClick={() => setHelp(false)} aria-label="Yardımı kapat" autoFocus><X size={20} /></button><span className="help-icon"><Sparkles size={25} /></span><h2 id="help-title">Yeni kadrajın, üç adımda.</h2><p>Yayınlarından Reels, Shorts ve TikTok videoları oluştur.</p><ol><li><strong>Videonu seç</strong><span>Bilgisayarındaki yatay videoyu bırak. İşlem yerel olarak yapılır.</span></li><li><strong>Kameranı kontrol et</strong><span>Otomatik öneriyi kontrol et; mor çerçeveyi taşı ve köşesinden boyutlandır. Seçtiğin alan video boyunca sabit kalır.</span></li><li><strong>Kesitini seç ve oluştur</strong><span>Başlangıç ve bitiş saniyelerini gir. Dikey videonu MP4 olarak indir.</span></li></ol><div className="help-note"><ScanFace size={18} /><p>Otomatik kamera tahmini her yayında kusursuz olmayabilir. Dışa aktarmadan önce önizlemeyi kontrol et.</p></div><button className="button primary" onClick={() => setHelp(false)}>Hadi başlayalım <ArrowRight size={16} /></button></section></div>}
  </div>;
}
