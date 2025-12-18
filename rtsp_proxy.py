# app/rtsp_proxy.py - ZERO LATENCY RTSP PROXY
"""
Zero-latency RTSP proxy with optimized GStreamer pipeline
Key fixes: Minimal buffering, frame synchronization, avdec_h264 decoder
"""
from flask import Response, Blueprint
import cv2
import time
import socket
from datetime import datetime
import subprocess
import threading
import queue

rtsp_proxy = Blueprint("rtsp_proxy", __name__)

ACTIVE_RTSP_URL = None
BOARD_IP = None
FRAME_QUEUE = queue.Queue(maxsize=1)  # Only keep latest frame
STREAMING_ACTIVE = threading.Event()

def set_active_rtsp(url):
    global ACTIVE_RTSP_URL, BOARD_IP
    ACTIVE_RTSP_URL = url
    if url:
        try:
            parts = url.split('://')[1].split(':')
            BOARD_IP = parts[0]
        except:
            BOARD_IP = "192.168.1.22"
    print(f"[RTSP-PROXY] SET {url}", flush=True)
    STREAMING_ACTIVE.set()

def clear_active_rtsp():
    global ACTIVE_RTSP_URL, BOARD_IP
    ACTIVE_RTSP_URL = None
    BOARD_IP = None
    STREAMING_ACTIVE.clear()
    # Clear frame queue
    while not FRAME_QUEUE.empty():
        try:
            FRAME_QUEUE.get_nowait()
        except queue.Empty:
            break
    print("[RTSP-PROXY] CLEARED", flush=True)

def timestamp_str():
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]

def check_rtsp_port_open(host, port, timeout=1):
    """Fast port check with minimal timeout"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((host, port))
        sock.close()
        return result == 0
    except:
        return False

@rtsp_proxy.route("/stream/<job_id>")
def proxy_stream(job_id):
    if not ACTIVE_RTSP_URL:
        print("[RTSP-PROXY] No active RTSP URL", flush=True)
        return "No RTSP stream active", 404

    print(f"[RTSP-PROXY] Stream request for job: {job_id}", flush=True)
    print(f"[RTSP-PROXY] RTSP URL: {ACTIVE_RTSP_URL}", flush=True)

    def generate():
        """Zero-latency stream generation"""
        rtsp_url = ACTIVE_RTSP_URL
        frame_count = 0
        last_frame_time = time.time()
        target_fps = 30
        frame_interval = 1.0 / target_fps
        
        print(f"[RTSP-PROXY] [{timestamp_str()}] Starting zero-latency stream...", flush=True)
        
        # Zero-latency pipeline with minimal buffering
        gst_pipeline = (
            f"rtspsrc location={rtsp_url} latency=0 ! "
            f"rtph264depay ! h264parse ! avdec_h264 max-threads=1 ! "
            f"videoconvert ! video/x-raw,format=BGR ! "
            f"appsink drop=true max-buffers=1 sync=false"
        )
        
        print(f"[RTSP-PROXY] Pipeline: {gst_pipeline}", flush=True)
        
        cap = cv2.VideoCapture(gst_pipeline, cv2.CAP_GSTREAMER)
        
        if not cap.isOpened():
            error_msg = "Failed to open RTSP stream"
            yield b'--frame\r\nContent-Type: text/plain\r\n\r\n' + error_msg.encode() + b'\r\n'
            return
        
        print(f"[RTSP-PROXY] [{timestamp_str()}] ✓ Stream connected", flush=True)
        
        try:
            while STREAMING_ACTIVE.is_set():
                ret, frame = cap.read()
                
                if not ret or frame is None:
                    continue
                
                current_time = time.time()
                
                # Rate limiting - skip frames if we're going too fast
                if current_time - last_frame_time < frame_interval:
                    continue
                
                last_frame_time = current_time
                frame_count += 1
                
                # Resize to UI dimensions
                frame = cv2.resize(frame, (640, 480))
                
                # Encode with quality optimization
                ret_encode, jpeg = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
                
                if not ret_encode:
                    continue
                
                # Log every 100 frames
                if frame_count % 100 == 0:
                    print(f"[RTSP-PROXY] [{timestamp_str()}] {frame_count} frames streamed", flush=True)
                
                # Yield frame immediately
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + 
                       jpeg.tobytes() + b'\r\n')
                
        except Exception as e:
            print(f"[RTSP-PROXY] [{timestamp_str()}] Stream error: {e}", flush=True)
        finally:
            cap.release()
            print(f"[RTSP-PROXY] [{timestamp_str()}] Stream ended ({frame_count} frames)", flush=True)

    return Response(
        generate(),
        mimetype="multipart/x-mixed-replace; boundary=frame",
        headers={
            'Cache-Control': 'no-cache, no-store, must-revalidate',
            'Pragma': 'no-cache',
            'Expires': '0',
            'Access-Control-Allow-Origin': '*',
            'Connection': 'close'
        }
    )