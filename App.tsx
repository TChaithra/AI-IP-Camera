// src/App.tsx - FIXED REAL-TIME PROFILING WITH DYNAMIC UI UPDATES
import React, { useEffect, useState, useCallback, useRef } from "react";
import {
  getCameras,
  getModels,
  getBoards,
  startJob,
  stopJob,
  getRecentEvents,
  pauseVideo,
  resumeVideo,
  getProfiling,
  Board,
  CameraItem,
  ModelItem,
  Event,
  ProfilingData,
  BACKEND,
} from "./api";

/* =============================================================================
   COMPONENT
   ============================================================================= */
function App() {
  // Theme & UI State
  const [isDarkTheme, setIsDarkTheme] = useState(false);
  const [now, setNow] = useState<string>("");
  
  // Board & Resource Selection
  const [boards, setBoards] = useState<Board[]>([]);
  const [cameras, setCameras] = useState<CameraItem[]>([]);
  const [models, setModels] = useState<ModelItem[]>([]);
  const [selectedBoardId, setSelectedBoardId] = useState<string>("");
  const [selectedCameraId, setSelectedCameraId] = useState<string>("");
  const [selectedModelId, setSelectedModelId] = useState<string>("");
  
  // Job & Streaming State
  const [jobId, setJobId] = useState<string | null>(null);
  const [streamUrl, setStreamUrl] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [isPaused, setIsPaused] = useState(false);
  const [imageLoaded, setImageLoaded] = useState(false);
  const [streamError, setStreamError] = useState<string | null>(null);
  const [countdown, setCountdown] = useState(0);
  const [loadingModels, setLoadingModels] = useState(false);
  
  // Events & Data
  const [events, setEvents] = useState<Event[]>([]);
  const [selectedEvent, setSelectedEvent] = useState<Event | null>(null);
  const [savedFrames, setSavedFrames] = useState<any[]>([]);
  
  // Profiling Data
  const [profiling, setProfiling] = useState<ProfilingData | null>(null);
  
  // Video Display State
  const [isVideoMinimized, setIsVideoMinimized] = useState(false);
  const [isVideoFullscreen, setIsVideoFullscreen] = useState(false);
  
  // Refs for intervals
  const jobIdRef = useRef<string | null>(null);
  const eventsIntervalRef = useRef<NodeJS.Timeout | null>(null);
  const profilingIntervalRef = useRef<NodeJS.Timeout | null>(null);
  const savedFramesIntervalRef = useRef<NodeJS.Timeout | null>(null);

  useEffect(() => {
    jobIdRef.current = jobId;
  }, [jobId]);


  /* =============================================================================
     THEME MANAGEMENT
     ============================================================================= */
  useEffect(() => {
    const saved = localStorage.getItem("theme");
    if (saved === "dark") setIsDarkTheme(true);
  }, []);

  useEffect(() => {
    localStorage.setItem("theme", isDarkTheme ? "dark" : "light");
  }, [isDarkTheme]);


  /* =============================================================================
     CLOCK
     ============================================================================= */
  useEffect(() => {
    const t = setInterval(() => {
      setNow(
        new Date().toLocaleString("en-US", {
          hour12: true,
          hour: "2-digit",
          minute: "2-digit",
          second: "2-digit",
        })
      );
    }, 1000);
    return () => clearInterval(t);
  }, []);


  /* =============================================================================
     INITIAL DATA LOADING
     ============================================================================= */
  useEffect(() => {
    (async () => {
      try {
        const list = await getBoards();
        setBoards(list);
      } catch (e) {
        console.error("[UI] boards load:", e);
      }
    })();
  }, []);


  /* =============================================================================
     CAMERAS & MODELS LOADING
     ============================================================================= */
  useEffect(() => {
    if (!selectedBoardId) {
      setCameras([]);
      setModels([]);
      return;
    }
    
    (async () => {
      setLoadingModels(true);
      try {
        const [c, m] = await Promise.all([
          getCameras(selectedBoardId),
          getModels(selectedBoardId),
        ]);
        setCameras(c);
        setModels(m);
      } catch (e) {
        console.error("[UI] cameras/models:", e);
      } finally {
        setLoadingModels(false);
      }
    })();
  }, [selectedBoardId]);


  /* =============================================================================
     EVENTS POLLING
     ============================================================================= */
  useEffect(() => {
    if (!jobId) {
      if (eventsIntervalRef.current) clearInterval(eventsIntervalRef.current);
      return;
    }
    
    loadEvents();
    eventsIntervalRef.current = setInterval(loadEvents, 3000);
    
    return () => {
      if (eventsIntervalRef.current) clearInterval(eventsIntervalRef.current);
    };
  }, [jobId]);

  const loadEvents = async () => {
    try {
      const ev = await getRecentEvents(20);
      setEvents(ev);
    } catch (e) {
      console.error("[UI] events:", e);
    }
  };


  /* =============================================================================
     PROFILING POLLING - FIXED FOR DYNAMIC UPDATES
     ============================================================================= */
  useEffect(() => {
    if (!jobId) {
      if (profilingIntervalRef.current) clearInterval(profilingIntervalRef.current);
      setProfiling(null);
      return;
    }
    
    loadProfiling();
    // FIXED: Poll every 500ms for real-time updates
    profilingIntervalRef.current = setInterval(loadProfiling, 500);
    
    return () => {
      if (profilingIntervalRef.current) clearInterval(profilingIntervalRef.current);
    };
  }, [jobId]);

  const loadProfiling = async () => {
    if (!jobId) return;
    try {
      const data = await getProfiling(jobId);
      if (data) {
        setProfiling(data);
        console.log(`[UI] Profiling update: FPS=${data.fps}, Frames=${data.frame_count}, Inference=${data.inference_ms}ms`);
      }
    } catch (e) {
      console.error("[UI] profiling error:", e);
    }
  };


  /* =============================================================================
     SAVED FRAMES POLLING
     ============================================================================= */
  useEffect(() => {
    if (!jobId) {
      if (savedFramesIntervalRef.current) clearInterval(savedFramesIntervalRef.current);
      setSavedFrames([]);
      return;
    }
    
    loadSavedFrames();
    savedFramesIntervalRef.current = setInterval(loadSavedFrames, 5000);
    
    return () => {
      if (savedFramesIntervalRef.current) clearInterval(savedFramesIntervalRef.current);
    };
  }, [jobId]);

  const loadSavedFrames = async () => {
    try {
      const response = await fetch(`${BACKEND}/saved_frames`);
      if (response.ok) {
        const frames = await response.json();
        setSavedFrames(frames);
      }
    } catch (e) {
      console.error("[UI] saved frames:", e);
    }
  };


  /* =============================================================================
     COUNTDOWN HELPER
     ============================================================================= */
  useEffect(() => {
    if (countdown <= 0) return;
    const t = setInterval(() => setCountdown((c) => Math.max(0, c - 1)), 1000);
    return () => clearInterval(t);
  }, [countdown]);


  /* =============================================================================
     UI HELPERS
     ============================================================================= */
  const canStart = selectedBoardId && selectedCameraId && selectedModelId && !busy && !jobId;
  const canStop = !!jobId && !busy;
  const canPause = !!jobId && !busy;


  /* =============================================================================
     JOB CONTROLS
     ============================================================================= */
  const onStart = useCallback(async () => {
    if (!canStart) return;
    
    setBusy(true);
    setImageLoaded(false);
    setStreamError(null);
    setCountdown(8);
    setIsPaused(false);
    
    if (jobId) await new Promise((r) => setTimeout(r, 3000)); // cleanup delay
    
    try {
      const res = await startJob(selectedBoardId, selectedCameraId, selectedModelId);
      setJobId(res.job_id);
      setTimeout(() => setStreamUrl(res.stream_url), 8000);
    } catch (e: any) {
      console.error("[UI] start:", e);
      setStreamError(`Failed to start: ${e.message}`);
      alert("Start failed: " + e.message);
      setJobId(null);
      setStreamUrl("");
    } finally {
      setBusy(false);
    }
  }, [canStart, jobId, selectedBoardId, selectedCameraId, selectedModelId]);


  const onStop = useCallback(async () => {
    if (!jobId || busy) return;
    
    setBusy(true);
    try {
      await stopJob(jobId);
      setJobId(null);
      setStreamUrl("");
      setImageLoaded(false);
      setStreamError(null);
      setCountdown(0);
      setIsPaused(false);
      setEvents([]);
      setSelectedEvent(null);
      setProfiling(null);
      setSavedFrames([]);
      setIsVideoMinimized(false);
    } catch (e: any) {
      alert("Stop failed: " + e.message);
    } finally {
      setBusy(false);
    }
  }, [jobId, busy]);


  const onPause = useCallback(async () => {
    if (!jobId || !selectedBoardId) return;
    
    setBusy(true);
    try {
      if (isPaused) {
        await resumeVideo(selectedBoardId);
        setIsPaused(false);
      } else {
        await pauseVideo(selectedBoardId);
        setIsPaused(true);
      }
    } catch (e: any) {
      alert("Pause/resume failed: " + e.message);
    } finally {
      setBusy(false);
    }
  }, [jobId, selectedBoardId, isPaused]);


  /* =============================================================================
     STREAM HANDLERS
     ============================================================================= */
  const handleImageLoad = useCallback(() => {
    setImageLoaded(true);
    setStreamError(null);
  }, []);

  const handleImageError = useCallback(() => {
    setImageLoaded(false);
    if (countdown === 0 && streamUrl && jobId)
      setStreamError("Connection error. Retrying...");
  }, [countdown, streamUrl, jobId]);


  /* =============================================================================
   VIDEO HEADER COMPONENT
   ============================================================================= */
  const VideoHeader = () => (
    <div className="video-header-inner">
      {jobId && imageLoaded && <span className="live-badge">● LIVE</span>}
      {countdown > 0 && <span className="status-badge">Initializing... {countdown}s</span>}
      {profiling && (
        <>
          <span className="profiling-left">
            FPS: {profiling.fps.toFixed(1)} | Frame: {profiling.frame_count} | {profiling.resolution}
          </span>
          <span className="profiling-right">
            Model: {profiling.model} | Inference: {profiling.inference_ms.toFixed(1)}ms
          </span>
        </>
      )}
    </div>
  );


  /* =============================================================================
     RENDER
     ============================================================================= */
  const themeClass = isDarkTheme ? "app-dark" : "app-white";

  return (
    <div className={`app-container ${themeClass}`}>
      
      {/* ---------------- TOPBAR ---------------- */}
      <div className={isDarkTheme ? "topbar-dark" : "topbar-white"}>
        <div className={isDarkTheme ? "topbar-left-dark" : "topbar-left-white"}>
          <div className={isDarkTheme ? "app-title-dark" : "app-title-white"}>
            <svg className={isDarkTheme ? "icon-camera-dark" : "icon-camera-white"} viewBox="0 0 24 24" fill="currentColor">
              <path d="M17 10.5V7c0-.55-.45-1-1-1H4c-.55 0-1 .45-1 1v10c0 .55.45 1 1 1h12c.55 0 1-.45 1-1v-3.5l4 4v-11l-4 4z" />
            </svg>
            <div>
              <h1>Smart Traffic Detection</h1>
              <span className={isDarkTheme ? "platform-dark" : "platform-white"}>IMX8M+ NPU LIVE-STREAMING</span>
            </div>
          </div>
        </div>
        
        <div className={isDarkTheme ? "topbar-right-dark" : "topbar-right-white"}>
          <button onClick={() => setIsDarkTheme((t) => !t)} className={isDarkTheme ? "theme-toggle-dark" : "theme-toggle-white"} title="Toggle theme">
            {isDarkTheme ? (
              <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
                <path d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z" />
              </svg>
            ) : (
              <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
                <path d="M21 12.79A9 9 0 1111.21 3 7 7 0 0021 12.79z" />
              </svg>
            )}
          </button>
          <div className={isDarkTheme ? "time-box-dark" : "time-box-white"}>{now}</div>
        </div>
      </div>


      {/* ---------------- MAIN LAYOUT ---------------- */}
      <div className="main-layout">
        
        {/* -------- LEFT PANEL -------- */}
        <div className="left-panel">
          
          {/* Board Selection */}
          <div className="control-card">
            <h3 className="card-title">Select Board</h3>
            <select
              className={isDarkTheme ? "select-dark" : "select-white"}
              value={selectedBoardId}
              onChange={(e) => {
                setSelectedBoardId(e.target.value);
                setSelectedCameraId("");
                setSelectedModelId("");
              }}
              disabled={!!jobId || busy}
            >
              <option value="">-- Select Board --</option>
              {boards.map((b) => (
                <option key={b.id} value={b.id}>
                  {b.name}
                </option>
              ))}
            </select>
          </div>

          {/* Model Selection */}
          <div className="control-card">
            <h3 className="card-title">
              AI Model
              {loadingModels && <span style={{ fontSize: "0.75rem", color: "#718096" }}> Loading...</span>}
            </h3>
            <select
              className={isDarkTheme ? "select-dark" : "select-white"}
              value={selectedModelId}
              onChange={(e) => setSelectedModelId(e.target.value)}
              disabled={!!jobId || busy || !selectedBoardId || loadingModels}
            >
              <option value="">-- Select Model --</option>
              {models.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.name}
                </option>
              ))}
            </select>
          </div>

          {/* Camera Selection */}
          <div className="control-card">
            <h3 className="card-title">Camera Source</h3>
            <select
              className={isDarkTheme ? "select-dark" : "select-white"}
              value={selectedCameraId}
              onChange={(e) => setSelectedCameraId(e.target.value)}
              disabled={!!jobId || busy || !selectedBoardId}
            >
              <option value="">-- Select Camera --</option>
              {cameras.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          </div>

          {/* Control Buttons */}
          <div className="button-group">
            <button
              className={`btn-${isDarkTheme ? "dark" : "white"} btn-start-${isDarkTheme ? "dark" : "white"}`}
              disabled={!canStart}
              onClick={onStart}
            >
              Start Camera
            </button>
            <button
              className={`btn-${isDarkTheme ? "dark" : "white"} btn-pause-${isDarkTheme ? "dark" : "white"}`}
              disabled={!canPause}
              onClick={onPause}
            >
              {isPaused ? "Resume" : "Pause"} Detection
            </button>
            <button
              className={`btn-${isDarkTheme ? "dark" : "white"} btn-stop-${isDarkTheme ? "dark" : "white"}`}
              disabled={!canStop}
              onClick={onStop}
            >
              Stop Camera
            </button>
          </div>

          {/* FIXED: Performance Section with Alert-like Format */}
          {profiling && (
            <div className="control-card performance-section">
              <h3 className="card-title">⚡ Performance Metrics</h3>
              
              {/* Alert-style performance summary */}
              <div style={{
                background: isDarkTheme ? "#0f172a" : "#f7fafc",
                border: `1px solid ${isDarkTheme ? "#334155" : "#e2e8f0"}`,
                borderRadius: "8px",
                padding: "1rem",
                marginBottom: "1rem"
              }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.5rem" }}>
                  <span style={{ fontSize: "0.8125rem", color: isDarkTheme ? "#94a3b8" : "#718096" }}>
                    FPS: {profiling.fps.toFixed(1)}
                  </span>
                  <span style={{ fontSize: "0.8125rem", color: isDarkTheme ? "#94a3b8" : "#718096" }}>
                    Frame: {profiling.frame_count}
                  </span>
                </div>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.5rem" }}>
                  <span style={{ fontSize: "0.8125rem", color: isDarkTheme ? "#94a3b8" : "#718096" }}>
                    Model: {profiling.model}
                  </span>
                  <span style={{ fontSize: "0.8125rem", color: isDarkTheme ? "#94a3b8" : "#718096" }}>
                    Inference: {profiling.inference_ms.toFixed(1)}ms
                  </span>
                </div>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <span style={{ fontSize: "0.8125rem", color: isDarkTheme ? "#94a3b8" : "#718096" }}>
                    {profiling.resolution}
                  </span>
                  <span style={{ fontSize: "0.8125rem", color: isDarkTheme ? "#94a3b8" : "#718096" }}>
                    Status: {profiling.streaming ? "Live" : "Paused"}
                  </span>
                </div>
              </div>
              
              {/* Original performance grid below */}
              <div className="performance-grid">
                <div className="performance-item">
                  <div className="status-dot active"></div>
                  <div>
                    <div className="status-label">FPS</div>
                    <div className="status-value">{profiling.fps.toFixed(1)}</div>
                  </div>
                </div>
                <div className="performance-item">
                  <div className="status-dot active"></div>
                  <div>
                    <div className="status-label">Frames</div>
                    <div className="status-value">{profiling.frame_count}</div>
                  </div>
                </div>
                <div className="performance-item">
                  <div className="status-dot active"></div>
                  <div>
                    <div className="status-label">Inference</div>
                    <div className="status-value">{profiling.inference_ms.toFixed(1)}ms</div>
                  </div>
                </div>
                <div className="performance-item">
                  <div className="status-dot active"></div>
                  <div>
                    <div className="status-label">Resolution</div>
                    <div className="status-value">{profiling.resolution}</div>
                  </div>
                </div>
                <div className="performance-item">
                  <div className="status-dot active"></div>
                  <div>
                    <div className="status-label">Model</div>
                    <div className="status-value">{profiling.model}</div>
                  </div>
                </div>
                <div className="performance-item">
                  <div className="status-dot active"></div>
                  <div>
                    <div className="status-label">Status</div>
                    <div className="status-value">{profiling.streaming ? "Live" : "Paused"}</div>
                  </div>
                </div>
              </div>
              
              <div style={{ marginTop: "0.5rem", fontSize: "0.75rem", color: isDarkTheme ? "#94a3b8" : "#718096" }}>
                Last update: {profiling.timestamp}
              </div>
            </div>
          )}

          {/* Status Section */}
          <div className="status-section">
            <h3 className="card-title">Status</h3>
            <div className="status-grid">
              <div className="status-item">
                <div className={`status-dot ${jobId ? "active" : "inactive"}`}></div>
                <div>
                  <div className="status-label">Active Traffic Stream</div>
                  <div className="status-value">{jobId ? `(${selectedBoardId})` : "-"}</div>
                </div>
              </div>
              <div className="status-item">
                <div className="status-dot active"></div>
                <div>
                  <div className="status-label">System Health</div>
                  <div className="status-value">100%</div>
                </div>
              </div>
            </div>
          </div>
        </div>


        {/* -------- CENTER PANEL -------- */}
        <div className="center-panel">
          <div className="video-card">
            <div className={isDarkTheme ? "video-header-dark" : "video-header-white"}>
              <VideoHeader />
            </div>
            
            <div className={isDarkTheme ? "video-container-dark" : "video-container-white"}>
              {!jobId ? (
                <div className={isDarkTheme ? "video-empty-dark" : "video-empty-white"}>
                  <svg className={isDarkTheme ? "empty-icon-dark" : "empty-icon-white"} viewBox="0 0 24 24" fill="none" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" />
                  </svg>
                  <p>Click "Start Camera" to begin detection</p>
                </div>
              ) : (
                <>
                  {!imageLoaded && !isPaused && (
                    <div className="video-loading">
                      <div className={isDarkTheme ? "spinner-dark" : "spinner-white"}></div>
                      <p>{countdown > 0 ? `Initializing (${countdown}s)` : "Connecting..."}</p>
                    </div>
                  )}

                  {isPaused ? (
                    <div className="video-paused">
                      <svg width="64" height="64" viewBox="0 0 24 24" fill="currentColor">
                        <path d="M6 4h4v16H6V4zm8 0h4v16h-4V4z" />
                      </svg>
                      <p>Video Stream Paused</p>
                      <small>Inference continues in background</small>
                      <small>Click Resume to show live video</small>
                    </div>
                  ) : (
                    streamUrl && (
                      <>
                        <img
                          key={streamUrl}
                          className={isDarkTheme ? "video-stream-dark" : "video-stream-white"}
                          src={streamUrl}
                          alt="Live Stream"
                          onLoad={handleImageLoad}
                          onError={handleImageError}
                          style={{ display: imageLoaded ? "block" : "none" }}
                        />
                        <div className="video-controls">
                          <button onClick={() => setIsVideoFullscreen(true)} title="Enlarge">
                            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                              <path d="M8 3H5a2 2 0 0 0-2 2v3m18 0V5a2 2 0 0 0-2-2h-3m0 18h3a2 2 0 0 0 2-2v-3M3 16v3a2 2 0 0 0 2 2h3"/>
                            </svg>
                          </button>
                          <button onClick={() => setIsVideoMinimized(true)} title="Minimize">
                            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                              <path d="M8 3v3a2 2 0 0 1-2 2H3m18 0h-3a2 2 0 0 1-2-2V3m0 18v-3a2 2 0 0 1 2-2h3M3 16h3a2 2 0 0 1 2 2v3"/>
                            </svg>
                          </button>
                        </div>
                      </>
                    )
                  )}
                </>
              )}
            </div>
          </div>
        </div>


        {/* -------- RIGHT PANEL -------- */}
        <div className="right-panel">
          
          {/* Events Card */}
          <div className="events-card">
            <h3 className="card-title">
              Recent Alerts
              <button className="sound-toggle" aria-label="Sound">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
                  <path d="M3 9v6h4l5 5V4L7 9H3zm13.5 3c0-1.77-1.02-3.29-2.5-4.03v8.05c1.48-.73 2.5-2.25 2.5-4.02z" />
                </svg>
              </button>
            </h3>
            
            <div className="events-list">
              {events.length === 0 ? (
                <div className="no-events">
                  <p>No alerts yet</p>
                  <p className="no-events-sub">Events will appear here when detected</p>
                </div>
              ) : (
                events.map((ev) => (
                  <div key={ev.event_id} className="event-item" onClick={() => setSelectedEvent(ev)}>
                    <div className="event-icon">⚠️</div>
                    <div className="event-details">
                      <div className="event-header-row">
                        <span className="event-time">{new Date(ev.timestamp).toLocaleTimeString()}</span>
                        <span className="event-plate">{ev.plate_number || "N/A"}</span>
                      </div>
                      <div className="event-type">{ev.event_type}</div>
                      {ev.speed && <div className="event-speed">{ev.speed} km/h</div>}
                    </div>
                    {ev.image_base64 && <img src={ev.image_base64} alt="Event" className="event-thumbnail" />}
                  </div>
                ))
              )}
            </div>
          </div>

          {/* FIXED: Saved Detection Frames Gallery with Full Images */}
          <div className="gallery-card">
            <h3 className="card-title">
              Saved Detection Frames
              <span className="card-subtitle">Frames with bounding boxes</span>
            </h3>
            
            <div className="gallery-grid">
              {savedFrames.length === 0 ? (
                <div className="no-events">
                  <p>No saved frames yet</p>
                  <p className="no-events-sub">Frames with detections will appear here</p>
                </div>
              ) : (
                savedFrames.slice(0, 8).map((frame) => (
                  <div 
                    key={frame.frame_id} 
                    className="gallery-item" 
                    onClick={() => {
                      // FIXED: Show full image in modal when clicked
                      const modal = document.createElement('div');
                      modal.style.position = 'fixed';
                      modal.style.top = '0';
                      modal.style.left = '0';
                      modal.style.width = '100%';
                      modal.style.height = '100%';
                      modal.style.background = 'rgba(0,0,0,0.9)';
                      modal.style.zIndex = '9999';
                      modal.style.display = 'flex';
                      modal.style.alignItems = 'center';
                      modal.style.justifyContent = 'center';
                      modal.style.cursor = 'pointer';
                      
                      const img = document.createElement('img');
                      img.src = frame.image_base64;
                      img.style.maxWidth = '90%';
                      img.style.maxHeight = '90%';
                      img.style.objectFit = 'contain';
                      img.style.borderRadius = '8px';
                      
                      const info = document.createElement('div');
                      info.style.position = 'absolute';
                      info.style.bottom = '20px';
                      info.style.left = '50%';
                      info.style.transform = 'translateX(-50%)';
                      info.style.background = 'rgba(0,0,0,0.8)';
                      info.style.color = 'white';
                      info.style.padding = '10px 20px';
                      info.style.borderRadius = '4px';
                      info.style.fontSize = '14px';
                      info.innerHTML = `
                        <div><strong>Frame:</strong> ${frame.frame_id}</div>
                        <div><strong>Time:</strong> ${new Date(frame.timestamp).toLocaleTimeString()}</div>
                        <div><strong>Detections:</strong> ${frame.detections}</div>
                        <div><strong>Model:</strong> ${frame.model_id}</div>
                      `;
                      
                      modal.appendChild(img);
                      modal.appendChild(info);
                      document.body.appendChild(modal);
                      modal.onclick = () => document.body.removeChild(modal);
                    }}
                  >
                    <img src={frame.image_base64} alt="Saved frame" />
                    <div className="gallery-label">
                      {new Date(frame.timestamp).toLocaleTimeString()} - {frame.detections} detections
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      </div>


      {/* ---------------- MINIMIZED VIDEO ---------------- */}
      {isVideoMinimized && streamUrl && (
        <div className="video-minimized">
          <img src={streamUrl} alt="Minimized Stream" />
          <div className="mini-controls">
            <button onClick={() => setIsVideoFullscreen(true)} title="Enlarge">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="2">
                <path d="M8 3H5a2 2 0 0 0-2 2v3m18 0V5a2 2 0 0 0-2-2h-3m0 18h3a2 2 0 0 0 2-2v-3M3 16v3a2 2 0 0 0 2 2h3"/>
              </svg>
            </button>
            <button onClick={() => setIsVideoMinimized(false)} title="Restore">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="2">
                <path d="M18 6 6 18M6 6l12 12"/>
              </svg>
            </button>
          </div>
        </div>
      )}


      {/* ---------------- EVENT MODAL ---------------- */}
      {selectedEvent && (
        <div className="modal-overlay" onClick={() => setSelectedEvent(null)}>
          <div className={isDarkTheme ? "modal-content-dark" : "modal-content"} onClick={(e) => e.stopPropagation()}>
            <button className="modal-close" onClick={() => setSelectedEvent(null)}>×</button>
            <h2>Event Details</h2>
            {selectedEvent.image_base64 && <img src={selectedEvent.image_base64} alt="Event" className="modal-image" />}
            <div className="modal-details">
              <p><strong>Event ID:</strong> {selectedEvent.event_id}</p>
              <p><strong>Type:</strong> {selectedEvent.event_type}</p>
              <p><strong>Plate:</strong> {selectedEvent.plate_number || "N/A"}</p>
              {selectedEvent.speed && (
                <p><strong>Speed:</strong> {selectedEvent.speed} km/h</p>
              )}
              <p><strong>Time:</strong> {new Date(selectedEvent.timestamp).toLocaleString()}</p>
              <p><strong>Camera:</strong> {selectedEvent.camera_id || "N/A"}</p>
              <p><strong>Board:</strong> {selectedEvent.board_id || "N/A"}</p>
              {selectedEvent.confidence && (
                <p><strong>Confidence:</strong> {(selectedEvent.confidence * 100).toFixed(1)}%</p>
              )}
            </div>
          </div>
        </div>
      )}


      {/* ---------------- FOOTER ---------------- */}
      <div className={isDarkTheme ? "footer-dark" : "footer-white"}>
        AI-IP Camera Project by VCONNECTECH SYSTEMS
      </div>


      {/* ---------------- FULLSCREEN VIDEO ---------------- */}
      {isVideoFullscreen && streamUrl && (
        <div className="video-fullscreen-overlay" onClick={() => setIsVideoFullscreen(false)}>
          <div className="video-header-fullscreen">
            <VideoHeader />
          </div>
          <img src={streamUrl} alt="Fullscreen Stream" className="video-fullscreen-img" />
          <button className="video-fullscreen-close" onClick={() => setIsVideoFullscreen(false)} />
        </div>
      )}
    </div>
  );
}

export default App;