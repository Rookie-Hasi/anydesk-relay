import time
import threading
import ctypes
import cv2
import numpy as np
import mss
import logging

logger = logging.getLogger("ScreenStreamer")

class ScreenStreamer:
    def __init__(self, send_callback, quality=55, fps_limit=25, scale=0.75):
        self.send_callback = send_callback
        self.quality = quality
        self.fps_limit = fps_limit
        self.scale = scale
        self.is_running = False
        self.thread = None

    def start(self):
        if not self.is_running:
            self.is_running = True
            self.thread = threading.Thread(target=self._capture_loop, daemon=True)
            self.thread.start()
            logger.info("Screen capture streaming started.")

    def stop(self):
        self.is_running = False
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=1.5)
        logger.info("Screen capture streaming stopped.")

    def _capture_loop(self):
        # Attach thread to interactive desktop station on Windows
        try:
            u32 = ctypes.windll.user32
            desk = u32.OpenInputDesktop(0, False, 0x01FF)
            if desk:
                u32.SetThreadDesktop(desk)
        except Exception as e:
            logger.warning(f"Could not attach thread to desktop station: {e}")

        sct = mss.MSS()
        monitor = sct.monitors[1]  # Primary monitor
        target_interval = 1.0 / self.fps_limit if self.fps_limit > 0 else 0.04
        encode_params = [int(cv2.IMWRITE_JPEG_QUALITY), int(self.quality)]

        while self.is_running:
            start_time = time.time()
            try:
                # 1. Grab raw screen pixels
                raw_frame = sct.grab(monitor)
                frame = np.array(raw_frame, dtype=np.uint8)
                frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)

                # 2. Scale down slightly for crisp balance between speed & bandwidth
                if self.scale != 1.0:
                    width = int(frame.shape[1] * self.scale)
                    height = int(frame.shape[0] * self.scale)
                    frame = cv2.resize(frame, (width, height), interpolation=cv2.INTER_LINEAR)

                # 3. Fast OpenCV JPEG encoding
                success, encoded_img = cv2.imencode('.jpg', frame, encode_params)
                if success:
                    jpeg_bytes = encoded_img.tobytes()
                    # Deliver directly to network sender
                    self.send_callback(jpeg_bytes)

            except Exception as e:
                logger.error(f"Capture error: {e}")
                time.sleep(0.1)

            elapsed = time.time() - start_time
            sleep_time = target_interval - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)
