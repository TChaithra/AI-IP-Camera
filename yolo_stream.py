#!/usr/bin/env python3
"""
yolo_fixed_stream.py - RTSP streaming with YOLO detection and FIXED real-time profiling
Fixes detection count and performance metrics updates with dynamic UI updates
"""

import os
import sys
import time
import cv2
import numpy as np
import threading
import requests
import json
import base64
from datetime import datetime
import queue
import gi
import gc

# Force unbuffered output
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

print("[STARTUP] YOLO RTSP Streaming with Fixed Metrics", flush=True)

# ------------------------------------------------------------------------------
# GSTREAMER & TFLITE IMPORTS
# ------------------------------------------------------------------------------
# GStreamer imports
try:
    gi.require_version('Gst', '1.0')
    gi.require_version('GstRtspServer', '1.0')
    from gi.repository import Gst, GstRtspServer, GLib
    Gst.init(None)
    print("[STARTUP] GStreamer loaded", flush=True)
except Exception as e:
    print(f"[ERROR] GStreamer: {e}", flush=True)
    sys.exit(1)

# TFLite
try:
    import tflite_runtime.interpreter as tflite
    print("[STARTUP] TFLite loaded", flush=True)
except Exception as e:
    print(f"[ERROR] TFLite: {e}", flush=True)
    sys.exit(1)


# ------------------------------------------------------------------------------
# CONFIGURATION
# ------------------------------------------------------------------------------
MODEL_PATH = os.getenv('NPU_MODEL_PATH', "/root/chaitra/imx/models/yolo.tflite")
VIDEO_SOURCE = os.getenv('NPU_VIDEO_SOURCE', "/dev/video3")
RTSP_PORT = int(os.getenv('NPU_RTSP_PORT', '8554'))
RTSP_MOUNT = os.getenv('NPU_RTSP_MOUNT', '/chaithu')
BOARD_IP = os.getenv('BOARD_IP', '192.168.1.22')
BACKEND_URL = os.getenv('BACKEND_URL', 'http://192.168.1.56:8000').rstrip()
MODEL_ID = os.getenv('NPU_MODEL_ID', 'yolo')
BOARD_ID = os.getenv('NPU_BOARD_ID', 'imx8')

# FIXED: Get the actual job ID from environment
JOB_ID = os.getenv('NPU_JOB_ID', 'current_job')

OUTPUT_WIDTH = 640
OUTPUT_HEIGHT = 480
OUTPUT_FPS = 30
INPUT_SIZE = 320
CONF_THRESH = 0.5
IOU_THRESH = 0.45

# 80 COCO classes
CLASS_NAMES = [
    'person','bicycle','car','motorcycle','airplane','bus','train','truck','boat',
    'traffic light','fire hydrant','stop sign','parking meter','bench','bird','cat',
    'dog','horse','sheep','cow','elephant','bear','zebra','giraffe','backpack',
    'umbrella','handbag','tie','suitcase','frisbee','skis','snowboard','sports ball',
    'kite','baseball bat','baseball glove','skateboard','surfboard','tennis racket',
    'bottle','wine glass','cup','fork','knife','spoon','bowl','banana','apple',
    'sandwich','orange','broccoli','carrot','hot dog','pizza','donut','cake','chair',
    'couch','potted plant','bed','dining table','toilet','tv','laptop','mouse',
    'remote','keyboard','cell phone','microwave','oven','toaster','sink','refrigerator',
    'book','clock','vase','scissors','teddy bear','hair drier','toothbrush'
]

VIDEO_STREAMING = True
STREAMING_LOCK = threading.Lock()


# ------------------------------------------------------------------------------
# PROFILING DATA - FIXED TO MATCH UI EXPECTATIONS AND UPDATE DYNAMICALLY
# ------------------------------------------------------------------------------
profiling_data = {
    "fps": 0.0,
    "frame_count": 0,
    "inference_ms": 0.0,
    "resolution": f"{OUTPUT_WIDTH}x{OUTPUT_HEIGHT}",
    "timestamp": "",
    "model_id": MODEL_ID,
    "camera_id": "",
    "board_id": BOARD_ID,
    "streaming": True,
    "model": MODEL_ID,  # ADDED for UI compatibility
    "camera": "",  # ADDED for UI compatibility
    "board": BOARD_ID  # ADDED for UI compatibility
}

# Frame processing metrics - FIXED FOR ACCURATE TRACKING
frame_metrics = {
    "count": 0,
    "start_time": time.time(),
    "inference_times": [],
    "current_fps": 0.0,
    "last_frame_time": time.time(),
    "total_frames": 0  # ADDED for proper frame counting
}

# Detection state
detection_state = {
    "last_detection_frame": 0,
    "detection_count": 0,
    "saved_frames_dir": "/tmp/saved_frames",
    "frame_save_interval": 30  # Save every 30 frames with detections
}


# ------------------------------------------------------------------------------
# ENHANCED RTSP SERVER
# ------------------------------------------------------------------------------
class EnhancedRtspServer:
    """Enhanced RTSP server with stability fixes and instant switching"""
    
    def __init__(self, width, height, fps, mount="/chaithu", port=8554):
        self.width = int(width)
        self.height = int(height)
        self.fps = int(fps)
        self.mount = mount
        self.port = int(port)
        
        self.server = None
        self.factory = None
        self.appsrc = None
        self.main_loop = None
        self.thread = None
        self.media_ready = threading.Event()
        self.client_connected = threading.Event()
        self.stop_streaming = threading.Event()
        
        # Frame delivery system
        self.frame_queue = queue.Queue(maxsize=3)
        self.delivery_thread = None
        self.pts_base = None
        self.frame_count = 0
        self.client_count = 0
        
        # Create saved frames directory
        import pathlib
        pathlib.Path(detection_state["saved_frames_dir"]).mkdir(parents=True, exist_ok=True)
        
        self._setup_server()
    
    def _on_client_connected(self, server, client):
        """Handle client connections"""
        self.client_count += 1
        self.client_connected.set()
        print(f"\n{'='*60}", flush=True)
        print(f"[RTSP] ✓✓✓ CLIENT CONNECTED! (total: {self.client_count})", flush=True)
        print(f"{'='*60}\n", flush=True)
    
    def _on_client_disconnected(self, server, client):
        """Handle client disconnections"""
        self.client_count -= 1
        if self.client_count <= 0:
            self.client_count = 0
            self.client_connected.clear()
            print(f"[RTSP] Client disconnected (remaining: {self.client_count})", flush=True)
    
    def _on_media_configure(self, factory, media):
        """Configure media pipeline when client connects"""
        try:
            element = media.get_element()
            appsrc = element.get_child_by_name("appsrc")
            self.appsrc = appsrc
            
            if appsrc:
                caps_str = f"video/x-raw,format=BGR,width={self.width},height={self.height},framerate={self.fps}/1"
                caps = Gst.Caps.from_string(caps_str)
                appsrc.set_property("caps", caps)
                appsrc.set_property("format", Gst.Format.TIME)
                appsrc.set_property("is-live", True)
                appsrc.set_property("do-timestamp", True)
                appsrc.set_property("block", False)
                appsrc.set_property("max-buffers", 3)
                print("[RTSP] ✓ appsrc configured", flush=True)
                self.media_ready.set()
        except Exception as e:
            print(f"[RTSP] Media configure error: {e}", flush=True)
    
    def _setup_server(self):
        """Setup RTSP server with stability improvements"""
        print(f"[RTSP] Setting up server: 0.0.0.0:{self.port}{self.mount}", flush=True)
        
        # Optimized pipeline for stability
        gst_launch = (
            f"( appsrc name=appsrc is-live=true format=3 "
            f"caps=video/x-raw,format=BGR,width={self.width},height={self.height},framerate={self.fps}/1 ! "
            f"videoconvert ! video/x-raw,format=I420 ! queue max-size-buffers=2 ! "
            f"x264enc tune=zerolatency bitrate=2000 key-int-max={self.fps*2} speed-preset=ultrafast ! "
            f"h264parse ! rtph264pay name=pay0 pt=96 config-interval=1 )"
        )
        
        self.server = GstRtspServer.RTSPServer()
        self.server.set_service(str(self.port))
        self.server.set_address("0.0.0.0")
        self.server.connect("client-connected", self._on_client_connected)
        
        self.factory = GstRtspServer.RTSPMediaFactory()
        self.factory.set_shared(True)
        self.factory.set_launch(gst_launch)
        self.factory.connect("media-configure", self._on_media_configure)
        
        mounts = self.server.get_mount_points()
        mounts.add_factory(self.mount, self.factory)
        
        self.main_loop = GLib.MainLoop()
        print("[RTSP] ✓ Server configured", flush=True)
    
    def start(self):
        """Start RTSP server with stability fixes"""
        if self.thread and self.thread.is_alive():
            return True
            
        def _run():
            try:
                # Add delay to prevent port conflicts
                time.sleep(1)
                server_id = self.server.attach(None)
                
                if server_id == 0:
                    print("[RTSP] ✗ Failed to attach server!", flush=True)
                    return
                
                print(f"[RTSP] ✓✓✓ Server STARTED id={server_id}")
                print(f"[RTSP] URL: rtsp://{BOARD_IP}:{self.port}{self.mount}", flush=True)
                print("[RTSP] Waiting for clients to connect...", flush=True)
                
                self.main_loop.run()
            except Exception as e:
                print(f"[RTSP] Server loop error: {e}", flush=True)
        
        self.thread = threading.Thread(target=_run, daemon=True)
        self.thread.start()
        
        # Start frame delivery thread
        self.delivery_thread = threading.Thread(target=self._delivery_loop, daemon=True)
        self.delivery_thread.start()
        
        # Wait for server to be ready
        time.sleep(2)
        return True
    
    def _delivery_loop(self):
        """Smart frame delivery with client awareness and stability fixes"""
        print("[RTSP] Starting smart frame delivery loop", flush=True)
        
        while not self.stop_streaming.is_set():
            try:
                # Get frame with short timeout
                frame = self.frame_queue.get(timeout=0.1)
                
                # Only deliver if we have clients AND appsrc is ready
                if not self.client_connected.is_set():
                    continue
                
                if self.appsrc is None:
                    continue
                
                with STREAMING_LOCK:
                    if not VIDEO_STREAMING:
                        continue
                
                # Create buffer
                data = frame.tobytes()
                buf = Gst.Buffer.new_allocate(None, len(data), None)
                
                # Fill buffer safely
                success, mapinfo = buf.map(Gst.MapFlags.WRITE)
                if success:
                    buf.fill(0, data)
                    buf.unmap(mapinfo)
                
                # Set timestamp
                if self.pts_base is None:
                    self.pts_base = time.time() * 1e9
                
                buf.pts = int(time.time() * 1e9 - self.pts_base)
                buf.duration = int(1e9 / self.fps)
                
                # Push to RTSP with error checking
                if self.appsrc:
                    result = self.appsrc.emit("push-buffer", buf)
                    if result == Gst.FlowReturn.OK:
                        self.frame_count += 1
                        if self.frame_count % 100 == 0:
                            print(f"[RTSP] Delivered {self.frame_count} frames to clients", flush=True)
                    else:
                        if result == Gst.FlowReturn.FLUSHING:
                            print("[RTSP] Pipeline flushing - waiting for clients to reconnect", flush=True)
                            self.client_connected.clear()
                
            except queue.Empty:
                continue
            except Exception as e:
                print(f"[RTSP] Delivery error: {e}", flush=True)
    
    def push_frame(self, frame):
        """Push frame with client awareness and stability checks"""
        try:
            # Check if we should queue this frame
            should_queue = (
                self.client_connected.is_set() or 
                self.frame_queue.qsize() < 2  # Keep small buffer
            )
            
            if should_queue:
                try:
                    # Non-blocking put with overflow handling
                    self.frame_queue.put(frame, block=False)
                    return True
                except queue.Full:
                    # Remove oldest frame and try again
                    try:
                        self.frame_queue.get_nowait()
                        self.frame_queue.put(frame, block=False)
                        return True
                    except:
                        return False
            
            return False
                    
        except Exception as e:
            print(f"[RTSP] Push frame error: {e}", flush=True)
            return False
    
    def stop(self):
        """Stop streaming with proper cleanup"""
        print("[RTSP] Stopping server...", flush=True)
        
        # Signal threads to stop
        self.stop_streaming.set()
        
        # Clear pending frames
        while not self.frame_queue.empty():
            try:
                self.frame_queue.get_nowait()
            except:
                break
        
        # Stop main loop
        try:
            if self.main_loop and self.main_loop.is_running():
                self.main_loop.quit()
        except Exception as e:
            print(f"[RTSP] Error stopping main loop: {e}", flush=True)
        
        # Wait for threads
        if self.delivery_thread and self.delivery_thread.is_alive():
            self.delivery_thread.join(timeout=2.0)
        
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=2.0)
        
        # Cleanup resources
        try:
            if self.server:
                self.server.remove_factory(self.factory)
                self.server = None
                self.factory = None
                self.appsrc = None
        except Exception as e:
            print(f"[RTSP] Cleanup error: {e}", flush=True)
        
        print("[RTSP] ✓ Server stopped", flush=True)


# ------------------------------------------------------------------------------
# HELPER FUNCTIONS
# ------------------------------------------------------------------------------
def check_streaming_status():
    """Check if video should be streamed"""
    try:
        return not os.path.exists("/tmp/pause_video.flag") and VIDEO_STREAMING
    except:
        return VIDEO_STREAMING


def check_for_swaps():
    """Check for camera/model swap requests"""
    swap_file = "/tmp/swap.json"
    if os.path.exists(swap_file):
        try:
            with open(swap_file, 'r') as f:
                swap_data = json.load(f)
            
            # Process swap requests
            if "camera_path" in swap_data:
                print(f"[SWAP] Camera swap requested: {swap_data['camera_path']}")
                # Handle camera swap logic here
            
            if "model_path" in swap_data:
                print(f"[SWAP] Model swap requested: {swap_data['model_path']}")
                # Handle model swap logic here
            
            # Clear swap file after processing
            os.remove(swap_file)
            return swap_data
        except Exception as e:
            print(f"[SWAP] Error processing swap: {e}")
    return None


# In yolo_stream.py, update the send_profiling_update function:
def send_profiling_update():
    """Send profiling data to backend - FIXED TO SEND ACTUAL VALUES"""
    try:
        # Get actual current values
        current_fps = frame_metrics.get("current_fps", 0.0)
        current_inference = np.mean(frame_metrics["inference_times"]) if frame_metrics["inference_times"] else 0.0
        total_frames = frame_metrics.get("total_frames", 0)
        
        profiling_payload = {
            "fps": float(current_fps),
            "frame_count": int(total_frames),
            "inference_ms": float(current_inference),
            "resolution": f"{OUTPUT_WIDTH}x{OUTPUT_HEIGHT}",
            "timestamp": datetime.now().isoformat(),
            "streaming": check_streaming_status(),
            "model_id": MODEL_ID,
            "board_id": BOARD_ID,
            "frame_delay_ms": 0.0  # Add this field
        }
        
        print(f"[PROFILING] Sending update: FPS={current_fps:.1f}, Frames={total_frames}, Inference={current_inference:.1f}ms")
        
        # FIXED: Use the actual job ID from environment
        job_id = JOB_ID
        response = requests.post(f"{BACKEND_URL}/profiling/{job_id}", json=profiling_payload, timeout=1)
        print(f"[PROFILING] Update sent: {response.status_code}")
        
    except Exception as e:
        print(f"[PROFILING] Failed to send update: {e}", flush=True)


def save_frame_with_detections(frame, detection_count, boxes, scores, classes):
    """Save frame with detections to board and send to backend - FIXED"""
    try:
        if detection_count > 0 and frame_metrics["count"] % detection_state["frame_save_interval"] == 0:
            # Save to local file
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            frame_id = f"{MODEL_ID}_{BOARD_ID}_{timestamp}_{frame_metrics['total_frames']}"
            
            # Encode frame
            _, jpeg = cv2.imencode('.jpg', frame)
            
            # Save locally
            frame_path = os.path.join(detection_state["saved_frames_dir"], f"{frame_id}.jpg")
            with open(frame_path, 'wb') as f:
                f.write(jpeg.tobytes())
            
            print(f"[SAVED] Frame saved locally: {frame_path}")
            
            # Send to backend
            frame_data = {
                "frame_id": frame_id,
                "image_base64": "data:image/jpeg;base64," + base64.b64encode(jpeg).decode(),
                "timestamp": datetime.now().isoformat(),
                "detections": detection_count,
                "model_id": MODEL_ID,
                "board_id": BOARD_ID
            }
            
            response = requests.post(f"{BACKEND_URL}/saved_frames", json=frame_data, timeout=2)
            print(f"[SAVED] Frame sent to backend: {response.status_code}")
            
    except Exception as e:
        print(f"[SAVED] Error saving frame: {e}")


def dequantize(tensor, det_info):
    """Dequantize tensor data"""
    q = det_info.get('quantization', (0.0, 0))
    scale, zero_point = q
    if scale and scale != 0:
        return (tensor.astype(np.float32) - zero_point) * scale
    return tensor.astype(np.float32)


def postprocess_yolo(output_tensor, img_w, img_h):
    """Post-process YOLO output to get bounding boxes"""
    out = dequantize(output_tensor, output_details[0])[0]  # (84,2100) → (2100,84)
    pred = out.transpose(1, 0)
    boxes, scores, classes = [], [], []
    
    for det in pred:
        x, y, w, h = det[:4]
        cls_scores = det[4:]
        cls_id = int(np.argmax(cls_scores))
        conf = float(cls_scores[cls_id])
        
        if conf < CONF_THRESH: 
            continue
            
        # Convert to pixel coordinates
        x1 = int((x - w/2) * img_w)
        y1 = int((y - h/2) * img_h)
        x2 = int((x + w/2) * img_w)
        y2 = int((y + h/2) * img_h)
        
        # Clamp to image bounds
        x1 = max(0, min(x1, img_w - 1))
        y1 = max(0, min(y1, img_h - 1))
        x2 = max(0, min(x2, img_w - 1))
        y2 = max(0, min(y2, img_h - 1))
        
        # Skip small boxes
        if (x2 - x1) < 4 or (y2 - y1) < 4: 
            continue
            
        boxes.append([x1, y1, x2, y2])
        scores.append(conf)
        classes.append(cls_id)
    
    # Apply NMS
    if len(boxes) == 0: 
        return [], [], []
        
    idxs = cv2.dnn.NMSBoxes(boxes, scores, CONF_THRESH, IOU_THRESH)
    final_b, final_s, final_c = [], [], []
    
    if len(idxs) > 0:
        for i in idxs.flatten():
            final_b.append(boxes[i])
            final_s.append(scores[i])
            final_c.append(classes[i])
    
    return final_b, final_s, final_c


def update_profiling(fps, inference_time_ms=0):
    """Update real-time profiling data - FIXED"""
    global profiling_data, frame_metrics
    
    frame_metrics["count"] += 1
    frame_metrics["total_frames"] += 1  # ADDED for proper frame counting
    frame_metrics["inference_times"].append(inference_time_ms)
    
    # Keep only last 30 inference times
    if len(frame_metrics["inference_times"]) > 30:
        frame_metrics["inference_times"].pop(0)
    
    # Calculate FPS every second
    current_time = time.time()
    elapsed = current_time - frame_metrics["start_time"]
    
    if elapsed >= 1.0:
        frame_metrics["current_fps"] = frame_metrics["count"] / elapsed
        frame_metrics["start_time"] = current_time
        frame_metrics["count"] = 0
    
    # Update profiling data
    profiling_data["fps"] = float(frame_metrics["current_fps"])
    profiling_data["frame_count"] = frame_metrics["total_frames"]  # FIXED: Use total_frames
    profiling_data["inference_ms"] = float(inference_time_ms)
    profiling_data["resolution"] = f"{OUTPUT_WIDTH}x{OUTPUT_HEIGHT}"
    profiling_data["timestamp"] = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    profiling_data["model_id"] = MODEL_ID
    profiling_data["model"] = MODEL_ID  # ADDED for UI compatibility
    profiling_data["streaming"] = check_streaming_status()





# In yolo_stream.py, add more detailed logging:
# In yolo_stream.py, change the send_profiling_update function:
def send_profiling_update():
    """Send profiling data to board server instead of backend"""
    try:
        current_fps = frame_metrics.get("current_fps", 0.0)
        current_inference = np.mean(frame_metrics["inference_times"]) if frame_metrics["inference_times"] else 0.0
        total_frames = frame_metrics.get("total_frames", 0)
        
        profiling_payload = {
            "fps": float(current_fps),
            "frame_count": int(total_frames),
            "inference_ms": float(current_inference),
            "resolution": f"{OUTPUT_WIDTH}x{OUTPUT_HEIGHT}",
            "timestamp": datetime.now().isoformat(),
            "streaming": check_streaming_status(),
            "model_id": MODEL_ID,
            "board_id": BOARD_ID,
            "frame_delay_ms": 0.0
        }
        
        print(f"[PROFILING-DEBUG] Sending to board server: FPS={current_fps:.1f}, Frames={total_frames}")
        
        # Send to board server's profiling endpoint
        board_server_url = f"http://{BOARD_IP}:9000/profiling"  # Board server port
        response = requests.post(board_server_url, json=profiling_payload, timeout=1)
        print(f"[PROFILING-DEBUG] Board server response: {response.status_code}")
        
    except Exception as e:
        print(f"[PROFILING-DEBUG] Failed to send to board server: {e}", flush=True)


# ------------------------------------------------------------------------------
# MAIN INFERENCE LOOP
# ------------------------------------------------------------------------------
def inference_loop():
    """Main inference loop with YOLO detection and FIXED real-time profiling"""
    global interpreter, input_details, output_details, frame_metrics
    
    print(f"[INFERENCE] Opening camera: {VIDEO_SOURCE}", flush=True)
    
    # Open camera with optimized settings
    if VIDEO_SOURCE.startswith('/dev/video'):
        # Live camera
        pipeline = (
            f"v4l2src device={VIDEO_SOURCE} ! "
            f"video/x-raw,width={OUTPUT_WIDTH},height={OUTPUT_HEIGHT},framerate={OUTPUT_FPS}/1 ! "
            f"videoconvert ! video/x-raw,format=BGR ! appsink drop=true max-buffers=1 sync=false"
        )
        cap = cv2.VideoCapture(pipeline, cv2.CAP_GSTREAMER)
    elif VIDEO_SOURCE.endswith(('.mp4', '.avi', '.mov')):
        # Video file (for computational board)
        pipeline = (
            f"filesrc location={VIDEO_SOURCE} ! "
            f"decodebin ! videoconvert ! video/x-raw,format=BGR ! "
            f"videoscale ! video/x-raw,width={OUTPUT_WIDTH},height={OUTPUT_HEIGHT} ! "
            f"appsink drop=true max-buffers=1 sync=false"
        )
        cap = cv2.VideoCapture(pipeline, cv2.CAP_GSTREAMER)
    else:
        # Fallback to standard capture
        cap = cv2.VideoCapture(VIDEO_SOURCE)
    
    if not cap.isOpened():
        print(f"[ERROR] Failed to open: {VIDEO_SOURCE}", flush=True)
        return
    
    print("[INFERENCE] ✓ Camera ready", flush=True)
    
    # Load YOLO model
    print(f"[INFERENCE] Loading YOLO model: {MODEL_PATH}", flush=True)
    try:
        interpreter = tflite.Interpreter(
            model_path=MODEL_PATH,
            experimental_delegates=[tflite.load_delegate('libvx_delegate.so')]
        )
        interpreter.allocate_tensors()
        
        input_details = interpreter.get_input_details()
        output_details = interpreter.get_output_details()
        
        model_height = input_details[0]['shape'][1]
        model_width = input_details[0]['shape'][2]
        print(f"[INFERENCE] ✓ YOLO model loaded - Input: {model_width}x{model_height}", flush=True)
        
    except Exception as e:
        print(f"[ERROR] YOLO model loading failed: {e}", flush=True)
        cap.release()
        return
    
    frame_count = 0
    last_frame_time = time.time()
    no_frame_count = 0
    
    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                no_frame_count += 1
                if no_frame_count > 10:
                    print("[INFERENCE] Too many camera failures, exiting", flush=True)
                    break
                time.sleep(0.1)
                continue
            
            no_frame_count = 0
            frame_count += 1
            
            # Calculate FPS
            current_time = time.time()
            frame_interval = current_time - last_frame_time
            last_frame_time = current_time
            
            actual_fps = 1.0 / frame_interval if frame_interval > 0 else 0.0
            
            # YOLO inference
            frame_resized = cv2.resize(frame, (model_width, model_height))
            input_data = np.expand_dims(frame_resized.astype('int8'), axis=0)
            
            t_start = time.time()
            interpreter.set_tensor(input_details[0]['index'], input_data)
            interpreter.invoke()
            output_data = interpreter.get_tensor(output_details[0]['index'])
            inference_time = (time.time() - t_start) * 1000
            
            # Post-process YOLO output
            display_frame = cv2.resize(frame, (OUTPUT_WIDTH, OUTPUT_HEIGHT))
            boxes, scores, classes = postprocess_yolo(output_data, OUTPUT_WIDTH, OUTPUT_HEIGHT)
            
            # Draw bounding boxes and labels
            detection_count = 0
            for (box, score, cls) in zip(boxes, scores, classes):
                x1, y1, x2, y2 = box
                color = (0, 255, 0)  # Green for all detections
                
                # Draw bounding box
                cv2.rectangle(display_frame, (x1, y1), (x2, y2), color, 2)
                
                # Draw label with background
                label = f"{CLASS_NAMES[cls] if cls < len(CLASS_NAMES) else str(cls)}:{score:.2f}"
                label_size = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 2)[0]
                
                # Draw label background
                cv2.rectangle(display_frame, (x1, y1 - label_size[1] - 6), (x1 + label_size[0] + 6, y1), color, -1)
                
                # Draw label text
                cv2.putText(display_frame, label, (x1 + 3, y1 - 3), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
                
                detection_count += 1
            
            # Clean green overlay
            cv2.rectangle(display_frame, (0, 0), (OUTPUT_WIDTH, 70), (0, 0, 0), -1)
            
            # Line 1: FPS and model info
            info_line = f"FPS:{actual_fps:.1f} | Frame:{frame_count} | {MODEL_ID} | {inference_time:.1f}ms"
            cv2.putText(display_frame, info_line, (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
            
            # Status in corner
            is_streaming = check_streaming_status()
            status_text = "● LIVE" if is_streaming else "■ PAUSED"
            status_color = (0, 255, 0) if is_streaming else (0, 165, 255)
            cv2.putText(display_frame, status_text, (OUTPUT_WIDTH - 120, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, status_color, 2)
            
            # Line 2: Resolution and detection info
            if is_streaming:
                perf_line = f"Resolution: {OUTPUT_WIDTH}x{OUTPUT_HEIGHT} | Detections: {detection_count}"
                cv2.putText(display_frame, perf_line, (10, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
            else:
                cv2.putText(display_frame, "Streaming paused - inference continues", (10, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 165, 255), 1)
            
            # Check for swaps
            swap_data = check_for_swaps()
            if swap_data:
                print(f"[INFERENCE] Processing swap: {swap_data}")
            
            # Push to RTSP (client-aware)
            if is_streaming:
                success = rtsp_server.push_frame(display_frame)
            else:
                success = False
            
            # Save frame with detections - FIXED
            save_frame_with_detections(display_frame, detection_count, boxes, scores, classes)
            
            # Send events (rate limited)
            if detection_count > 0 and frame_count % 30 == 0:
                try:
                    _, jpeg = cv2.imencode('.jpg', display_frame)
                    event_data = {
                        "event_type": "detection",
                        "model_id": MODEL_ID,
                        "image_base64": "data:image/jpeg;base64," + base64.b64encode(jpeg).decode(),
                        "timestamp": datetime.now().isoformat(),
                        "board_id": BOARD_ID,
                        "inference_time": inference_time,
                        "detections": detection_count
                    }
                    requests.post(f"{BACKEND_URL}/events", json=event_data, timeout=1)
                except Exception as e:
                    print(f"[EVENT] Send failed: {e}", flush=True)
            
            # Log performance every 30 frames
            if frame_count % 10 == 0:
                send_profiling_update()
                client_info = f"Clients: {rtsp_server.client_count}"
                print(f"[INFERENCE] Frame: {frame_count} | FPS: {actual_fps:.1f} | {client_info} | Detections: {detection_count} | Push: {'OK' if success else 'FAIL'}")
            
            # Update profiling - FIXED
            update_profiling(actual_fps, inference_time)
            
            # Small delay to prevent CPU overload
            time.sleep(0.001)
    
    except KeyboardInterrupt:
        print("\n[INFO] Interrupted by user", flush=True)
    except Exception as e:
        print(f"[ERROR] Inference error: {e}", flush=True)
        import traceback
        traceback.print_exc()
    finally:
        print("[INFO] Inference cleanup", flush=True)
        cap.release()
        gc.collect()


# ------------------------------------------------------------------------------
# MAIN EXECUTION
# ------------------------------------------------------------------------------
def main():
    global rtsp_server
    
    print("=" * 70, flush=True)
    print("YOLO RTSP STREAMING WITH BOUNDING BOXES - FIXED REAL-TIME PROFILING")
    print("=" * 70, flush=True)
    
    # Start RTSP server FIRST
    print("[MAIN] Starting RTSP server with stability fixes...", flush=True)
    rtsp_server = EnhancedRtspServer(
        width=OUTPUT_WIDTH,
        height=OUTPUT_HEIGHT,
        fps=OUTPUT_FPS,
        mount=RTSP_MOUNT,
        port=RTSP_PORT
    )
    
    if not rtsp_server.start():
        print("[MAIN] ✗ Failed to start RTSP server")
        return 1
    
    print("[MAIN] RTSP server ready - waiting for clients to connect...")
    print("[MAIN] Starting YOLO inference...", flush=True)
    
    # Start inference in separate thread
    inference_thread = threading.Thread(target=inference_loop, daemon=True)
    inference_thread.start()
    
    print("=" * 70, flush=True)
    print("✓✓✓ YOLO SYSTEM READY - Waiting for RTSP clients", flush=True)
    print(f"RTSP URL: rtsp://{BOARD_IP}:{RTSP_PORT}{RTSP_MOUNT}", flush=True)
    print("=" * 70, flush=True)
    
    # Keep main thread alive
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        print("\n[MAIN] Shutting down...", flush=True)
        rtsp_server.stop()
    
    return 0


if __name__ == "__main__":
    sys.exit(main())