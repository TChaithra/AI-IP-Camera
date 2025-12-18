// src/api.ts - ENHANCED WITH REAL-TIME PROFILING

export const BACKEND = "http://192.168.1.56:8000";

/* ===================================================================
   INTERFACES
   =================================================================== */

export interface Board {
  id: string;
  name: string;
  ip: string;
  base_path?: string;
}

export interface CameraItem {
  id: string;
  name: string;
  path: string;
}

export interface ModelItem {
  id: string;
  name: string;
  path?: string;
  script?: string;
  model_file?: string;
}

export interface Event {
  event_id: string;
  event_type: string;
  timestamp: string;
  plate_number?: string;
  speed?: number;
  confidence?: number;
  camera_id?: string;
  board_id?: string;
  image_base64?: string;
  image_path?: string;
  created_at?: string;
  metadata?: any;
}

export interface ProfilingData {
  job_id: string;
  fps: number;
  resolution: string;
  frame_count: number;
  inference_ms: number;
  model: string;
  camera: string;
  board: string;
  frame_delay_ms: number;
  timestamp: string;
  streaming: boolean;
}

/* ===================================================================
   API FUNCTIONS
   =================================================================== */

/* -----------------------------------------------------------
   Board Management
   ----------------------------------------------------------- */
export async function getBoards(): Promise<Board[]> {
  const r = await fetch(`${BACKEND}/boards`);
  if (!r.ok) throw new Error("Failed to fetch boards");
  return r.json();
}

/* -----------------------------------------------------------
   Camera Management
   ----------------------------------------------------------- */
export async function getCameras(boardId: string): Promise<CameraItem[]> {
  const r = await fetch(`${BACKEND}/cameras?board_id=${boardId}`);
  if (!r.ok) throw new Error("Failed to fetch cameras");
  return r.json();
}

/* -----------------------------------------------------------
   Model Management
   ----------------------------------------------------------- */
export async function getModels(boardId: string): Promise<ModelItem[]> {
  const r = await fetch(`${BACKEND}/models?board_id=${boardId}`);
  if (!r.ok) throw new Error("Failed to fetch models");
  return r.json();
}

/* -----------------------------------------------------------
   Job Control
   ----------------------------------------------------------- */
export async function startJob(boardId: string, cameraId: string, modelId: string) {
  console.log("[API] Starting job with:", { board: boardId, camera: cameraId, model: modelId });

  const r = await fetch(`${BACKEND}/jobs/start`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      board_id: boardId,
      camera: cameraId,
      model: modelId
    })
  });

  if (!r.ok) {
    const errorBody = await r.json();
    throw new Error(`Failed to start job: ${errorBody.message || r.statusText}`);
  }

  return r.json();
}

export async function stopJob(jobId: string) {
  console.log("[API] Stopping job:", jobId);

  const r = await fetch(`${BACKEND}/jobs/stop`, {
    method: "POST"
  });

  if (!r.ok) {
    const errorBody = await r.json();
    throw new Error(`Failed to stop job: ${errorBody.message || r.statusText}`);
  }

  return r.json();
}

/* -----------------------------------------------------------
   Video Control
   ----------------------------------------------------------- */
export async function pauseVideo(boardId: string) {
  const r = await fetch(`${BACKEND}/pause_video`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ board_id: boardId })
  });

  if (!r.ok) {
    const errorBody = await r.json();
    throw new Error(`Failed to pause video: ${errorBody.message || r.statusText}`);
  }

  return r.json();
}

export async function resumeVideo(boardId: string) {
  const r = await fetch(`${BACKEND}/resume_video`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ board_id: boardId })
  });

  if (!r.ok) {
    const errorBody = await r.json();
    throw new Error(`Failed to resume video: ${errorBody.message || r.statusText}`);
  }

  return r.json();
}

/* -----------------------------------------------------------
   Event Management
   ----------------------------------------------------------- */
export async function getRecentEvents(limit: number = 20): Promise<Event[]> {
  const r = await fetch(`${BACKEND}/events/recent?limit=${limit}`);
  if (!r.ok) throw new Error("Failed to fetch events");
  return r.json();
}

export async function getEventById(eventId: string): Promise<Event> {
  const r = await fetch(`${BACKEND}/events/${eventId}`);
  if (!r.ok) throw new Error("Failed to fetch event");
  return r.json();
}

/* -----------------------------------------------------------
   Real-time Profiling (PERFORMANCE METRICS)
   ----------------------------------------------------------- */
export async function getProfiling(jobId: string): Promise<ProfilingData> {
  const r = await fetch(`${BACKEND}/profiling/${jobId}`);
  if (!r.ok) throw new Error("Failed to fetch profiling data");
  return r.json();
}

/* -----------------------------------------------------------
   System Health
   ----------------------------------------------------------- */
export async function getHealth() {
  const r = await fetch(`${BACKEND}/health`);
  if (!r.ok) throw new Error("Health check failed");
  return r.json();
}