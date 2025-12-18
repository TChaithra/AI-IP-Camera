#!/usr/bin/env python3
"""
raw_video_stream.py - RAW VIDEO ONLY (NO INFERENCE)
Test script to verify maximum possible FPS without any AI processing.
This will show the pure camera -> RTSP -> browser speed.
"""

import os
import sys
import time
import cv2
import threading

sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

print("[STARTUP] RAW VIDEO TEST - NO INFERENCE", flush=True)

# GStreamer imports
try:
    import gi
    gi.require_version('Gst', '1.0')
    gi.require_version('GstRtspServer', '1.0')
    from gi.repository import Gst, GstRtspServer, GLib
    Gst.init(None)
    print("[STARTUP] GStreamer loaded", flush=True)
except Exception as e:
    print(f"[ERROR] GStreamer: {e}", flush=True)
    sys.exit(1)

# Configuration
MODEL_PATH = os.getenv('NPU_MODEL_PATH', "/root/chaitra/imx/models/raw.tflite")
VIDEO_SOURCE = os.getenv('NPU_VIDEO_SOURCE', "/dev/video4")
RTSP_PORT = int(os.getenv('NPU_RTSP_PORT', '8554'))
RTSP_MOUNT = os.getenv('NPU_RTSP_MOUNT', '/chaithu')
BOARD_IP = os.getenv('BOARD_IP', '192.168.1.22')

OUTPUT_WIDTH = 640
OUTPUT_HEIGHT = 480
TARGET_FPS = 30  # Try 30 FPS for raw video

print(f"[CONFIG] Target: {TARGET_FPS} FPS RAW video (no inference)", flush=True)


class EmbeddedRtspServer:
    """RTSP server for raw video streaming"""
    def __init__(self, output_path, width, height, fps, bitrate_kbps=2500, mount="/chaithu", port=8554):
        self.output_path = os.path.abspath(output_path)
        self.width = int(width)
        self.height = int(height)
        self.fps = int(round(fps))
        self.bitrate_kbps = bitrate_kbps
        self.mount = mount
        self.port = int(port)

        self.server = None
        self.factory = None
        self.appsrc = None
        self.main_loop = None
        self.thread = None
        self.media_ready = threading.Event()
        
        self._setup_server()

    def _on_media_configure(self, factory, media):
        element = media.get_element()
        if not element:
            return
            
        appsrc = element.get_child_by_name("appsrc")
        self.appsrc = appsrc
        
        if self.appsrc:
            caps_str = f"video/x-raw,format=BGR,width={self.width},height={self.height},framerate={self.fps}/1"
            caps = Gst.Caps.from_string(caps_str)
            
            try:
                self.appsrc.set_property("caps", caps)
                self.appsrc.set_property("format", Gst.Format.TIME)
                self.appsrc.set_property("is-live", True)
                self.appsrc.set_property("block", False)
                self.appsrc.set_property("max-bytes", 0)
                self.appsrc.set_property("max-buffers", 5)
            except Exception as e:
                print(f"[WARN] appsrc property error: {e}", flush=True)
            
            print(f"[RTSP] ✓ appsrc ready - {self.fps} FPS RAW mode", flush=True)
            self.media_ready.set()

    def _setup_server(self):
        """Pipeline for raw video streaming"""
        gst_launch = (
            f"( appsrc name=appsrc is-live=true block=false format=3 "
            f"caps=video/x-raw,format=BGR,width={self.width},height={self.height},framerate={self.fps}/1 ! "
            
            # Minimal queues
            f"queue max-size-buffers=3 ! "
            f"videoconvert ! "
            f"queue max-size-buffers=3 ! "
            f"v4l2convert ! "
            f"video/x-raw,format=NV12 ! "
            f"queue max-size-buffers=3 ! "
            
            # H.264 encoder
            f"v4l2h264enc extra-controls=\"controls,video_bitrate={self.bitrate_kbps * 1000}\" ! "
            f"video/x-h264,level=(string)4 ! "
            f"h264parse ! "
            
            # Tee
            f"tee name=t "
            
            # RTSP branch
            f"t. ! queue max-size-buffers=5 ! "
            f"rtph264pay name=pay0 pt=96 config-interval=1 "
            
            # Recording branch
            f"t. ! queue max-size-buffers=5 ! "
            f"mp4mux ! filesink location={self.output_path} sync=false )"
        )

        self.server = GstRtspServer.RTSPServer()
        self.server.set_service(str(self.port))

        self.factory = GstRtspServer.RTSPMediaFactory()
        self.factory.set_shared(True)
        self.factory.set_launch(gst_launch)
        self.factory.connect("media-configure", self._on_media_configure)

        mounts = self.server.get_mount_points()
        mounts.add_factory(self.mount, self.factory)
        self.main_loop = GLib.MainLoop()

    def start(self):
        if self.thread and self.thread.is_alive():
            return True
            
        def _run():
            self.server.attach(None)
            print(f"[RTSP] ✓ Server LIVE: rtsp://{BOARD_IP}:{self.port}{self.mount}", flush=True)
            try:
                self.main_loop.run()
            except Exception as e:
                print(f"[RTSP] Loop error: {e}", flush=True)
                
        self.thread = threading.Thread(target=_run, daemon=True)
        self.thread.start()
        return True

    def stop(self):
        try:
            if self.main_loop:
                self.main_loop.quit()
        except Exception:
            pass

    def push_frame(self, frame, pts_ns=None):
        if self.appsrc is None:
            return False

        if frame.shape[1] != self.width or frame.shape[0] != self.height:
            frame = cv2.resize(frame, (self.width, self.height), interpolation=cv2.INTER_LINEAR)

        try:
            data = frame.tobytes()
            
            try:
                buf = Gst.Buffer.new_wrapped(data)
            except Exception:
                buf = Gst.Buffer.new_allocate(None, len(data), None)
                success, mapinfo = buf.map(Gst.MapFlags.WRITE)
                if success:
                    try:
                        mapinfo.data[:] = data
                    except Exception:
                        try:
                            buf.fill(0, data)
                        except Exception:
                            pass
                    buf.unmap(mapinfo)

            if pts_ns is not None:
                try:
                    buf.pts = pts_ns
                    buf.duration = int(1e9 // self.fps)
                except Exception:
                    pass

            try:
                ret = self.appsrc.emit("push-buffer", buf)
            except Exception:
                try:
                    ret = self.appsrc.push_buffer(buf)
                except Exception:
                    return False
                    
            return True
            
        except Exception:
            return False


def main():
    print("=" * 70, flush=True)
    print("RAW VIDEO TEST - NO INFERENCE", flush=True)
    print(f"Target: {TARGET_FPS} FPS pure video streaming", flush=True)
    print("=" * 70, flush=True)
    
    try:
        # STEP 1: Start RTSP server
        print(f"[1/3] Starting RTSP server at {TARGET_FPS} FPS...", flush=True)
        rtsp_server = EmbeddedRtspServer(
            output_path="/tmp/rtsp_recording_raw.mp4",
            width=OUTPUT_WIDTH,
            height=OUTPUT_HEIGHT,
            fps=TARGET_FPS,
            bitrate_kbps=2500,
            mount=RTSP_MOUNT,
            port=RTSP_PORT
        )
        rtsp_server.start()
        print(f"[RTSP] ✓ Server active at {TARGET_FPS} FPS", flush=True)
        
        # STEP 2: Open camera
        print(f"[2/3] Opening camera at {OUTPUT_WIDTH}x{OUTPUT_HEIGHT} @ {TARGET_FPS} FPS...", flush=True)
        
        if VIDEO_SOURCE.startswith('/dev/video'):
            # Capture at target FPS
            pipeline = (
                f"v4l2src device={VIDEO_SOURCE} ! "
                f"video/x-raw,width={OUTPUT_WIDTH},height={OUTPUT_HEIGHT},framerate={TARGET_FPS}/1 ! "
                f"videoconvert ! "
                f"video/x-raw,format=BGR ! "
                f"appsink max-buffers=1 drop=false"
            )
            print(f"[CAMERA] Pipeline: {pipeline}", flush=True)
            cap = cv2.VideoCapture(pipeline, cv2.CAP_GSTREAMER)
        else:
            cap = cv2.VideoCapture(VIDEO_SOURCE)
            cap.set(cv2.CAP_PROP_FPS, TARGET_FPS)
        
        if not cap.isOpened():
            print(f"[ERROR] Failed to open: {VIDEO_SOURCE}", flush=True)
            return 1
        
        print(f"[CAMERA] ✓ Ready", flush=True)
        
        # STEP 3: Stream loop - NO INFERENCE!
        print(f"[3/3] Starting RAW video streaming (NO INFERENCE)...", flush=True)
        print("=" * 70, flush=True)
        
        frame_count = 0
        
        # FPS tracking
        fps_start_time = time.time()
        fps_frame_count = 0
        
        # PTS for RTSP
        pts_ns = 0
        frame_duration_ns = int(1e9 / TARGET_FPS)
        
        # Frame timing for consistent FPS
        target_frame_time = 1.0 / TARGET_FPS
        last_frame_time = time.time()
        
        while True:
            # Timing control
            current_time = time.time()
            elapsed = current_time - last_frame_time
            
            if elapsed < target_frame_time:
                time.sleep(target_frame_time - elapsed)
            
            last_frame_time = time.time()
            
            ret, frame = cap.read()
            if not ret:
                if VIDEO_SOURCE.startswith('/dev/video'):
                    continue
                else:
                    break
            
            frame_count += 1
            fps_frame_count += 1
            
            # Calculate current FPS
            elapsed = time.time() - fps_start_time
            if elapsed > 0:
                current_fps = fps_frame_count / elapsed
            else:
                current_fps = 0
            
            # Add minimal overlay (just FPS counter)
            cv2.rectangle(frame, (0, 0), (OUTPUT_WIDTH, 30), (0, 0, 0), -1)
            cv2.putText(frame, f"RAW VIDEO | FPS: {current_fps:.1f} | NO INFERENCE", 
                       (10, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
            
            # Push to RTSP
            rtsp_server.push_frame(frame, pts_ns=pts_ns)
            pts_ns += frame_duration_ns
            
            # Log stats every 100 frames
            if frame_count % 100 == 0:
                print(f"[STATS] Frame:{frame_count} | FPS:{current_fps:.1f} | RAW VIDEO (NO INFERENCE)", flush=True)
                fps_start_time = time.time()
                fps_frame_count = 0

    except KeyboardInterrupt:
        print(f"\n[INFO] Stopped", flush=True)
    except Exception as e:
        print(f"[ERROR] {e}", flush=True)
        import traceback
        traceback.print_exc()
    finally:
        print(f"[INFO] Cleanup", flush=True)
        if 'cap' in locals():
            cap.release()
        if 'rtsp_server' in locals():
            rtsp_server.stop()
    
    return 0


if __name__ == "__main__":
    sys.exit(main())









