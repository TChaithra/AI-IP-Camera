# board_server.py - ENHANCED WITH INSTANT SWITCHING AND STABILITY FIXES
import subprocess
import sys
import os
import signal
from flask import Flask, request, jsonify
from multiprocessing import Process
# Add this import at the top with the other imports
from datetime import datetime
import time
import json
import threading
import queue
from pathlib import Path

VIDEO_STREAMING = True

# FIXED: Initialize profiling data with proper structure for UI compatibility
profiling_data = {
    "fps": 0.0,
    "frame_count": 0,
    "inference_ms": 0.0,
    "resolution": "640x480",
    "frame_delay_ms": 0.0,
    "timestamp": "",
    "model_id": "",
    "camera_id": "",
    "board_id": "",
    "streaming": True,
    "model": "",  # ADDED for UI compatibility
    "camera": "",  # ADDED for UI compatibility
    "board": ""  # ADDED for UI compatibility
}

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

try:
    from config import BOARD_CONTROL_PORT, RTSP_PORT, RTSP_MOUNT_POINT, BOARDS
except ImportError:
    print("Error: config.py not found.")
    sys.exit(1)

app = Flask(__name__)

RUNNING_PROCESS = None
CURRENT_BOARD_ID = None
CURRENT_BOARD_CONFIG = None

# FIXED: Add job ID tracking for proper profiling updates
CURRENT_JOB_ID = None


# ------------------------------------------------------------------------------
# BOARD DETECTION
# ------------------------------------------------------------------------------
def detect_board():
    """Detect which board we're running on"""
    global CURRENT_BOARD_ID, CURRENT_BOARD_CONFIG
    cwd = os.getcwd()
    for board_id, config in BOARDS.items():
        if config["base_path"] in cwd:
            CURRENT_BOARD_ID = board_id
            CURRENT_BOARD_CONFIG = config
            print(f"[BOARD] Detected: {config['name']} ({board_id})")
            return
    # Default to imx8
    CURRENT_BOARD_ID = "imx8"
    CURRENT_BOARD_CONFIG = BOARDS["imx8"]
    print(f"[BOARD] Using default: {CURRENT_BOARD_CONFIG['name']}")

detect_board()


# ------------------------------------------------------------------------------
# CAMERA DETECTION
# ------------------------------------------------------------------------------
def is_actual_camera(device_path):
    """Check if device is an actual camera (not metadata device)"""
    try:
        result = subprocess.run(
            ['v4l2-ctl', '--device', device_path, '--all'],
            capture_output=True, text=True, timeout=2
        )
        if result.returncode != 0:
            return False
        output = result.stdout.lower()
        has_video_capture = 'video capture' in output
        is_metadata = 'metadata' in output or device_path.endswith('m2m')
        can_open = 'video capture' in output and 'device caps' in output
        return has_video_capture and not is_metadata and can_open
    except subprocess.TimeoutExpired:
        print(f"[BOARD] Timeout checking {device_path}")
        return False
    except Exception as e:
        print(f"[BOARD] Error checking {device_path}: {e}")
        return False


def scan_cameras():
    """Only detect actual working cameras"""
    cameras = []
    print("[BOARD] Scanning for cameras...", flush=True)
    # Check video0 to video10
    for i in range(11):
        device_path = f"/dev/video{i}"
        if not os.path.exists(device_path):
            continue
        print(f"[BOARD] Checking {device_path}...", flush=True)
        if is_actual_camera(device_path):
            camera_name = f"Camera {i} - {CURRENT_BOARD_CONFIG['name']}"
            cameras.append({
                "id": f"camera_{i}",
                "name": camera_name,
                "path": device_path
            })
            print(f"[BOARD] ✓ Found: {device_path} -> {camera_name}", flush=True)
        else:
            print(f"[BOARD] ✗ Skipped: {device_path} (not a camera or metadata device)", flush=True)
    if len(cameras) == 0:
        print(f"[BOARD] WARNING: No cameras detected!", flush=True)
    else:
        print(f"[BOARD] Total cameras found: {len(cameras)}", flush=True)
    return cameras


# ------------------------------------------------------------------------------
# MODEL DISCOVERY
# ------------------------------------------------------------------------------
def scan_models_directory():
    """Scan models directory for .tflite files"""
    import glob
    models_dir = os.path.join(CURRENT_BOARD_CONFIG['base_path'], 'models')
    if not os.path.exists(models_dir):
        print(f"[WARN] Models directory not found: {models_dir}")
        return []
    tflite_files = glob.glob(os.path.join(models_dir, "*.tflite"))
    models = []
    for filepath in tflite_files:
        filename = os.path.basename(filepath)
        model_name = os.path.splitext(filename)[0]
        script_name = f"{model_name}_stream.py"
        script_path = os.path.join(CURRENT_BOARD_CONFIG['base_path'], 'scripts', script_name)
        if not os.path.exists(script_path):
            alt_script = f"{model_name}.py"
            alt_path = os.path.join(CURRENT_BOARD_CONFIG['base_path'], 'scripts', alt_script)
            if os.path.exists(alt_path):
                script_name = alt_script
                script_path = alt_path
        has_script = os.path.exists(script_path)
        models.append({
            "id": model_name,
            "name": model_name.replace('_', ' ').title(),
            "model_file": filename,
            "script": script_name,
            "has_script": has_script
        })
    print(f"[BOARD] Found {len(models)} models in {models_dir}")
    return models


def get_video_source():
    """Get appropriate video source based on board type"""
    if CURRENT_BOARD_ID == "computational":
        video_file = os.path.join(CURRENT_BOARD_CONFIG['base_path'], 'test_video.mp4')
        if os.path.exists(video_file):
            print(f"[BOARD] Using stored video for computational board: {video_file}")
            return video_file
        else:
            cameras = scan_cameras()
            return cameras[0]["path"] if cameras else "/dev/video0"
    else:
        cameras = scan_cameras()
        return cameras[0]["path"] if cameras else "/dev/video0"


# ------------------------------------------------------------------------------
# INFERENCE SCRIPT EXECUTION
# ------------------------------------------------------------------------------
def run_inference_script(script_path, model_path, camera_path, model_id):
    """Run inference script with environment variables"""
    def signal_handler(sig, frame):
        sys.exit(0)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        print("=" * 70)
        print(f"STARTING INFERENCE JOB")
        print(f" Board: {CURRENT_BOARD_CONFIG['name']}")
        print(f" Script: {script_path}")
        print(f" Model: {model_path}")
        print(f" Camera: {camera_path}")
        print(f" RTSP: rtsp://{CURRENT_BOARD_CONFIG['ip']}:{RTSP_PORT}{RTSP_MOUNT_POINT}")
        print("=" * 70)
        
        if not os.path.exists(script_path):
            print(f"[ERROR] Script not found: {script_path}")
            return
            
        env = os.environ.copy()
        env['NPU_MODEL_PATH'] = model_path
        env['NPU_VIDEO_SOURCE'] = camera_path
        env['NPU_RTSP_PORT'] = str(RTSP_PORT)
        env['NPU_RTSP_MOUNT'] = RTSP_MOUNT_POINT
        env['NPU_MODEL_ID'] = model_id
        env['BOARD_IP'] = CURRENT_BOARD_CONFIG['ip']
        env['BACKEND_URL'] = f"http://192.168.1.56:8000"
        env['NPU_BOARD_ID'] = CURRENT_BOARD_ID
        env['PYTHONUNBUFFERED'] = '1'
        
        cmd = ['python3', '-u', script_path]
        print(f"[CMD] {' '.join(cmd)}")
        
        proc = subprocess.Popen(
            cmd, env=env, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, bufsize=1, universal_newlines=True
        )
        
        for line in iter(proc.stdout.readline, ''):
            if line:
                print(f"[NPU] {line.rstrip()}", flush=True)
        
        proc.wait()
        print(f"[INFO] Script exited with code {proc.returncode}")
        
    except Exception as e:
        print(f"[ERROR] Failed to run script: {e}")
        import traceback
        traceback.print_exc()


def run_inference_script_with_job_id(script_path, model_path, camera_path, model_id, job_id):
    """Run inference script with environment variables including job_id"""
    global CURRENT_JOB_ID, profiling_data
    
    def signal_handler(sig, frame):
        sys.exit(0)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # FIXED: Set current job ID for profiling
    CURRENT_JOB_ID = job_id
    
    # FIXED: Initialize profiling data with job info
    profiling_data.update({
        "model_id": model_id,
        "board_id": CURRENT_BOARD_ID,
        "model": model_id,
        "board": CURRENT_BOARD_ID,
        "camera": camera_path,
        "camera_id": os.path.basename(camera_path).replace('video', 'camera_'),
        "streaming": True,
        "fps": 0.0,  # Initialize with actual values
        "frame_count": 0,
        "inference_ms": 0.0,
        "resolution": "640x480",
        "timestamp": datetime.now().strftime("%H:%M:%S.%f")[:-3]
    })
    
    
    try:
        print("=" * 70)
        print(f"STARTING INFERENCE JOB")
        print(f" Job ID: {job_id}")
        print(f" Board: {CURRENT_BOARD_CONFIG['name']}")
        print(f" Script: {script_path}")
        print(f" Model: {model_path}")
        print(f" Camera: {camera_path}")
        print(f" RTSP: rtsp://{CURRENT_BOARD_CONFIG['ip']}:{RTSP_PORT}{RTSP_MOUNT_POINT}")
        print("=" * 70)
        
        if not os.path.exists(script_path):
            print(f"[ERROR] Script not found: {script_path}")
            return
            
        env = os.environ.copy()
        env['NPU_MODEL_PATH'] = model_path
        env['NPU_VIDEO_SOURCE'] = camera_path
        env['NPU_RTSP_PORT'] = str(RTSP_PORT)
        env['NPU_RTSP_MOUNT'] = RTSP_MOUNT_POINT
        env['NPU_MODEL_ID'] = model_id
        env['BOARD_IP'] = CURRENT_BOARD_CONFIG['ip']
        env['BACKEND_URL'] = f"http://192.168.1.56:8000"
        env['NPU_BOARD_ID'] = CURRENT_BOARD_ID
        env['NPU_JOB_ID'] = job_id
        env['PYTHONUNBUFFERED'] = '1'
        
        cmd = ['python3', '-u', script_path]
        print(f"[CMD] {' '.join(cmd)}")
        print(f"[ENV] NPU_JOB_ID={job_id}")
        
        proc = subprocess.Popen(
            cmd, env=env, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, bufsize=1, universal_newlines=True
        )
        
        for line in iter(proc.stdout.readline, ''):
            if line:
                print(f"[NPU] {line.rstrip()}", flush=True)
        
        proc.wait()
        print(f"[INFO] Script exited with code {proc.returncode}")
        
    except Exception as e:
        print(f"[ERROR] Failed to run script: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # FIXED: Clear job ID when process ends
        CURRENT_JOB_ID = None


# ------------------------------------------------------------------------------
# INSTANT SWITCHING ENDPOINTS
# ------------------------------------------------------------------------------
@app.post("/swap_camera")
def swap_camera():
    """Swap camera without stopping inference"""
    global CURRENT_JOB_ID, profiling_data
    
    data = request.json or {}
    camera_path = data.get("camera_path")
    
    if not camera_path:
        return jsonify({"ok": False, "message": "camera_path required"}), 400
    
    if not os.path.exists(camera_path):
        return jsonify({"ok": False, "message": f"Camera not found: {camera_path}"}), 400
    
    # FIXED: Update profiling data with new camera
    profiling_data["camera"] = camera_path
    profiling_data["camera_id"] = os.path.basename(camera_path).replace('video', 'camera_')
    
    swap_file = "/tmp/swap.json"
    swap = {}
    if os.path.exists(swap_file):
        try:
            with open(swap_file, 'r') as f:
                swap = json.load(f)
        except:
            pass
    
    swap["camera_path"] = camera_path
    
    with open(swap_file, 'w') as f:
        json.dump(swap, f)
    
    print(f"[BOARD] Camera swap initiated: {camera_path}")
    return jsonify({"ok": True, "swap": swap, "message": "Camera swap initiated"})

# In board_server.py, add a POST endpoint for profiling updates:
@app.post("/profiling")
def receive_profiling_update():
    """Receive profiling updates from YOLO stream"""
    global profiling_data
    
    data = request.json
    if not data:
        return jsonify({"ok": False, "message": "No data"}), 400
    
    try:
        # Update the profiling data with received values
        profiling_data.update({
            "fps": float(data.get("fps", 0.0)),
            "frame_count": int(data.get("frame_count", 0)),
            "inference_ms": float(data.get("inference_ms", 0.0)),
            "resolution": data.get("resolution", "640x480"),
            "timestamp": data.get("timestamp", datetime.now().strftime("%H:%M:%S.%f")[:-3]),
            "model_id": data.get("model_id", ""),
            "board_id": data.get("board_id", CURRENT_BOARD_ID),
            "streaming": bool(data.get("streaming", True))
        })
        
        print(f"[BOARD] Received profiling update: FPS={profiling_data['fps']:.1f}, Frames={profiling_data['frame_count']}")
        return jsonify({"ok": True, "message": "Profiling updated"})
        
    except Exception as e:
        print(f"[BOARD] Error updating profiling: {e}")
        return jsonify({"ok": False, "message": str(e)}), 500

@app.post("/swap_model")
def swap_model():
    """Swap model without stopping inference"""
    global CURRENT_JOB_ID, profiling_data
    
    data = request.json or {}
    model_path = data.get("model_path")
    
    if not model_path:
        return jsonify({"ok": False, "message": "model_path required"}), 400
    
    if not os.path.exists(model_path):
        return jsonify({"ok": False, "message": f"Model not found: {model_path}"}), 400
    
    # FIXED: Update profiling data with new model
    model_id = os.path.basename(model_path).replace('.tflite', '')
    profiling_data["model_id"] = model_id
    profiling_data["model"] = model_id
    
    swap_file = "/tmp/swap.json"
    swap = {}
    if os.path.exists(swap_file):
        try:
            with open(swap_file, 'r') as f:
                swap = json.load(f)
        except:
            pass
    
    swap["model_path"] = model_path
    
    with open(swap_file, 'w') as f:
        json.dump(swap, f)
    
    print(f"[BOARD] Model swap initiated: {model_path}")
    return jsonify({"ok": True, "swap": swap, "message": "Model swap initiated"})


# ------------------------------------------------------------------------------
# JOB MANAGEMENT
# ------------------------------------------------------------------------------
@app.post("/start_job")
def start_job():
    global RUNNING_PROCESS, CURRENT_JOB_ID
    
    # Check if job already running
    if RUNNING_PROCESS and RUNNING_PROCESS.is_alive():
        return jsonify({"ok": False, "message": "Job already running"}), 409
    
    data = request.json
    camera_path = data.get("camera_path")
    model_path = data.get("model_path")
    script_path = data.get("script_path")
    model_id = data.get("model_id", "unknown")
    
    import uuid
    job_id = uuid.uuid4().hex[:8]
    
    print(f"\n{'='*70}")
    print("RECEIVED START_JOB REQUEST")
    print(f" job_id: {job_id}")
    print(f" camera_path: {camera_path}")
    print(f" model_path: {model_path}")
    print(f" script_path: {script_path}")
    print(f" model_id: {model_id}")
    print(f"{'='*70}\n")
    
    # Validate paths
    if not script_path or not os.path.exists(script_path):
        return jsonify({
            "ok": False,
            "message": f"Script not found: {script_path}"
        }), 400
    
    if not os.path.exists(camera_path):
        return jsonify({
            "ok": False,
            "message": f"Camera not found: {camera_path}"
        }), 400
    
    # FIXED: Set current job ID
    CURRENT_JOB_ID = job_id
    
    RUNNING_PROCESS = Process(
        target=run_inference_script_with_job_id,
        args=(script_path, model_path, camera_path, model_id, job_id),
        daemon=True
    )
    RUNNING_PROCESS.start()
    
    return jsonify({
        "ok": True,
        "message": f"Started {os.path.basename(script_path)} (PID {RUNNING_PROCESS.pid})",
        "model_id": model_id,
        "script": os.path.basename(script_path),
        "rtsp_url": f"rtsp://{CURRENT_BOARD_CONFIG['ip']}:{RTSP_PORT}{RTSP_MOUNT_POINT}",
        "board_id": CURRENT_BOARD_ID,
        "job_id": job_id
    })


@app.post("/stop_job")
def stop_job():
    global RUNNING_PROCESS, CURRENT_JOB_ID
    
    if RUNNING_PROCESS and RUNNING_PROCESS.is_alive():
        print("[INFO] Terminating inference process...")
        RUNNING_PROCESS.terminate()
        RUNNING_PROCESS.join(timeout=5)
        if RUNNING_PROCESS.is_alive():
            print("[WARN] Force killing process...")
            RUNNING_PROCESS.kill()
            RUNNING_PROCESS.join(timeout=2)
        RUNNING_PROCESS = None
        print("[INFO] Job stopped")
    
    # FIXED: Clear job ID
    CURRENT_JOB_ID = None
    
    # Clean up rogue processes
    try:
        subprocess.run(['pkill', '-f', 'overspeed_stream.py'], capture_output=True)
        subprocess.run(['pkill', '-f', 'raw_video_stream.py'], capture_output=True)
        subprocess.run(['pkill', '-f', 'yolo_stream.py'], capture_output=True)
    except:
        pass
    
    time.sleep(2)
    
    return jsonify({"ok": True, "message": "Stopped"})


# ------------------------------------------------------------------------------
# VIDEO STREAMING CONTROL
# ------------------------------------------------------------------------------
@app.post("/pause_video")
def pause_video():
    """Pause only video streaming, keep inference running"""
    global VIDEO_STREAMING
    
    VIDEO_STREAMING = False
    print("[BOARD] Video streaming paused, inference continues")
    
    # FIXED: Update profiling data
    profiling_data["streaming"] = False
    
    try:
        with open("/tmp/pause_video.flag", "w") as f:
            f.write("paused")
    except:
        pass
    return jsonify({"ok": True, "message": "Video paused"})


@app.post("/resume_video")
def resume_video():
    """Resume video streaming"""
    global VIDEO_STREAMING
    
    VIDEO_STREAMING = True
    print("[BOARD] Video streaming resumed")
    
    # FIXED: Update profiling data
    profiling_data["streaming"] = True
    
    try:
        if os.path.exists("/tmp/pause_video.flag"):
            os.remove("/tmp/pause_video.flag")
    except:
        pass
    return jsonify({"ok": True, "message": "Video resumed"})


# ------------------------------------------------------------------------------
# STATUS & MONITORING
# ------------------------------------------------------------------------------
@app.get("/streaming_status")
def streaming_status():
    """Get current streaming status"""
    return jsonify({
        "ok": True,
        "video_streaming": VIDEO_STREAMING,
        "inference_running": RUNNING_PROCESS is not None and RUNNING_PROCESS.is_alive()
    })


@app.get("/health")
def health():
    running = RUNNING_PROCESS is not None and RUNNING_PROCESS.is_alive()
    return jsonify({
        "ok": True,
        "running": running,
        "pid": RUNNING_PROCESS.pid if running else None,
        "board_id": CURRENT_BOARD_ID,
        "board_name": CURRENT_BOARD_CONFIG['name'],
        "rtsp_url": f"rtsp://{CURRENT_BOARD_CONFIG['ip']}:{RTSP_PORT}{RTSP_MOUNT_POINT}" if running else None
    })


@app.get("/board_info")
def board_info():
    """Get board information with dynamically detected cameras and models"""
    return jsonify({
        "ok": True,
        "board_id": CURRENT_BOARD_ID,
        "board_name": CURRENT_BOARD_CONFIG['name'],
        "board_ip": CURRENT_BOARD_CONFIG['ip'],
        "base_path": CURRENT_BOARD_CONFIG['base_path'],
        "cameras": scan_cameras(),
        "models": scan_models_directory()
    })


@app.get("/models")
def list_models():
    """Endpoint for dynamic model discovery"""
    models = scan_models_directory()
    return jsonify({
        "ok": True,
        "board_id": CURRENT_BOARD_ID,
        "models": models,
        "count": len(models)
    })


@app.get("/cameras")
def list_cameras():
    """Endpoint for dynamic camera discovery"""
    cameras = scan_cameras()
    return jsonify({
        "ok": True,
        "board_id": CURRENT_BOARD_ID,
        "cameras": cameras,
        "count": len(cameras)
    })


# In board_server.py, update the get_profiling function:
@app.get("/profiling")
def get_profiling():
    """Get real-time profiling data - FIXED to return proper format"""
    current_time = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    
    # Ensure all fields have proper data types
    result = {
        "fps": float(profiling_data.get("fps", 0.0)),
        "frame_count": int(profiling_data.get("frame_count", 0)),
        "inference_ms": float(profiling_data.get("inference_ms", 0.0)),
        "resolution": profiling_data.get("resolution", "640x480"),
        "frame_delay_ms": float(profiling_data.get("frame_delay_ms", 0.0)),
        "timestamp": profiling_data.get("timestamp", current_time),
        "model_id": profiling_data.get("model_id", ""),
        "camera_id": profiling_data.get("camera_id", ""),
        "board_id": profiling_data.get("board_id", CURRENT_BOARD_ID),
        "streaming": bool(profiling_data.get("streaming", True)),
        "model": profiling_data.get("model", ""),
        "camera": profiling_data.get("camera", ""),
        "board": profiling_data.get("board", CURRENT_BOARD_ID)
    }
    
    return jsonify(result)


@app.post("/quick_stop")
def quick_stop():
    """Fast stop without waiting"""
    global RUNNING_PROCESS, CURRENT_JOB_ID
    
    if RUNNING_PROCESS and RUNNING_PROCESS.is_alive():
        RUNNING_PROCESS.terminate()
        RUNNING_PROCESS = None
        CURRENT_JOB_ID = None  # FIXED: Clear job ID
    
    return jsonify({"ok": True, "message": "Quick stopped"})


# ------------------------------------------------------------------------------
# MAIN EXECUTION
# ------------------------------------------------------------------------------
if __name__ == "__main__":
    print("=" * 70)
    print("BOARD SERVER - ENHANCED WITH INSTANT SWITCHING")
    print("=" * 70)
    print(f"Board: {CURRENT_BOARD_CONFIG['name']}")
    print(f"Base Path: {CURRENT_BOARD_CONFIG['base_path']}")
    print(f"RTSP Port: {RTSP_PORT}")
    print(f"RTSP Mount: {RTSP_MOUNT_POINT}")
    print(f"Control Port: {BOARD_CONTROL_PORT}")
    print("=" * 70)
    print("\nDetecting Resources...")
    cameras = scan_cameras()
    models = scan_models_directory()
    print(f"\n✓ Cameras: {len(cameras)}")
    for cam in cameras:
        print(f"  - {cam['name']} ({cam['path']})")
    print(f"\n✓ Models: {len(models)}")
    for model in models:
        print(f"  - {model['name']} ({'✓' if model['has_script'] else '✗'} script)")
    print("=" * 70)
    print(f"\nStarting server on 0.0.0.0:{BOARD_CONTROL_PORT}")
    app.run(host="0.0.0.0", port=BOARD_CONTROL_PORT, debug=False)