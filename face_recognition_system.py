# backend/face_recognition_system.py - Optimized for Raspberry Pi
"""
FaceRecognitionSystem - Optimized for Raspberry Pi
- Lightweight processing
- Reduced memory usage
- Optimized for ARM architecture
"""

from typing import List, Tuple, Optional, Dict, Any
import time
import numpy as np
import cv2
import warnings

try:
    import face_recognition
    print("✅ face_recognition loaded successfully")
except Exception as e:
    raise ImportError(f"Install face_recognition: {e}")

class FaceRecognitionSystem:
    def __init__(self, database, tolerance: float = 0.6, model: str = "hog", scale: float = 0.25):
        self.database = database
        self.tolerance = float(tolerance)
        self.model = model
        self.scale = float(scale)
        
        # Core components
        self.known_face_encodings: List[np.ndarray] = []
        self.known_face_names: List[str] = []
        self.known_face_user_ids: List[int] = []
        self._enc_matrix: Optional[np.ndarray] = None
        
        print(f"🔧 FaceRecognitionSystem initialized:")
        print(f"   - Model: {model}")
        print(f"   - Tolerance: {tolerance}")
        print(f"   - Scale: {scale}")
        
        self.reload_cache()

    def reload_cache(self) -> None:
        """Reload face encodings from database"""
        self.known_face_encodings.clear()
        self.known_face_names.clear()
        self.known_face_user_ids.clear()
        
        rows = self.database.get_all_users()
        loaded_count = 0
        
        for row in rows:
            enc_bytes = row.get("encoding") or row.get("face_encoding")
            if not enc_bytes:
                continue
            try:
                # Simple decoding for Raspberry Pi
                enc = np.frombuffer(enc_bytes, dtype=np.float64)
                if enc.size == 128:  # Standard face encoding size
                    self.known_face_encodings.append(enc)
                    self.known_face_names.append(row.get("name", "Unknown"))
                    self.known_face_user_ids.append(int(row.get("id")))
                    loaded_count += 1
            except Exception as e:
                print(f"❌ Error loading face encoding for {row.get('name')}: {e}")
                continue
                
        if len(self.known_face_encodings) > 0:
            self._enc_matrix = np.vstack(self.known_face_encodings).astype(np.float32)  # Use float32 for efficiency
        else:
            self._enc_matrix = None
            
        print(f"✅ Loaded {loaded_count} face encodings from database")

    def register_face_bytes(self, image_bytes: bytes, name: str, employee_id: str, 
                          num_jitters: int = 1, enable_anti_spoof: bool = False) -> Tuple[bool, str]:
        """Register a new face with the system"""
        start_time = time.time()
        
        print(f"👤 Registering face for: {name} ({employee_id})")
        
        data = np.frombuffer(image_bytes, dtype=np.uint8)
        bgr = cv2.imdecode(data, cv2.IMREAD_COLOR)
        if bgr is None:
            return False, "Invalid image file."
            
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        boxes = face_recognition.face_locations(rgb, model=self.model)
        
        if len(boxes) == 0:
            return False, "No face detected. Use a clear frontal photo."
        if len(boxes) > 1:
            return False, "Multiple faces detected. Upload a single-person image."
            
        encs = face_recognition.face_encodings(rgb, boxes, num_jitters=num_jitters)
        if not encs:
            return False, "Unable to compute face encoding."
            
        encoding = encs[0]
        
        try:
            user_id = self.database.add_user(name, employee_id, encoding.tobytes())
        except Exception as exc:
            return False, f"Registration failed: {exc}"
            
        self.known_face_encodings.append(encoding)
        self.known_face_names.append(name)
        self.known_face_user_ids.append(user_id)
        
        if self._enc_matrix is None:
            self._enc_matrix = encoding.reshape(1, -1).astype(np.float32)
        else:
            self._enc_matrix = np.vstack([self._enc_matrix, encoding.astype(np.float32)])
        
        processing_time = time.time() - start_time
        print(f"✅ Registration completed in {processing_time:.2f}s")
        
        return True, f"Successfully registered {name} ({employee_id})"

    def _vectorized_compare(self, enc: np.ndarray) -> Tuple[int, float, bool]:
        """Efficient vector comparison optimized for Raspberry Pi"""
        if self._enc_matrix is None:
            return -1, float("inf"), False
            
        # Use efficient matrix operations with float32
        enc_32 = enc.astype(np.float32)
        diff = self._enc_matrix - enc_32
        dists = np.sqrt(np.einsum('ij,ij->i', diff, diff))
            
        best_idx = int(np.argmin(dists))
        best_dist = float(dists[best_idx])
        is_match = best_dist <= self.tolerance
        
        return best_idx, best_dist, is_match

    def recognize(self, frame_bgr):
        """Main recognition function - optimized for performance"""
        if frame_bgr is None:
            return [], [], []
            
        start_time = time.time()
        
        # Resize frame for faster processing
        if self.scale != 1.0:
            small = cv2.resize(frame_bgr, (0, 0), fx=self.scale, fy=self.scale)
        else:
            small = frame_bgr
            
        rgb_small = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
        
        # Fast face detection
        boxes_small = face_recognition.face_locations(rgb_small, model=self.model, number_of_times_to_upsample=0)
        
        if not boxes_small:
            return [], [], []
            
        # Get face encodings
        encs = face_recognition.face_encodings(rgb_small, boxes_small)
        names, uids = [], []
        
        if self._enc_matrix is None:
            # No known faces
            for _ in encs:
                names.append("Unknown")
                uids.append(-1)
        else:
            # Compare with known faces
            for enc in encs:
                best_idx, best_dist, is_match = self._vectorized_compare(enc)
                
                if is_match:
                    names.append(self.known_face_names[best_idx])
                    uids.append(self.known_face_user_ids[best_idx])
                else:
                    names.append("Unknown")
                    uids.append(-1)
        
        # Scale boxes back to original size
        scale_inv = round(1.0 / self.scale) if self.scale != 0 else 1
        boxes = [(t*scale_inv, r*scale_inv, b*scale_inv, l*scale_inv) for (t, r, b, l) in boxes_small]
        
        processing_time = time.time() - start_time
        if processing_time > 0.5:
            print(f"⚠️ Slow recognition: {processing_time:.2f}s")
        
        return boxes, names, uids

    def set_tolerance(self, tol: float):
        self.tolerance = float(tol)
        print(f"🔧 Tolerance set to: {tol}")
        
    def set_model(self, model: str):
        if model not in ("hog", "cnn"):
            raise ValueError("model must be 'hog' or 'cnn'")
        self.model = model
        print(f"🔧 Model set to: {model}")
        
    def set_scale(self, scale: float):
        if not (0 < scale <= 1.0):
            raise ValueError("scale must be in (0, 1].")
        self.scale = float(scale)
        print(f"🔧 Scale set to: {scale}")

# Simple test
if __name__ == "__main__":
    class MockDatabase:
        def get_all_users(self):
            return []
        def add_user(self, name, employee_id, encoding):
            return 1
    
    print("🧪 Testing FaceRecognitionSystem...")
    system = FaceRecognitionSystem(MockDatabase())
    print("✅ System ready!")