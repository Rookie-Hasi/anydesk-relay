import time
import threading
import ctypes
from ctypes import c_void_p, c_int, c_uint, windll
import cv2
import numpy as np
import mss
from PIL import ImageGrab
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
        # 1. Attach thread to interactive desktop station with proper 64-bit ctypes
        try:
            u32 = windll.user32
            u32.OpenInputDesktop.argtypes = [c_uint, c_int, c_uint]
            u32.OpenInputDesktop.restype = c_void_p
            u32.SetThreadDesktop.argtypes = [c_void_p]
            u32.SetThreadDesktop.restype = c_int

            desk = u32.OpenInputDesktop(0, 0, 0x01FF)
            if desk:
                u32.SetThreadDesktop(desk)
                logger.info(f"Attached thread to desktop station handle: {desk}")
        except Exception as e:
            logger.warning(f"Could not attach thread to desktop station: {e}")

        sct = None
        try:
            sct = mss.MSS()
            monitor = sct.monitors[1]
        except Exception as e:
            logger.warning(f"MSS init warning: {e}")

        target_interval = 1.0 / self.fps_limit if self.fps_limit > 0 else 0.04
        encode_params = [int(cv2.IMWRITE_JPEG_QUALITY), int(self.quality)]

        while self.is_running:
            start_time = time.time()
            frame = None

            # Primary capture: High-speed MSS
            if sct:
                try:
                    raw_frame = sct.grab(monitor)
                    frame_bgra = np.array(raw_frame, dtype=np.uint8)
                    frame = cv2.cvtColor(frame_bgra, cv2.COLOR_BGRA2BGR)
                except Exception as e:
                    # MSS error fallback
                    pass

            # Fallback capture: PIL ImageGrab (Guaranteed to work if MSS fails)
            if frame is None:
                try:
                    pil_img = ImageGrab.grab()
                    frame_rgb = np.array(pil_img, dtype=np.uint8)
                    frame = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)
                except Exception as e:
                    logger.error(f"Fallback grab error: {e}")

            if frame is not None:
                try:
                    # Scale for optimal speed & quality balance
                    if self.scale != 1.0:
                        w = int(frame.shape[1] * self.scale)
                        h = int(frame.shape[0] * self.scale)
                        frame = cv2.resize(frame, (w, h), interpolation=cv2.INTER_LINEAR)

                    success, encoded = cv2.imencode('.jpg', frame, encode_params)
                    if success:
                        self.send_callback(encoded.tobytes())
                except Exception as e:
                    logger.error(f"Encode error: {e}")

            elapsed = time.time() - start_time
            sleep_time = target_interval - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)
