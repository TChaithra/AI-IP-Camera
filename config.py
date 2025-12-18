# config.py - ENHANCED WITH COMPUTATIONAL BOARD SUPPORT
# Supports multiple board types with different paths, cameras, and models

# --- Board Registry ---
BOARDS = {
    "imx8": {
        "id": "imx8",
        "name": "IMX8M+ Board",
        "ip": "192.168.1.22",
        "control_port": 9000,
        "base_path": "/root/chaitra/imx",
        "cameras": {
            "camera_3": {
                "name": "Camera 3 - IMX Board Camera",
                "path": "/dev/video3"
            },
            "camera_4": {
                "name": "Camera 4 - IMX Secondary Camera", 
                "path": "/dev/video4"
            }
        },
        "models": {
            "overspeed": {
                "name": "Overspeed Detection (INT8)",
                "script": "overspeed_stream.py",
                "model_file": "overspeed.tflite"
            },
            "raw-video": {
                "name": "🎥 RAW VIDEO TEST (No Inference)",
                "script": "raw_video_stream.py",
                "model_file": ""
            },
            "helmet": {
                "name": "Helmet Detection (INT8)",
                "script": "helmet_stream.py",
                "model_file": "helmet.tflite"
            },
            "yolo": {
                "name": "YOLO Detection",
                "script": "yolo_stream.py",
                "model_file": "yolo.tflite"
            }
        }
    },
    
    "computational": {
        "id": "computational",
        "name": "Computational Lab Board",
        "ip": "192.168.1.31",  # Updated IP
        "control_port": 4000,   # Updated port
        "base_path": "/root/chaitra/computational",
        "cameras": {
            "camera_3": {
                "name": "Stored Video Input",
                "path": "/root/chaitra/computational/test_video.mp4"  # Video file path
            },
            "camera_4": {
                "name": "Backup Camera",
                "path": "/dev/video4"
            }
        },
        "models": {
            "overspeed": {
                "name": "Overspeed Detection (INT8)",
                "script": "overspeed_stream.py",
                "model_file": "model_calibrated_int8_og.tflite"
            },
            "helmet": {
                "name": "Helmet Detection (INT8)",
                "script": "helmet_stream.py",
                "model_file": "helmet.tflite"
            },
            "triple-riding": {
                "name": "Triple Riding Detection",
                "script": "triple_riding_stream.py",
                "model_file": "triple_riding.tflite"
            },
            "wrong-way": {
                "name": "Wrong Way Detection",
                "script": "wrong_way_stream.py",
                "model_file": "wrong_way.tflite"
            },
            "yolo": {
                "name": "YOLO Detection",
                "script": "yolo_stream.py",
                "model_file": "yolo.tflite"
            }
        }
    }
}

# Default board for backward compatibility
DEFAULT_BOARD = "imx8"

# Backend IP (where Flask backend runs)
BACKEND_IP = "192.168.1.56"
BACKEND_PORT = 8000

# RTSP server configuration
RTSP_PORT = 8554
RTSP_MOUNT_POINT = "/chaithu"

# Board control port (Flask server on each board)
BOARD_CONTROL_PORT = 9000

# Database configuration for events
DATABASE_PATH = "./events.db"  # Local DB for development

# ALPR Configuration
ALPR_ENABLED = True
ALPR_CONFIDENCE_THRESHOLD = 0.6

# Event storage
MAX_RECENT_EVENTS = 50
EVENT_IMAGE_DIR = "./event_images"

# Saved frames configuration
SAVED_FRAMES_DIR = "./saved_frames"
MAX_SAVED_FRAMES = 100

# Helper function to get full paths
def get_model_path(board_id, model_id):
    """Get full path to model file"""
    if board_id not in BOARDS:
        return None
    
    board = BOARDS[board_id]
    if model_id not in board["models"]:
        return None
    
    model_file = board["models"][model_id]["model_file"]
    if not model_file:
        return ""
    
    return f"{board['base_path']}/{model_file}"

def get_script_path(board_id, model_id):
    """Get full path to script file"""
    if board_id not in BOARDS:
        return None
    
    board = BOARDS[board_id]
    if model_id not in board["models"]:
        return None
    
    script = board["models"][model_id]["script"]
    return f"{board['base_path']}/scripts/{script}"

def get_camera_path(board_id, camera_id):
    """Get camera device path"""
    if board_id not in BOARDS:
        return None
    
    board = BOARDS[board_id]
    if camera_id not in board["cameras"]:
        return None
    
    return board["cameras"][camera_id]["path"]