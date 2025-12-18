# app/main.py - FIXED REAL-TIME PROFILING WITH DYNAMIC UI UPDATES
from flask import Flask, request, jsonify
from flask_cors import CORS
from app.board_connector import BoardConnector
from app.rtsp_proxy import rtsp_proxy, set_active_rtsp, clear_active_rtsp
from app.config import BOARDS, DEFAULT_BOARD, BACKEND_IP, BACKEND_PORT
from app.events_db import init_db, save_event, get_recent_events, get_event_by_id
import uuid
import requests
import time
import threading
import queue
from datetime import datetime

# ------------------------------------------------------------------------------
# GLOBALS
# ------------------------------------------------------------------------------
PROFILING_CACHE = {}
SAVED_FRAMES_QUEUE = queue.Queue(maxsize=100)   # frames with detections

app = Flask(__name__)
CORS(app)
app.register_blueprint(rtsp_proxy)

init_db()  # create events DB

# Connectors for every board
board_connectors = {
    bid: BoardConnector(board_ip=b["ip"], board_port=b["control_port"])
    for bid, b in BOARDS.items()
}

JOBS = {}          # active jobs  {job_id: {...}}
CURRENT_BOARD = None

# Board-info cache
board_info_cache = {}
CACHE_TIMEOUT = 2  # seconds


# ------------------------------------------------------------------------------
# HELPERS
# ------------------------------------------------------------------------------
def fetch_board_info_from_board(board_id):
    """Return cached board info or fetch fresh copy."""
    if board_id in board_info_cache:
        cached_data, ts = board_info_cache[board_id]
        if time.time() - ts < CACHE_TIMEOUT:
            return cached_data

    try:
        board = BOARDS[board_id]
        url = f"http://{board['ip']}:{board['control_port']}/board_info"
        resp = requests.get(url, timeout=3)
        resp.raise_for_status()
        data = resp.json()
        if data.get("ok"):
            board_info_cache[board_id] = (data, time.time())
            return data
    except Exception:
        pass
    return None


# ------------------------------------------------------------------------------
# INSTANT SWITCHING  (camera / model)
# ------------------------------------------------------------------------------
@app.post("/swap_camera")
def swap_camera():
    data = request.json or {}
    board_id = data.get("board_id", CURRENT_BOARD or DEFAULT_BOARD)
    camera_id = data.get("camera_id")

    if not camera_id:
        return jsonify({"ok": False, "message": "camera_id required"}), 400
    if board_id not in BOARDS:
        return jsonify({"ok": False, "message": f"Invalid board_id: {board_id}"}), 400

    board_info = fetch_board_info_from_board(board_id)
    if not board_info:
        return jsonify({"ok": False, "message": f"Cannot connect to board {board_id}"}), 500

    camera_path = None
    for cam in board_info.get("cameras", []):
        if cam["id"] == camera_id:
            camera_path = cam["path"]
            break
    if not camera_path:
        return jsonify({"ok": False, "message": f"Camera {camera_id} not found on board"}), 400

    connector = board_connectors[board_id]
    resp = connector._make_request("POST", "/swap_camera", json={"camera_path": camera_path})
    if resp and resp.get("ok"):
        if JOBS:
            jid = next(iter(JOBS.keys()))
            JOBS[jid]["camera_id"] = camera_id
        return jsonify({"ok": True, "message": f"Camera switched to {camera_id}", "camera_id": camera_id})
    return jsonify({"ok": False, "message": resp.get("message", "Camera swap failed")}), 500


@app.post("/swap_model")
def swap_model():
    data = request.json or {}
    board_id = data.get("board_id", CURRENT_BOARD or DEFAULT_BOARD)
    model_id = data.get("model_id")

    if not model_id:
        return jsonify({"ok": False, "message": "model_id required"}), 400
    if board_id not in BOARDS:
        return jsonify({"ok": False, "message": f"Invalid board_id: {board_id}"}), 400

    board_info = fetch_board_info_from_board(board_id)
    if not board_info:
        return jsonify({"ok": False, "message": f"Cannot connect to board {board_id}"}), 500

    model_path = None
    for m in board_info.get("models", []):
        if m["id"] == model_id:
            if not m.get("has_script"):
                return jsonify({"ok": False, "message": f"No script found for model {model_id}"}), 400
            model_path = f"{BOARDS[board_id]['base_path']}/models/{m['model_file']}"
            break
    if not model_path:
        return jsonify({"ok": False, "message": f"Model {model_id} not found on board"}), 400

    connector = board_connectors[board_id]
    resp = connector._make_request("POST", "/swap_model", json={"model_path": model_path})
    if resp and resp.get("ok"):
        if JOBS:
            jid = next(iter(JOBS.keys()))
            JOBS[jid]["model_id"] = model_id
        return jsonify({"ok": True, "message": f"Model switched to {model_id}", "model_id": model_id})
    return jsonify({"ok": False, "message": resp.get("message", "Model swap failed")}), 500


# ------------------------------------------------------------------------------
# RESOURCE LISTING  (boards / cameras / models)
# ------------------------------------------------------------------------------
@app.get("/boards")
def get_boards():
    out = []
    for bid, data in BOARDS.items():
        try:
            ok = board_connectors[bid].health().get("ok", False)
        except Exception:
            ok = False
        out.append({"id": bid, "name": data["name"], "ip": data["ip"],
                    "base_path": data["base_path"], "online": ok})
    return jsonify(out)


@app.get("/cameras")
def cameras():
    board_id = request.args.get("board_id", DEFAULT_BOARD)
    if board_id not in BOARDS:
        return jsonify({"error": "Invalid board_id"}), 400

    info = fetch_board_info_from_board(board_id)
    if info and info.get("cameras"):
        return jsonify(info["cameras"])

    # fallback to config file
    out = []
    if "cameras" in BOARDS[board_id]:
        for cid, c in BOARDS[board_id]["cameras"].items():
            out.append({"id": cid, "name": c["name"], "path": c["path"]})
    return jsonify(out)


@app.get("/models")
def models():
    board_id = request.args.get("board_id", DEFAULT_BOARD)
    if board_id not in BOARDS:
        return jsonify({"error": "Invalid board_id"}), 400

    info = fetch_board_info_from_board(board_id)
    if info and info.get("models"):
        return jsonify(info["models"])

    # fallback to config file
    out = []
    if "models" in BOARDS[board_id]:
        for mid, m in BOARDS[board_id]["models"].items():
            out.append({"id": mid, "name": m["name"],
                        "script": m["script"], "model_file": m["model_file"]})
    return jsonify(out)


# ------------------------------------------------------------------------------
# PAUSE / RESUME  (smart – keeps inference running)
# ------------------------------------------------------------------------------
@app.post("/pause_video")
def pause_video():
    if not CURRENT_BOARD:
        return jsonify({"ok": False, "message": "No active board"}), 400
    resp = board_connectors[CURRENT_BOARD]._make_request("POST", "/pause_video")
    if resp and resp.get("ok"):
        return jsonify({"ok": True, "message": "Video streaming paused"})
    return jsonify({"ok": False, "message": resp.get("message", "Pause failed")}), 500


@app.post("/resume_video")
def resume_video():
    if not CURRENT_BOARD:
        return jsonify({"ok": False, "message": "No active board"}), 400
    resp = board_connectors[CURRENT_BOARD]._make_request("POST", "/resume_video")
    if resp and resp.get("ok"):
        return jsonify({"ok": True, "message": "Video streaming resumed"})
    return jsonify({"ok": False, "message": resp.get("message", "Resume failed")}), 500


# ------------------------------------------------------------------------------
# JOB LIFECYCLE
# ------------------------------------------------------------------------------
@app.post("/jobs/start")
def jobs_start():
    global CURRENT_BOARD

    data = request.json or {}
    board_id = data.get("board_id", DEFAULT_BOARD)
    camera_id = data.get("camera") or data.get("camera_id")
    model_id = data.get("model") or data.get("model_id")

    if not camera_id or not model_id:
        return jsonify({"ok": False, "message": "Missing camera or model", "received": data}), 400
    if board_id not in BOARDS:
        return jsonify({"ok": False, "message": f"Invalid board_id: {board_id}"}), 400

    board = BOARDS[board_id]
    info = fetch_board_info_from_board(board_id)
    if not info:
        return jsonify({"ok": False, "message": f"Cannot connect to board {board_id}"}), 500

    # resolve camera path
    camera_path = None
    for cam in info.get("cameras", []):
        if cam["id"] == camera_id:
            camera_path = cam["path"]
            break
    if not camera_path:
        return jsonify({"ok": False, "message": f"Camera {camera_id} not found on board"}), 400

    # resolve model + script
    model_path = script_name = None
    for m in info.get("models", []):
        if m["id"] == model_id:
            if not m.get("has_script"):
                return jsonify({"ok": False, "message": f"No script found for model {model_id}"}), 400
            model_path = f"{board['base_path']}/models/{m['model_file']}"
            script_name = m.get("script")
            break
    if not model_path or not script_name:
        return jsonify({"ok": False, "message": f"Model {model_id} not found on board"}), 400
    script_path = f"{board['base_path']}/scripts/{script_name}"

    print(f"[BACKEND] Starting job on {board['name']}: {model_id} on {camera_id}", flush=True)
    print(f"[BACKEND] Paths – Camera: {camera_path}, Model: {model_path}, Script: {script_path}", flush=True)

    connector = board_connectors[board_id]
    resp = connector.start_inference(model_id, model_path, camera_path, script_path)
    if not resp.get("ok"):
        return jsonify(resp), 500

    rtsp_url = resp["rtsp_url"]
    if "0.0.0.0" in rtsp_url:
        rtsp_url = rtsp_url.replace("0.0.0.0", board["ip"])
        print(f"[BACKEND] Corrected RTSP URL: {rtsp_url}", flush=True)

    set_active_rtsp(rtsp_url)

    job_id = resp.get("job_id", uuid.uuid4().hex[:8])  # board may return one
    stream_url = f"http://{BACKEND_IP}:{BACKEND_PORT}/stream/{job_id}"

    JOBS[job_id] = {
        "rtsp_url": rtsp_url,
        "camera_id": camera_id,
        "model_id": model_id,
        "board_id": board_id
    }
    CURRENT_BOARD = board_id

    print(f"[BACKEND] ✓ Job started: {job_id}", flush=True)
    return jsonify({"ok": True, "job_id": job_id, "stream_url": stream_url, "rtsp_url": rtsp_url, "board_id": board_id})


@app.post("/jobs/stop")
def jobs_stop():
    global CURRENT_BOARD, JOBS

    print("[BACKEND] Stopping job", flush=True)
    if CURRENT_BOARD:
        board_connectors[CURRENT_BOARD].stop()

    clear_active_rtsp()
    JOBS.clear()
    CURRENT_BOARD = None
    return jsonify({"ok": True})


# ------------------------------------------------------------------------------
# EVENTS
# ------------------------------------------------------------------------------
@app.post("/events")
def receive_event():
    data = request.json
    if not data:
        return jsonify({"ok": False, "message": "No data"}), 400

    print(f"[BACKEND] Event received: {data.get('event_type')} – {data.get('plate_number')}", flush=True)
    if "board_id" not in data and CURRENT_BOARD:
        data["board_id"] = CURRENT_BOARD

    event_id = save_event(data)
    return jsonify({"ok": True, "event_id": event_id, "message": "Event saved"})


@app.get("/events/recent")
def recent_events():
    limit = request.args.get("limit", 20, type=int)
    return jsonify(get_recent_events(limit))


@app.get("/events/<event_id>")
def get_event(event_id):
    ev = get_event_by_id(event_id)
    return jsonify(ev) if ev else (jsonify({"error": "Event not found"}), 404)


# ------------------------------------------------------------------------------
# HEALTH
# ------------------------------------------------------------------------------
@app.get("/health")
def health():
    board_status = {bid: conn.health().get("ok", False)
                    for bid, conn in board_connectors.items()}
    return jsonify({
        "ok": True,
        "boards": board_status,
        "current_board": CURRENT_BOARD,
        "active_jobs": len(JOBS)
    })


# ------------------------------------------------------------------------------
# REAL-TIME PROFILING  (dynamic updates from board)
# ------------------------------------------------------------------------------
# In main.py, update the get_profiling function:
@app.get("/profiling/<job_id>")
def get_profiling(job_id):
    if job_id not in JOBS:
        return jsonify({"error": "Job not found"}), 404

    try:
        board_id = JOBS[job_id]["board_id"]
        board = BOARDS[board_id]
        url = f"http://{board['ip']}:{board['control_port']}/profiling"
        resp = requests.get(url, timeout=2)
        resp.raise_for_status()
        board_data = resp.json()

        # FIXED: Remove the problematic ok check - board server doesn't return ok field
        result = {
            "job_id": job_id,
            "fps": float(board_data.get("fps", 0)),
            "resolution": board_data.get("resolution", "640x480"),
            "frame_count": int(board_data.get("frame_count", 0)),
            "inference_ms": float(board_data.get("inference_ms", 0)),
            "model": JOBS[job_id]["model_id"],
            "camera": JOBS[job_id]["camera_id"],
            "board": JOBS[job_id]["board_id"],
            "frame_delay_ms": float(board_data.get("frame_delay_ms", 0)),
            "timestamp": board_data.get("timestamp", datetime.now().strftime("%H:%M:%S.%f")[:-3]),
            "streaming": bool(board_data.get("streaming", True))
        }
        
        # FIXED: Always update the cache
        PROFILING_CACHE[job_id] = result
        print(f"[BACKEND] Profiling from board: FPS={result['fps']}, Frames={result['frame_count']}")
        return jsonify(result)

    except Exception as e:
        print(f"[BACKEND] Profiling fetch error: {e}", flush=True)
        # Use cached data if available
        if job_id in PROFILING_CACHE:
            return jsonify(PROFILING_CACHE[job_id])
        
        # Final fallback
        return jsonify({
            "job_id": job_id,
            "fps": 0.0,
            "resolution": "640x480",
            "frame_count": 0,
            "inference_ms": 0.0,
            "model": JOBS[job_id]["model_id"],
            "camera": JOBS[job_id]["camera_id"],
            "board": JOBS[job_id]["board_id"],
            "frame_delay_ms": 0.0,
            "timestamp": datetime.now().strftime("%H:%M:%S.%f")[:-3],
            "streaming": True
        })


# In main.py, update the update_profiling_data function:
@app.post("/profiling/<job_id>")
def update_profiling_data(job_id):
    """Receive profiling data from board - FIXED"""
    if job_id not in JOBS:
        return jsonify({"error": "Job not found"}), 404
    
    data = request.json
    result = {
        "job_id": job_id,
        "fps": float(data.get("fps", 0)),
        "resolution": data.get("resolution", "640x480"),
        "frame_count": int(data.get("frame_count", 0)),
        "inference_ms": float(data.get("inference_ms", 0)),
        "model": JOBS[job_id]["model_id"],
        "camera": JOBS[job_id]["camera_id"],
        "board": JOBS[job_id]["board_id"],
        "frame_delay_ms": float(data.get("frame_delay_ms", 0)),
        "timestamp": data.get("timestamp", datetime.now().strftime("%H:%M:%S.%f")[:-3]),
        "streaming": bool(data.get("streaming", True))
    }
    PROFILING_CACHE[job_id] = result
    print(f"[BACKEND] Received profiling update: FPS={result['fps']}, Frames={result['frame_count']}, Inference={result['inference_ms']}ms")
    return jsonify({"ok": True})


# ------------------------------------------------------------------------------
# SAVED FRAMES  (from board → UI gallery)
# ------------------------------------------------------------------------------
@app.post("/saved_frames")
def receive_saved_frame():
    data = request.json
    if not data or "image_base64" not in data:
        return jsonify({"ok": False, "message": "No image data"}), 400

    try:
        frame_data = {
            "frame_id": data.get("frame_id", f"frame_{int(time.time()*1000)}"),
            "image_base64": data["image_base64"],
            "timestamp": data.get("timestamp", datetime.now().isoformat()),
            "detections": data.get("detections", 0),
            "model_id": data.get("model_id", "unknown"),
            "board_id": data.get("board_id", CURRENT_BOARD)
        }
        SAVED_FRAMES_QUEUE.put(frame_data)
        print(f"[BACKEND] Saved frame received: {frame_data['frame_id']} with {frame_data['detections']} detections")

        # keep last 50
        while SAVED_FRAMES_QUEUE.qsize() > 50:
            try:
                SAVED_FRAMES_QUEUE.get_nowait()
            except queue.Empty:
                break
        return jsonify({"ok": True, "message": "Frame saved"})
    except Exception as e:
        print(f"[BACKEND] Error saving frame: {e}")
        return jsonify({"ok": False, "message": f"Error saving frame: {e}"}), 500


@app.get("/saved_frames")
def get_saved_frames():
    """Return saved frames for UI gallery"""
    frames = []
    temp = queue.Queue()
    while not SAVED_FRAMES_QUEUE.empty():
        try:
            f = SAVED_FRAMES_QUEUE.get_nowait()
            frames.append(f)
            temp.put(f)
        except queue.Empty:
            break
    while not temp.empty():
        try:
            SAVED_FRAMES_QUEUE.put(temp.get_nowait())
        except queue.Full:
            break
    print(f"[BACKEND] Returning {len(frames)} saved frames to UI")
    return jsonify(frames)


# ------------------------------------------------------------------------------
# RUN
# ------------------------------------------------------------------------------
if __name__ == "__main__":
    print(f"Backend running on http://0.0.0.0:{BACKEND_PORT}", flush=True)
    print(f"Backend IP: {BACKEND_IP}", flush=True)
    print(f"Available boards: {list(BOARDS.keys())}", flush=True)
    print("\n[BACKEND] Using INSTANT SWITCHING with REAL-TIME PROFILING", flush=True)
    app.run(host="0.0.0.0", port=BACKEND_PORT, debug=False, threaded=True)