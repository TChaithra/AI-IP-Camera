# app/board_connector.py - Enhanced Multi-Board Connector
import requests
from app.config import RTSP_PORT, RTSP_MOUNT_POINT

class BoardConnector:
    """Helper class to communicate with board_server.py on different boards"""
    
    def __init__(self, board_ip, board_port):
        self.board_ip = board_ip
        self.board_port = board_port
        self.base = f"http://{board_ip}:{board_port}"
        print(f"[BoardConnector] Initialized: {self.base}")

    def start_inference(self, model_id, model_path, camera_path, script_path):
        """
        Start inference job on board with RTSP streaming.
        
        Args:
            model_id: Model identifier
            model_path: Path to TFLite model file on the board
            camera_path: Camera device path on the board
            script_path: Path to inference script on the board
        
        Returns:
            dict with 'ok', 'message', 'rtsp_url', and 'script' keys
        """
        payload = {
            "model_id": model_id,
            "model_path": model_path,
            "camera_path": camera_path,
            "script_path": script_path
        }
        
        print(f"[BoardConnector] Starting job on {self.board_ip}:")
        print(f"  model_id: {model_id}")
        print(f"  model_path: {model_path}")
        print(f"  camera_path: {camera_path}")
        print(f"  script_path: {script_path}")
        
        try:
            r = requests.post(
                f"{self.base}/start_job", 
                json=payload, 
                timeout=10
            )
            r.raise_for_status()
            response = r.json()
            print(f"[BoardConnector] Response: {response}")
            
            if not response.get("ok"):
                print(f"[BoardConnector] ERROR: Board returned ok=False")
                return {"ok": False, "message": response.get("message", "Unknown error")}
            
            if not response.get("rtsp_url"):
                print(f"[BoardConnector] WARNING: No RTSP URL in response")
                response["rtsp_url"] = f"rtsp://{self.board_ip}:{RTSP_PORT}{RTSP_MOUNT_POINT}"
                print(f"[BoardConnector] Using default RTSP URL: {response['rtsp_url']}")
            
            return response
            
        except requests.exceptions.Timeout:
            print(f"[BoardConnector] ERROR: Request timeout")
            return {"ok": False, "message": "Board request timeout"}
        except requests.exceptions.ConnectionError as e:
            print(f"[BoardConnector] ERROR: Connection failed: {e}")
            return {"ok": False, "message": f"Cannot connect to board at {self.base}"}
        except requests.exceptions.RequestException as e:
            print(f"[BoardConnector] ERROR: {e}")
            return {"ok": False, "message": str(e)}

    def stop(self):
        """Stop the current inference job on the board"""
        print(f"[BoardConnector] Stopping job on {self.board_ip}...")
        try:
            r = requests.post(f"{self.base}/stop_job", timeout=5)
            r.raise_for_status()
            response = r.json()
            print(f"[BoardConnector] Stop response: {response}")
            return response
        except requests.exceptions.RequestException as e:
            print(f"[BoardConnector] ERROR stopping: {e}")
            return {"ok": False, "message": str(e)}

    def health(self):
        """Check if board server is running and get status"""
        try:
            r = requests.get(f"{self.base}/health", timeout=5)
            r.raise_for_status()
            return r.json()
        except requests.exceptions.RequestException as e:
            print(f"[BoardConnector] Health check failed for {self.board_ip}: {e}")
            return {"ok": False, "message": str(e)}

    def get_board_info(self):
        """Get board information including available cameras and models"""
        try:
            r = requests.get(f"{self.base}/board_info", timeout=5)
            r.raise_for_status()
            return r.json()
        except requests.exceptions.RequestException as e:
            print(f"[BoardConnector] Get board info failed: {e}")
            return {"ok": False, "message": str(e)}

    def _make_request(self, method, endpoint, **kwargs):
        """Internal method to make HTTP requests to board server"""
        try:
            url = f"{self.base}{endpoint}"
            print(f"[BoardConnector] {method} {url}")
            
            response = requests.request(method, url, timeout=10, **kwargs)
            response.raise_for_status()
            
            if response.headers.get('content-type', '').startswith('application/json'):
                return response.json()
            else:
                return {"ok": True, "message": "Success"}
                
        except requests.exceptions.Timeout:
            print(f"[BoardConnector] ERROR: Request timeout for {endpoint}")
            return {"ok": False, "message": "Board request timeout"}
        except requests.exceptions.ConnectionError as e:
            print(f"[BoardConnector] ERROR: Connection failed for {endpoint}: {e}")
            return {"ok": False, "message": f"Cannot connect to board at {self.base}"}
        except requests.exceptions.RequestException as e:
            print(f"[BoardConnector] ERROR: {endpoint} - {e}")
            return {"ok": False, "message": str(e)}

    # NEW: Enhanced pause/resume methods
    def pause_video(self):
        """Pause video streaming"""
        return self._make_request("POST", "/pause_video")

    def resume_video(self):
        """Resume video streaming"""
        return self._make_request("POST", "/resume_video")

    # NEW: Instant switching methods
    def swap_camera(self, camera_path):
        """Swap camera without stopping inference"""
        return self._make_request("POST", "/swap_camera", json={"camera_path": camera_path})

    def swap_model(self, model_path):
        """Swap model without stopping inference"""
        return self._make_request("POST", "/swap_model", json={"model_path": model_path})# app/board_connector.py - Enhanced Multi-Board Connector

import requests
from app.config import RTSP_PORT, RTSP_MOUNT_POINT

class BoardConnector:
    """Helper class to communicate with board_server.py on different boards"""
    
    def __init__(self, board_ip, board_port):
        self.board_ip = board_ip
        self.board_port = board_port
        self.base = f"http://{board_ip}:{board_port}"
        print(f"[BoardConnector] Initialized: {self.base}")

    # ------------------------------------------------------------------
    # Core inference control
    # ------------------------------------------------------------------
    def start_inference(self, model_id, model_path, camera_path, script_path):
        """Start inference job on board with RTSP streaming"""
        payload = {
            "model_id": model_id,
            "model_path": model_path,
            "camera_path": camera_path,
            "script_path": script_path
        }
        print(f"[BoardConnector] Starting job on {self.board_ip}:")
        print(f"  model_id: {model_id}")
        print(f"  model_path: {model_path}")
        print(f"  camera_path: {camera_path}")
        print(f"  script_path: {script_path}")

        try:
            r = requests.post(f"{self.base}/start_job", json=payload, timeout=10)
            r.raise_for_status()
            response = r.json()
            print(f"[BoardConnector] Response: {response}")

            if not response.get("ok"):
                print("[BoardConnector] ERROR: Board returned ok=False")
                return {"ok": False, "message": response.get("message", "Unknown error")}

            if not response.get("rtsp_url"):
                print("[BoardConnector] WARNING: No RTSP URL in response")
                response["rtsp_url"] = f"rtsp://{self.board_ip}:{RTSP_PORT}{RTSP_MOUNT_POINT}"
                print(f"[BoardConnector] Using default RTSP URL: {response['rtsp_url']}")

            return response

        except requests.exceptions.Timeout:
            print("[BoardConnector] ERROR: Request timeout")
            return {"ok": False, "message": "Board request timeout"}

        except requests.exceptions.ConnectionError as e:
            print(f"[BoardConnector] ERROR: Connection failed: {e}")
            return {"ok": False, "message": f"Cannot connect to board at {self.base}"}

        except requests.exceptions.RequestException as e:
            print(f"[BoardConnector] ERROR: {e}")
            return {"ok": False, "message": str(e)}

    def stop(self):
        """Stop the current inference job on the board"""
        print(f"[BoardConnector] Stopping job on {self.board_ip}...")
        try:
            r = requests.post(f"{self.base}/stop_job", timeout=5)
            r.raise_for_status()
            response = r.json()
            print(f"[BoardConnector] Stop response: {response}")
            return response
        except requests.exceptions.RequestException as e:
            print(f"[BoardConnector] ERROR stopping: {e}")
            return {"ok": False, "message": str(e)}

    # ------------------------------------------------------------------
    # Health & info
    # ------------------------------------------------------------------
    def health(self):
        """Check if board server is running and get status"""
        try:
            r = requests.get(f"{self.base}/health", timeout=5)
            r.raise_for_status()
            return r.json()
        except requests.exceptions.RequestException as e:
            print(f"[BoardConnector] Health check failed for {self.board_ip}: {e}")
            return {"ok": False, "message": str(e)}

    def get_board_info(self):
        """Get board information including available cameras and models"""
        try:
            r = requests.get(f"{self.base}/board_info", timeout=5)
            r.raise_for_status()
            return r.json()
        except requests.exceptions.RequestException as e:
            print(f"[BoardConnector] Get board info failed: {e}")
            return {"ok": False, "message": str(e)}

    # ------------------------------------------------------------------
    # Internal request helper
    # ------------------------------------------------------------------
    def _make_request(self, method, endpoint, **kwargs):
        """Internal method to make HTTP requests to board server"""
        try:
            url = f"{self.base}{endpoint}"
            print(f"[BoardConnector] {method} {url}")
            response = requests.request(method, url, timeout=10, **kwargs)
            response.raise_for_status()

            if response.headers.get('content-type', '').startswith('application/json'):
                return response.json()
            else:
                return {"ok": True, "message": "Success"}

        except requests.exceptions.Timeout:
            print(f"[BoardConnector] ERROR: Request timeout for {endpoint}")
            return {"ok": False, "message": "Board request timeout"}

        except requests.exceptions.ConnectionError as e:
            print(f"[BoardConnector] ERROR: Connection failed for {endpoint}: {e}")
            return {"ok": False, "message": f"Cannot connect to board at {self.base}"}

        except requests.exceptions.RequestException as e:
            print(f"[BoardConnector] ERROR: {endpoint} - {e}")
            return {"ok": False, "message": str(e)}

    # ------------------------------------------------------------------
    # Enhanced control: pause / resume / instant switching
    # ------------------------------------------------------------------
    def pause_video(self):
        """Pause video streaming"""
        return self._make_request("POST", "/pause_video")

    def resume_video(self):
        """Resume video streaming"""
        return self._make_request("POST", "/resume_video")

    def swap_camera(self, camera_path):
        """Swap camera without stopping inference"""
        return self._make_request("POST", "/swap_camera", json={"camera_path": camera_path})

    def swap_model(self, model_path):
        """Swap model without stopping inference"""
        return self._make_request("POST", "/swap_model", json={"model_path": model_path})