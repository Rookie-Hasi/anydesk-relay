import time
import io
import tkinter as tk
from tkinter import ttk
import cv2
import numpy as np
from PIL import Image, ImageTk
import customtkinter as ctk
import logging

logger = logging.getLogger("RemoteViewer")

class RemoteViewerWindow(ctk.CTkToplevel):
    def __init__(self, parent, target_id, send_cmd_callback, disconnect_callback):
        super().__init__(parent)
        self.target_id = target_id
        self.send_cmd = send_cmd_callback
        self.disconnect_callback = disconnect_callback

        self.title(f"Remote Desktop - {target_id}")
        self.geometry("1100x750")
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        # Performance counters & state
        self.last_frame_time = time.time()
        self.frame_count = 0
        self.current_fps = 0
        self.photo_image = None
        self.image_item = None
        self.canvas_width = 1000
        self.canvas_height = 650
        self.is_fullscreen = False
        self.last_mouse_send = 0.0

        self._build_ui()
        self._bind_events()

    def _build_ui(self):
        # Top Bar
        self.top_bar = ctk.CTkFrame(self, height=45, fg_color="#1e1e24", corner_radius=0)
        self.top_bar.pack(side="top", fill="x")

        self.lbl_target = ctk.CTkLabel(
            self.top_bar, 
            text=f"🖥️ Connected to: {self.target_id}", 
            font=ctk.CTkFont(size=14, weight="bold")
        )
        self.lbl_target.pack(side="left", padx=15, pady=8)

        self.lbl_fps = ctk.CTkLabel(
            self.top_bar, 
            text="FPS: --", 
            text_color="#8ec07c",
            font=ctk.CTkFont(size=12, weight="bold")
        )
        self.lbl_fps.pack(side="left", padx=10, pady=8)

        self.btn_fullscreen = ctk.CTkButton(
            self.top_bar, 
            text="⛶ Fullscreen", 
            width=90, 
            height=28,
            fg_color="#3c3836",
            hover_color="#504945",
            command=self.toggle_fullscreen
        )
        self.btn_fullscreen.pack(side="right", padx=10, pady=8)

        self.btn_disconnect = ctk.CTkButton(
            self.top_bar, 
            text="❌ Disconnect", 
            width=100, 
            height=28, 
            fg_color="#cc241d", 
            hover_color="#fb4934",
            command=self.on_close
        )
        self.btn_disconnect.pack(side="right", padx=10, pady=8)

        # Video Canvas Container
        self.canvas_container = tk.Frame(self, bg="#121214")
        self.canvas_container.pack(side="bottom", fill="both", expand=True)

        self.canvas = tk.Canvas(self.canvas_container, bg="#121214", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)

        # Persistent canvas item for video frames
        self.image_item = self.canvas.create_image(0, 0, anchor="nw")
        self.text_item = self.canvas.create_text(
            500, 300, 
            text="Connecting to video stream...", 
            fill="#a1a1aa", 
            font=("Arial", 16)
        )

    def _bind_events(self):
        # Resize listener
        self.canvas.bind("<Configure>", self._on_canvas_resize)

        # Mouse listener (with 35Hz rate throttling to avoid network flooding)
        self.canvas.bind("<Motion>", self._on_mouse_move)
        self.canvas.bind("<Button-1>", lambda e: self._on_mouse_button("down", e, 1))
        self.canvas.bind("<ButtonRelease-1>", lambda e: self._on_mouse_button("up", e, 1))
        self.canvas.bind("<Button-3>", lambda e: self._on_mouse_button("down", e, 3))
        self.canvas.bind("<ButtonRelease-3>", lambda e: self._on_mouse_button("up", e, 3))
        self.canvas.bind("<Button-2>", lambda e: self._on_mouse_button("down", e, 2))
        self.canvas.bind("<ButtonRelease-2>", lambda e: self._on_mouse_button("up", e, 2))
        self.canvas.bind("<MouseWheel>", self._on_mouse_wheel)

        # Keyboard listener
        self.bind("<KeyPress>", self._on_key_press)
        self.bind("<KeyRelease>", self._on_key_release)
        self.canvas.focus_set()

    def _on_canvas_resize(self, event):
        self.canvas_width = max(event.width, 100)
        self.canvas_height = max(event.height, 100)
        if self.text_item:
            self.canvas.coords(self.text_item, self.canvas_width // 2, self.canvas_height // 2)

    def _get_normalized_coords(self, x, y):
        norm_x = max(0.0, min(1.0, x / self.canvas_width))
        norm_y = max(0.0, min(1.0, y / self.canvas_height))
        return norm_x, norm_y

    def _on_mouse_move(self, event):
        now = time.time()
        # Rate-limit mouse movements to ~35Hz to prevent socket congestion
        if now - self.last_mouse_send < 0.028:
            return
        self.last_mouse_send = now

        nx, ny = self._get_normalized_coords(event.x, event.y)
        self.send_cmd({
            "type": "mouse_event",
            "action": "move",
            "x": nx,
            "y": ny
        })

    def _on_mouse_button(self, action, event, button_num):
        self.canvas.focus_set()
        nx, ny = self._get_normalized_coords(event.x, event.y)
        self.send_cmd({
            "type": "mouse_event",
            "action": action,
            "button": button_num,
            "x": nx,
            "y": ny
        })

    def _on_mouse_wheel(self, event):
        delta = event.delta / 120.0
        self.send_cmd({
            "type": "mouse_event",
            "action": "scroll",
            "delta": delta
        })

    def _on_key_press(self, event):
        self.send_cmd({
            "type": "key_event",
            "action": "down",
            "key": event.keysym,
            "char": event.char
        })

    def _on_key_release(self, event):
        self.send_cmd({
            "type": "key_event",
            "action": "up",
            "key": event.keysym,
            "char": event.char
        })

    def update_bgr_frame(self, img_bgr):
        try:
            if img_bgr.shape[1] != self.canvas_width or img_bgr.shape[0] != self.canvas_height:
                img_bgr = cv2.resize(img_bgr, (self.canvas_width, self.canvas_height), interpolation=cv2.INTER_LINEAR)

            img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
            pil_image = Image.fromarray(img_rgb)
            self.photo_image = ImageTk.PhotoImage(pil_image, master=self.canvas)
            self.canvas.itemconfig(self.image_item, image=self.photo_image)

            if self.text_item:
                self.canvas.delete(self.text_item)
                self.text_item = None

            self.frame_count += 1
            now = time.time()
            if now - self.last_frame_time >= 1.0:
                self.current_fps = self.frame_count
                self.frame_count = 0
                self.last_frame_time = now
                self.lbl_fps.configure(text=f"Direct P2P: {self.current_fps} FPS", text_color="#22c55e")
        except Exception as e:
            logger.error(f"Error rendering bgr frame: {e}")

    def update_frame(self, jpeg_bytes):
        try:
            # High-speed OpenCV decoding & scaling
            nparr = np.frombuffer(jpeg_bytes, np.uint8)
            img_bgr = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            if img_bgr is None:
                return

            if img_bgr.shape[1] != self.canvas_width or img_bgr.shape[0] != self.canvas_height:
                img_bgr = cv2.resize(img_bgr, (self.canvas_width, self.canvas_height), interpolation=cv2.INTER_LINEAR)

            img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
            pil_image = Image.fromarray(img_rgb)
            
            # Explicit master=self.canvas guarantees proper Tkinter binding and prevents black screens
            self.photo_image = ImageTk.PhotoImage(pil_image, master=self.canvas)
            self.canvas.itemconfig(self.image_item, image=self.photo_image)

            # Hide initial placeholder text once first frame is rendered
            if self.text_item:
                self.canvas.delete(self.text_item)
                self.text_item = None

            # FPS Calculation
            self.frame_count += 1
            now = time.time()
            if now - self.last_frame_time >= 1.0:
                self.current_fps = self.frame_count
                self.frame_count = 0
                self.last_frame_time = now
                self.lbl_fps.configure(text=f"FPS: {self.current_fps}")

        except Exception as e:
            logger.error(f"Error rendering remote frame: {e}")

    def toggle_fullscreen(self):
        self.is_fullscreen = not self.is_fullscreen
        self.attributes("-fullscreen", self.is_fullscreen)
        if self.is_fullscreen:
            self.btn_fullscreen.configure(text="Exit Fullscreen")
        else:
            self.btn_fullscreen.configure(text="⛶ Fullscreen")

    def on_close(self):
        self.disconnect_callback()
        self.destroy()
