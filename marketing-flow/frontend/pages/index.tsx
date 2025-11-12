import { useMemo, useState } from "react";

type TrendPoint = { date: number; [key: string]: number };
type Trends = { interest_last_12m: TrendPoint[]; top_queries: any[]; rising_queries: any[] };
type MVPResult = {
  source: string;
  keyword: string;
  fields: { title?: string; h1?: string[]; h2?: string[]; metas?: any; text?: string };
  insights: any;
  trends: Trends;
  draft: string;
  // Thêm các trường lỗi tùy chọn
  draft_error_note?: string;
  sheet_export_error?: string;
};

// ---- Viral analyze types ----
type SceneSegment = { start_sec: number; end_sec: number; duration_sec: number };

// (Các type PlatformCaptions, ContentDeliverables, ViralAnalyzeResp... giữ nguyên)
type PlatformCaptions = {
  facebook: string;
  instagram: string;
  tiktok: string;
  youtube_shorts: string;
};
type ContentDeliverables = {
  video_stub_path: string;
  carousel_images: string[];
  captions?: PlatformCaptions;
  cta_comments?: string[];
  carousel_zip_url?: string | null;
};
type ViralAnalyzeResp = {
  ok: boolean;
  source_url: string;
  video_path: string;
  audio_path: string;
  video_url?: string | null;
  audio_url?: string | null;
  audio_format: string;
  scenes: SceneSegment[];
  stats: Record<string, number>;
  content_deliverables?: ContentDeliverables;
};
type DeliverableRow = {
  Platform: string;
  AssetType: string;
  AssetLink: string;
  Caption: string;
  CTA_Comment: string;
  Status: "Todo" | "In progress" | "Done";
  Owner: string;
  DueDate: string;
};

// (declare var process: any; giữ nguyên)
declare var process: any;

export default function Home() {
  const API = "http://localhost:8080";

  // ===== MVP state =====
  const [url, setUrl] = useState("");
  const [keyword, setKeyword] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<MVPResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  // --- SỬA LỖI HÀM NÀY ---
  async function runMVP() {
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const res = await fetch(`${API}/mvp/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url, keyword }),
      });
      const data: MVPResult = await res.json();
      
      // Kiểm tra tất cả các lỗi có thể xảy ra
      if (!res.ok || data.error || data.draft_error_note || data.sheet_export_error) {
        const errorMsg = data.error || data.draft_error_note || data.sheet_export_error || "Request failed";
        setError(errorMsg);
      }
      // Luôn set result để hiển thị draft (ngay cả khi sheet export lỗi)
      setResult(data);
    } catch (e: any) {
      setError(e?.message || "Network error");
    } finally {
      setLoading(false);
    }
  }

  // (Các state và hàm còn lại: vaData, procLoading, fmtTime, v.v... giữ nguyên)
  // ===== Viral analyze state =====
  const [ttUrl, setTtUrl] = useState("");
  const [audioExt, setAudioExt] = useState<".mp3" | ".wav">(".mp3");
  const [sceneSensitivity, setSceneSensitivity] = useState(0.45);
  const [minGapFrames, setMinGapFrames] = useState(10);
  const [vaLoading, setVaLoading] = useState(false);
  const [vaError, setVaError] = useState<string | null>(null);
  const [vaData, setVaData] = useState<ViralAnalyzeResp | null>(null);

  // ===== Auto Subtitle + BGM state =====
  const [vidFile, setVidFile] = useState<File | null>(null);
  const [bgmFile, setBgmFile] = useState<File | null>(null);
  const [burnIn, setBurnIn] = useState(true);
  const [langHint, setLangHint] = useState<string>("");
  const [flipVideo, setFlipVideo] = useState(false);
  const [procLoading, setProcLoading] = useState(false);
  const [procError, setProcError] = useState<string | null>(null);
  const [procBlobUrl, setProcBlobUrl] = useState<string | null>(null);
  const [currentJobId, setCurrentJobId] = useState<string | null>(null);

  // ===== Remix state =====
  const [remixLoading, setRemixLoading] = useState(false);
  const [remixError, setRemixError] = useState<string | null>(null);
  const [remixBlobUrl, setRemixBlobUrl] = useState<string | null>(null);
  const [remixJobId, setRemixJobId] = useState<string | null>(null);
  const [selectedSceneIndices, setSelectedSceneIndices] = useState<Set<number>>(new Set());
  const [remixServerPath, setRemixServerPath] = useState<string | null>(null);

  // ---- Helpers ----
  function fmtTime(t: number) {
    if (!isFinite(t) || t < 0) return "0:00.000";
    const m = Math.floor(t / 60);
    const s = Math.floor(t % 60).toString().padStart(2, "0");
    const ms = Math.round((t % 1) * 1000).toString().padStart(3, "0");
    return `${m}:${s}.${ms}`;
  }

  function toPublicMediaUrl(absPath?: string | null) {
    if (!absPath) return null;
    const norm = absPath.replace(/\\/g, "/");
    
    const i = norm.toLowerCase().lastIndexOf("/media/");
    if (i >= 0) return norm.slice(i);
    const j = norm.toLowerCase().lastIndexOf("/audio/");
    if (j >= 0) return "/media" + norm.slice(j);
    const k = norm.toLowerCase().lastIndexOf("/videos/");
    if (k >= 0) return "/media" + norm.slice(k);
    const l = norm.toLowerCase().lastIndexOf("/exports/");
    if (l >= 0) return "/media" + norm.slice(l);

    const lastMedia = norm.toLowerCase().lastIndexOf("media/");
    if(lastMedia >= 0) {
      return "/" + norm.slice(lastMedia);
    }
    return null;
  }

  function cleanForCaption(s: string) {
    if (!s) return "";
    return s
      .replace(/https?:\/\/\S+/gi, "")
      .replace(/(^|\s)#[\p{L}\w_]+/giu, "")
      .replace(/[•\-–]{1,}\s*/g, "")
      .replace(/\s+/g, " ")
      .trim();
  }

  function composeCaptionText(mvp: MVPResult | null) {
    if (!mvp) return "Tóm tắt ngắn nội dung video.";
    const title = cleanForCaption(mvp.fields?.title || mvp.keyword || "");
    const raw =
      mvp.draft ||
      mvp.insights?.formula ||
      mvp.fields?.text ||
      (Array.isArray(mvp.fields?.h1) ? mvp.fields.h1.join(". ") : "") ||
      (Array.isArray(mvp.fields?.h2) ? mvp.fields.h2.join(". ") : "");
    const summary = cleanForCaption(raw || "");
    const joined = [title, summary].filter(Boolean).join(" — ").trim();
    return joined || title || "Tóm tắt ngắn nội dung video.";
  }

  function makeCaptionsFromMVP(mvp: MVPResult | null): PlatformCaptions {
    const baseShort = shortenDraft(composeCaptionText(mvp), 220, 2);
    return {
      facebook: baseShort,
      instagram: baseShort,
      tiktok: baseShort,
      youtube_shorts: baseShort,
    };
  }

  function shortenDraft(s: string, charLimit = 480, minSentences = 2) {
    if (!s) return "";
    const normalized = s.replace(/\s+/g, " ").trim();
    if (normalized.length <= charLimit) return normalized;
    const parts = normalized.split(/(?<=[.!?])\s+/);
    let out = "";
    for (let i = 0; i < parts.length; i++) {
      const next = out ? out + " " + parts[i] : parts[i];
      if (next.length > charLimit && i >= minSentences) break;
      out = next;
    }
    if (out.length > charLimit) out = out.slice(0, charLimit).trim().replace(/[,:;]$/, "");
    return out + "…";
  }

  const [showShortDraft, setShowShortDraft] = useState(true);
  const shortDraft = useMemo(
    () => shortenDraft(result?.draft || "", 480, 2),
    [result?.draft]
  );

  const totalSceneDuration = useMemo(
    () => (vaData?.scenes || []).reduce((acc, s) => acc + (s?.duration_sec || 0), 0),
    [vaData]
  );

  const captionsFromMVP = useMemo(() => makeCaptionsFromMVP(result), [result]);

  async function runViralAnalyze() {
    setVaError(null);
    setVaData(null);
    setRemixError(null);
    setRemixBlobUrl(null);
    setRemixJobId(null);
    setSelectedSceneIndices(new Set());
    setRemixServerPath(null);
    
    if (!ttUrl.trim()) {
      setVaError("Please paste a TikTok video URL.");
      return;
    }
    setVaLoading(true);
    try {
      const qs = new URLSearchParams({
        url: ttUrl.trim(),
        audio_ext: audioExt,
        scene_sensitivity: String(sceneSensitivity),
        min_scene_gap_frames: String(minGapFrames),
      } as any);
      const res = await fetch(`${API}/video/viral-analyze?${qs.toString()}`, { method: "POST" });
      const data = await res.json();
      if (!res.ok || data?.ok === false) {
        throw new Error(typeof data === "string" ? data : data?.detail || "Request failed");
      }
      setVaData(data);
    } catch (e: any) {
      setVaError(e?.message || "Network error");
    } finally {
      setVaLoading(false);
    }
  }

  function copy(text: string) {
    // navigator.clipboard?.writeText(text); // Có thể bị block
    try {
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.style.position = "fixed";
      ta.style.left = "-9999px";
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      document.body.removeChild(ta);
    } catch (e) {
      console.error("Failed to copy", e);
    }
  }

  const audioUrl = vaData?.audio_url ?? toPublicMediaUrl(vaData?.audio_path) ?? undefined;
  const videoUrl = vaData?.video_url ?? toPublicMediaUrl(vaData?.video_path) ?? undefined;

  const deliverableRows: DeliverableRow[] = useMemo(() => {
    if (!vaData) return [];
    const cap = shortenDraft(composeCaptionText(result), 220, 2);
    const ctaDefault = "Bạn thấy phần nào hữu ích nhất? Bình luận để mình làm phần 2!";
    return [
      { Platform: "YouTube Shorts", AssetType: "Video Reup (cut)", AssetLink: vaData.source_url || "", Caption: cap, CTA_Comment: ctaDefault, Status: "Todo", Owner: "", DueDate: "" },
      { Platform: "TikTok", AssetType: "Video Reup (cut + music + subtitle)", AssetLink: vaData.source_url || "", Caption: cap, CTA_Comment: "Bạn muốn mình đào sâu phần nào tiếp theo?", Status: "Todo", Owner: "", DueDate: "" },
      { Platform: "Instagram", AssetType: "Image Carousel", AssetLink: "(upload planned)", Caption: cap, CTA_Comment: "👉 Lưu lại để xem sau và chia sẻ với bạn bè!", Status: "Todo", Owner: "", DueDate: "" },
      // --- SỬA LỖI Ở ĐÂY: Xóa chữ 'F' và dấu hai chấm thừa ---
      { Platform: "Facebook Page", AssetType: "Caption-only", AssetLink: vaData.source_url || "", Caption: cap, CTA_Comment: "Bạn đồng ý/không đồng ý điểm nào? Bình luận nhé!", Status: "Todo", Owner: "", DueDate: "" },
    ];
  }, [vaData, result]);

  function downloadDeliverablesCSV() {
    if (!deliverableRows.length) return;
    const headers = Object.keys(deliverableRows[0]) as (keyof DeliverableRow)[];
    const lines = [
      headers.join(","),
      ...deliverableRows.map((r) =>
        headers
          .map((h) => String(r[h] ?? "").replace(/"/g, '""').replace(/\n/g, "\\n"))
          .map((cell) => `"${cell}"`)
          .join(",")
      ),
    ].join("\n");
    const blob = new Blob([lines], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "deliverables.csv";
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }

  async function handleProcess() {
    if (!vidFile) {
        setProcError("Select a video first.");
        return;
    }
    setProcLoading(true);
    setProcError(null);
    setProcBlobUrl(null);
    setCurrentJobId(null);

    const fd = new FormData();
    fd.append("video", vidFile);
    if (bgmFile) fd.append("bgm", bgmFile);
    fd.append("burn_in", String(burnIn));
    fd.append("flip", String(flipVideo));
    if (langHint) fd.append("language", langHint);

    let intervalId: any = null;

    try {
        const startResp = await fetch(`${API}/process`, { method: "POST", body: fd });
        const startData = await startResp.json();
        if (!startResp.ok || startData.status !== "processing") {
            throw new Error(startData.error || "Failed to start job.");
        }
        const { job_id } = startData;
        setCurrentJobId(job_id);

        intervalId = setInterval(async () => {
            try {
                const statusResp = await fetch(`${API}/process/status/${job_id}`);
                if (!statusResp.ok) {
                   if (statusResp.status === 404) {
                       throw new Error("Job not found. Please try again.");
                   }
                   throw new Error("Failed to get job status from server.");
                }
                const statusData = await statusResp.json();
                if (statusData.status === "complete") {
                    clearInterval(intervalId);
                    setProcLoading(false);
                    setCurrentJobId(null);
                    setProcBlobUrl(`${API}${statusData.download_url}`); 
                } else if (statusData.status === "failed") {
                    clearInterval(intervalId);
                    setProcLoading(false);
                    setCurrentJobId(null);
                    setProcError(statusData.error || "Job failed.");
                }
            } catch (pollError: any) {
                clearInterval(intervalId);
                setProcLoading(false);
                setCurrentJobId(null);
                setProcError(pollError?.message || "Failed to get job status.");
            }
        }, 5000); 

    } catch (e: any) {
        if (intervalId) clearInterval(intervalId);
        setProcLoading(false);
        setProcError(e?.message || "Processing error");
    }
  }

  function handleSceneToggle(sceneIndex: number) {
    setSelectedSceneIndices(prev => {
      const newSet = new Set(prev);
      if (newSet.has(sceneIndex)) {
        newSet.delete(sceneIndex);
      } else {
        newSet.add(sceneIndex);
      }
      return newSet;
    });
  }

  async function handleRemix() {
    if (!vaData) {
      setRemixError("Please run the TikTok Video Analyzer first.");
      return;
    }
    
    const scenes_to_keep = vaData.scenes.filter((_, index) => selectedSceneIndices.has(index));
    
    if (scenes_to_keep.length === 0) {
      setRemixError("No scenes were selected. Please check the boxes in the 'Scene Durations' table.");
      return;
    }
    
    setRemixLoading(true);
    setRemixError(null);
    setRemixBlobUrl(null);
    setRemixJobId(null);
    setRemixServerPath(null);

    const payload = {
      video_path: vaData.video_path,
      scenes: scenes_to_keep
    };

    let intervalId: any = null;

    try {
      const startResp = await fetch(`${API}/remix`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      
      const startData = await startResp.json();
      if (!startResp.ok || startData.status !== "processing") {
          throw new Error(startData.error || "Failed to start remix job.");
      }

      const { job_id } = startData;
      setRemixJobId(job_id);

      intervalId = setInterval(async () => {
          try {
              const statusResp = await fetch(`${API}/process/status/${job_id}`);
              if (!statusResp.ok) {
                 if (statusResp.status === 404) {
                     throw new Error("Remix job not found. Please try again.");
                 }
                 throw new Error("Failed to get remix job status.");
              }
              
              const statusData = await statusResp.json();
              if (statusData.status === "complete") {
                  clearInterval(intervalId);
                  setRemixLoading(false);
                  setRemixJobId(null);
                  setRemixBlobUrl(`${API}${statusData.download_url}`);
                  setRemixServerPath(statusData.server_path); 
              } else if (statusData.status === "failed") {
                  clearInterval(intervalId);
                  setRemixLoading(false);
                  setRemixJobId(null);
                  setRemixError(statusData.error || "Remix job failed.");
              }
          } catch (pollError: any) {
              clearInterval(intervalId);
              setRemixLoading(false);
              setRemixJobId(null);
              setRemixError(pollError?.message || "Failed to get job status.");
          }
      }, 5000);

    } catch (e: any) {
        if (intervalId) clearInterval(intervalId);
        setRemixLoading(false);
        setRemixError(e?.message || "Remix error");
    }
  }

  return (
    <div className="container">
      <header className="header">
        <h1>Marketing Flow Automation</h1>
        <p className="muted">
          One form: URL + Keyword → Page insights + Trends + Generated Draft. Plus: TikTok viral analyzer & Auto subtitle.
        </p>
      </header>

      {/* ===== MVP Panel (No Changes) ===== */}
      <section className="card">
        <h2>URL analyzer</h2>
        <div className="grid2">
          <div>
            <label>URL</label>
            <input
              placeholder="https://example.com/article"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
            />
          </div>
          <div>
            <label>Keyword</label>
            <input placeholder="keyword" value={keyword} onChange={(e) => setKeyword(e.target.value)} />
          </div>
          <div className="right">
            <button onClick={runMVP} disabled={!url || !keyword || loading}>
              {loading ? "Running..." : "Run"}
            </button>
          </div>
        </div>

        {/* --- SỬA LỖI: HIỂN THỊ LỖI --- */}
        {error && <div className="pill error">Error: {error}</div>}
        
        {/* --- SỬA LỖI: HIỂN THỊ LỖI SHEET (NẾU CÓ) --- */}
        {result?.sheet_export_error && (
            <div className="pill error" style={{marginTop: "10px"}}>
                Sheet Error: {result.sheet_export_error}
            </div>
        )}

        {result && (
          <div className="resultGrid">
            {result?.fields?.title && <div className="pill"><b>Page Title</b>: {result.fields.title}</div>}
            <div className="resultCol">
              <h3>Insights (from URL)</h3>
              <h4>Strengths</h4>
              <ul>{(result.insights?.strengths || []).map((s: string, i: number) => (<li key={i}>{s}</li>))}</ul>
              <h4>Weaknesses</h4>
              <ul>{(result.insights?.weaknesses || []).map((s: string, i: number) => (<li key={i}>{s}</li>))}</ul>
              <h4>Content Formula</h4>
              <p>{result.insights?.formula || "—"}</p>
              <h4>Improvements</h4>
              <ul>{(result.insights?.improvements || []).map((s: string, i: number) => (<li key={i}>{s}</li>))}</ul>
              <h4>SEO Suggestions</h4>
              <pre className="pre">{JSON.stringify(result.insights?.seo || {}, null, 2)}</pre>
            </div>
            <div className="resultCol resultDraft">
              <div className="compactTrends">
                <div className="flexBetween" style={{ marginBottom: 8 }}>
                  <h3 style={{ margin: 0 }}>Keyword Queries ({result.keyword})</h3>
                </div>
                <div style={{ marginBottom: 8 }}>
                  <div className="muted" style={{ fontSize: 12, marginBottom: 6 }}>Top Queries</div>
                  {result.trends?.top_queries?.length ? (
                    <div className="pillRow">
                      {result.trends.top_queries.slice(0, 12).map((q: any, i: number) => (
                        <span key={i} className="chip">
                          {q?.query ?? ""} {typeof q?.value !== "undefined" ? <b>· {q.value}</b> : null}
                        </span>
                      ))}
                    </div>
                  ) : (
                    <div className="muted">No top queries.</div>
                  )}
                </div>
                <div>
                  <div className="muted" style={{ fontSize: 12, marginBottom: 6 }}>Rising Queries</div>
                  {result.trends?.rising_queries?.length ? (
                    <div className="pillRow">
                      {result.trends.rising_queries.slice(0, 12).map((q: any, i: number) => (
                        <span key={i} className="chip">
                          {q?.query ?? ""} {typeof q?.value !== "undefined" ? <b>· {q.value}</b> : null}
                        </span>
                      ))}
                    </div>
                  ) : (
                    <div className="muted">No rising queries.</div>
                  )}
                </div>
              </div>
              <div className="flexBetween" style={{ marginTop: 12, marginBottom: 8 }}>
                <h3 style={{ margin: 0 }}>Generated Draft</h3>
                <label style={{ fontSize: 13, display: "flex", gap: 8, alignItems: "center" }}>
                  <input
                    type="checkbox"
                    checked={showShortDraft}
                    onChange={(e) => setShowShortDraft(e.target.checked)}
                  />
                  Short version
                </label>
              </div>
              <textarea
                className="draft"
                style={showShortDraft ? { minHeight: 180 } : undefined}
                value={showShortDraft ? shortDraft : (result?.draft || "")}
                readOnly
              />
              {showShortDraft && result?.draft && result.draft.length > shortDraft.length && (
                <div className="muted" style={{ marginTop: 6 }}>
                  Showing a condensed draft (~{shortDraft.length} chars). Uncheck to view full.
                </div>
              )}
            </div>
            <details className="raw">
              <summary>Raw JSON</summary>
              <pre className="pre">{JSON.stringify(result, null, 2)}</pre>
            </details>
          </div>
        )}
      </section>

      {/* ===== TikTok Video Analyze Panel ===== */}
      <section className="card" style={{ marginTop: 24 }}>
        <h2>TikTok Video Analyzer</h2>
        <div className="grid2">
          <div>
            <label>TikTok URL</label>
            <input
              placeholder="https://www.tiktok.com/@user/video/123456789"
              value={ttUrl}
              onChange={(e) => setTtUrl(e.target.value)}
            />
          </div>
          <div>
            <label>Audio format</label>
            <select value={audioExt} onChange={(e) => setAudioExt(e.target.value as ".mp3" | ".wav")}>
              <option value=".mp3">MP3</option>
              <option value=".wav">WAV</option>
            </select>
          </div>
          <div>
            <label>Min gap (frames)</label>
            <input
              type="number"
              min={1}
              value={minGapFrames}
              onChange={(e) => setMinGapFrames(parseInt(e.target.value || "10", 10))}
            />
          </div>
          <div className="right">
            <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
              <div style={{ flex: 1 }}>
                <label>Scene sensitivity ({sceneSensitivity.toFixed(2)})</label>
                <input
                  type="range"
                  min={0.1}
                  max={0.9}
                  step={0.01}
                  value={sceneSensitivity}
                  onChange={(e) => setSceneSensitivity(parseFloat(e.target.value))}
                  style={{ width: "100%" }}
                />
              </div>
              <button onClick={runViralAnalyze} disabled={!ttUrl || vaLoading}>
                {vaLoading ? "Analyzing..." : "Analyze"}
              </button>
            </div>
          </div>
        </div>
        {vaError && <div className="pill error">Error: {vaError}</div>}
        {vaData && (
          <div className="resultGrid">
            <div className="pill"><b>Scenes</b>: {vaData.stats?.count ?? 0}</div>
            <div className="pill"><b>Mean</b>: {fmtTime(vaData.stats?.mean || 0)}</div>
            <div className="pill"><b>Median</b>: {fmtTime(vaData.stats?.median || 0)}</div>
            <div className="pill"><b>p90</b>: {fmtTime(vaData.stats?.p90 || 0)}</div>
            <div className="pill"><b>Shortest</b>: {fmtTime(vaData.stats?.shortest || 0)}</div>
            <div className="pill"><b>Longest</b>: {fmtTime(vaData.stats?.longest || 0)}</div>
            <div className="resultCol">
              <h3>Extracted Audio ({vaData.audio_format?.toUpperCase()})</h3>
              {audioUrl ? (
                <>
                  <audio controls src={`${API}${audioUrl.startsWith("/media/") ? audioUrl : audioUrl}`} className="w-full" />
                  <div style={{ marginTop: 8, display: "flex", gap: 8 }}>
                    <a className="downloadBtn" href={`${API}${audioUrl.startsWith("/media/") ? audioUrl : audioUrl}`} download>
                      Download audio
                    </a>
                    <button className="copyBtn" onClick={() => copy(`${API}${audioUrl.startsWith("/media/") ? audioUrl : audioUrl}`)}>
                      Copy audio URL
                    </button>
                  </div>
                </>
              ) : (
                <p className="muted">No audio URL from server. Path: {vaData.audio_path}</p>
              )}
            </div>
            <div className="resultCol">
              <h3>Source</h3>
              <p className="muted" style={{ wordBreak: "break-all" }}>{vaData.source_url}</p>
              {videoUrl ? (
                <p style={{ marginTop: 8 }}>
                  <a className="downloadBtn" href={`${API}${videoUrl.startsWith("/media/") ? videoUrl : videoUrl}`} target="_blank" rel="noreferrer">
                    Open downloaded video
                  </a>
                </p>
              ) : null}
              <div className="muted" style={{ fontSize: 12, marginTop: 8 }}>Server file:</div>
              <code className="pre" style={{ display: "block", whiteSpace: "pre-wrap" }}>{vaData.video_path}</code>
            </div>

            <div className="resultCol" style={{ gridColumn: "1 / -1" }}>
              <div className="flexBetween">
                <h3>Scene Durations</h3>
                <div className="muted">Total: {fmtTime(totalSceneDuration)}</div>
              </div>
              <div className="tableWrap">
                <table className="table">
                  <thead>
                    <tr>{/* XÓA KHOẢNG TRẮNG THỪA */}
                      <th title="Select for Remix">Remix?</th>
                      <th>#</th>
                      <th>Start</th>
                      <th>End</th>
                      <th>Duration</th>
                      <th />
                    </tr>{/* XÓA KHOẢNG TRẮNG THỪA */}
                  </thead>
                  <tbody>
                    {vaData.scenes.map((s, i) => (
                      <tr key={i} className={selectedSceneIndices.has(i) ? "selected" : ""}>
                        <td>
                          <input
                            type="checkbox"
                            checked={selectedSceneIndices.has(i)}
                            onChange={() => handleSceneToggle(i)}
                            title={`Select scene ${i+1} for remix`}
                          />
                        </td>
                        <td>{i + 1}</td>
                        <td className="mono">{fmtTime(s.start_sec)}</td>
                        <td className="mono">{fmtTime(s.end_sec)}</td>
                        <td className="mono">{fmtTime(s.duration_sec)}</td>
                        <td className="right">
                          <button
                            className="copyBtn"
                            onClick={() => copy(`${s.start_sec.toFixed(3)},${s.end_sec.toFixed(3)}`)}
                            title="Copy start,end seconds"
                          >
                            Copy times
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <details className="raw" style={{ marginTop: 12 }}>
                <summary>Raw JSON</summary>
                <pre className="pre">{JSON.stringify(vaData, null, 2)}</pre>
              </details>
            </div>

            <div className="resultCol" style={{ gridColumn: "1 / -1" }}>
              <h3>Remix Video (Custom)</h3>
              <p className="muted" style={{ marginBottom: 12 }}>
                Select scenes from the "Scene Durations" table above, then click here to create a new video.
              </p>
              <button 
                onClick={handleRemix} 
                disabled={remixLoading || !vaData || selectedSceneIndices.size === 0}
              >
                {remixLoading 
                  ? `Remixing... (Job: ${remixJobId?.slice(0, 8)}...)` 
                  : `Remix ${selectedSceneIndices.size} Selected Scenes`}
              </button>

              {remixError && <div className="pill error" style={{marginTop: 12}}>Error: {remixError}</div>}
              {remixLoading && !remixError && (
                <div className="pill" style={{ marginTop: 12 }}>
                  Remix job is processing...
                </div>
              )}

              {remixBlobUrl && (
                <div className="resultCol" style={{ marginTop: 16 }}>
                  <h3>Remix Preview / Download</h3>
                  <video controls src={remixBlobUrl} style={{ width: "100%", borderRadius: 12 }} />
                  <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: '8px' }}>
                    <a className="downloadBtn" href={remixBlobUrl} download>
                      Download Remix
                    </a>
                    {remixServerPath && (
                      <div>
                        <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>Server file:</div>
                        <code className="pre" style={{ display: "block", whiteSpace: "pre-wrap", fontSize: '12px' }}>
                          {remixServerPath}
                        </code>
                      </div>
                    )}
                  </div>
                </div>
              )}
            </div>

            {vaData.content_deliverables && (
              <div className="resultCol" style={{ gridColumn: "1 / -1" }}>
                <h3>3.1 Content — Carousel & Captions</h3>
                <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 10 }}>
                  {vaData.content_deliverables.carousel_images?.length ? (
                    <a
                      className="downloadBtn"
                      href={`${API}${vaData.content_deliverables.carousel_images[0]}`}
                      target="_blank"
                      rel="noreferrer"
                    >
                      View Carousel
                    </a>
                  ) : null}
                  {vaData.content_deliverables.carousel_zip_url ? (
                    <a
                      className="downloadBtn"
                      href={`${API}${vaData.content_deliverables.carousel_zip_url}`}
                      target="_blank"
                      rel="noreferrer"
                    >
                      Download Carousel (.zip)
                    </a>
                  ) : null}
                </div>
                {vaData.content_deliverables.carousel_images?.length ? (
                  <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(140px, 1fr))", gap: 8 }}>
                    {vaData.content_deliverables.carousel_images.map((u: string, idx: number) => (
                      <a key={idx} href={`${API}${u}`} target="_blank" rel="noreferrer" className="thumbLink">
                        <img src={`${API}${u}`} alt={`carousel-${idx+1}`} style={{ width: "100%", borderRadius: 8 }} />
                      </a>
                    ))}
                  </div>
                ) : (
                  <p className="muted">No carousel images were generated.</p>
                )}
                <div style={{ marginTop: 12, display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: 12 }}>
                  <div>
                    <h4>Facebook</h4>
                    <textarea className="draft" readOnly value={captionsFromMVP.facebook || ""} />
                  </div>
                  <div>
                    <h4>Instagram</h4>
                    <textarea className="draft" readOnly value={captionsFromMVP.instagram || ""} />
                  </div>
                  <div>
                    <h4>TikTok</h4>
                    <textarea className="draft" readOnly value={captionsFromMVP.tiktok || ""} />
                  </div>
                  <div>
                    <h4>YouTube Shorts</h4>
                    <textarea className="draft" readOnly value={captionsFromMVP.youtube_shorts || ""} />
                  </div>
                </div>
                <div style={{ marginTop: 12 }}>
                  <button className="downloadBtn" onClick={downloadDeliverablesCSV}>
                    Download CSV (clean captions)
                  </button>
                </div>
              </div>
            )}
          </div>
        )}
      </section>

      {/* ===== Auto Subtitle + BGM Panel (No Changes) ===== */}
      <section className="card" style={{ marginTop: 24 }}>
        <h2>Auto Subtitle + Optional BGM</h2>
        <div className="grid2">
          <div>
            <label>Video file</label>
            <input type="file" accept="video/*" onChange={(e) => setVidFile(e.target.files?.[0] ?? null)} />
          </div>
          <div>
            <label>Background music (optional)</label>
            <input type="file" accept="audio/*" onChange={(e) => setBgmFile(e.target.files?.[0] ?? null)} />
          </div>
          <div>
            <label>Burn subtitles?</label>
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <input type="checkbox" checked={burnIn} onChange={(e) => setBurnIn(e.target.checked)} />
              <span className="muted">{burnIn ? "MP4 (hard subs)" : "MKV (soft SRT)"}</span>
            </div>
          </div>
          <div>
            <label>Language hint (blank = auto)</label>
            <input value={langHint} onChange={(e) => setLangHint(e.target.value)} placeholder='e.g., "vi" or "en"' />
          </div>
          <div>
            <label>Flip Video?</label>
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <input
                type="checkbox"
                checked={flipVideo}
                onChange={(e) => setFlipVideo(e.target.checked)}
              />
              <span className="muted">{flipVideo ? "Yes (Flipped)" : "No (Original)"}</span>
            </div>
          </div>
          <div className="right">
            <button onClick={handleProcess} disabled={!vidFile || procLoading}>
              {procLoading ? `Processing... (Job: ${currentJobId?.slice(0, 8)}...)` : "Generate"}
            </button>
          </div>
        </div>
        {procError && <div className="pill error">Error: {procError}</div>}
        {procLoading && !procError && (
          <div className="pill" style={{ marginTop: 16 }}>
            Processing job... This may take several minutes for long videos.
          </div>
        )}
        {procBlobUrl && (
          <div className="resultCol" style={{ marginTop: 16 }}>
            <h3>Preview / Download</h3>
            <video controls src={procBlobUrl} style={{ width: "100%", borderRadius: 12 }} />
            <div style={{ marginTop: 8 }}>
              <a className="downloadBtn" href={procBlobUrl} download>
                Download result
              </a>
            </div>
          </div>
        )}
      </section>

      {/* --- CSS (Đã sửa lỗi DOM nesting) --- */}
      <style jsx>{`
        .container { max-width: 980px; margin: 24px auto; padding: 0 16px; }
        .header h1 { margin: 0; font-size: 28px; }
        .muted { color: #6b7280; }
        .card { border: 1px solid #e5e7eb; border-radius: 14px; padding: 16px; background: #fff; }
        input, select { padding: 10px 12px; border: 1px solid #e5e7eb; border-radius: 10px; width: 100%; }
        textarea.draft { width: 100%; min-height: 220px; padding: 10px 12px; border: 1px solid #e5e7eb; border-radius: 10px; }
        button { padding: 10px 14px; border: none; border-radius: 10px; background: #111827; color: #fff; cursor: pointer; }
        button:disabled { opacity: 0.6; cursor: not-allowed; }
        .grid2 { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; align-items: end; }
        .right { text-align: right; grid-column: 1 / -1; }
        .resultGrid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; margin-top: 16px; }
        .resultCol { border: 1px solid #f1f5f9; border-radius: 14px; padding: 12px; background: #fafafa; }
        .resultDraft { grid-column: span 2; }
        textarea.draft {
          width: 100%;
          min-height: 300px;
          padding: 12px 14px;
          border: 1px solid #e5e7eb;
          border-radius: 10px;
          font-size: 15px;
          line-height: 1.5;
        }
        .pill { display: inline-block; padding: 8px 12px; border-radius: 9999px; background: #eef2ff; border: 1px solid #c7d2fe; margin-top: 10px; }
        .pill.error { background: #fee2e2; border-color: #fecaca; }
        .pre { overflow: auto; background: #0b1020; color: #e5e7eb; padding: 10px; border-radius: 8px; }
        details.raw { grid-column: 1 / -1; }
        .downloadBtn { padding: 8px 12px; border-radius: 10px; background: #111827; color: #fff; text-decoration: none; }
        .copyBtn { padding: 8px 12px; border-radius: 10px; border: 1px solid #e5e7eb; background: #fff; }
        .flexBetween { display: flex; align-items: center; justify-content: space-between; }
        .tableWrap { max-height: 420px; overflow: auto; border: 1px solid #e5e7eb; border-radius: 12px; }
        .table { width: 100%; border-collapse: collapse; font-size: 14px; }
        .table thead { position: sticky; top: 0; background: #f8fafc; }
        .table th, .table td { padding: 8px 12px; border-bottom: 1px solid #eef2f7; text-align: left; }
        .table td.right { text-align: right; }
        .mono { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace; }
        .thumbLink img { transition: transform .12s ease; }
        .thumbLink:hover img { transform: scale(1.01); }
        .compactTrends { background: #fff; border: 1px solid #e5e7eb; border-radius: 10px; padding: 10px; }
        .pillRow { display: flex; flex-wrap: wrap; gap: 6px; }
        .chip {
          display: inline-flex;
          align-items: center;
          gap: 6px;
          padding: 6px 10px;
          background: #f8fafc;
          border: 1px solid #e5e7eb;
          border-radius: 9999px;
          font-size: 13px;
        }
        
        .table tbody tr:hover { background: #f9fafb; }
        .table tbody tr.selected { background: #eef2ff; }
        
        .table th:first-child, .table td:first-child {
          width: 60px;
          text-align: center;
        }
        .table td:first-child input {
          width: 16px;
          height: 16px;
          cursor: pointer;
        }

        @media (max-width: 900px){
          .grid2 { grid-template-columns: 1fr; }
          .resultGrid { grid-template-columns: 1fr; }
        }
      `}</style>
    </div>
  );
}