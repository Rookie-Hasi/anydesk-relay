import os
import sys
import json
import time
import asyncio
import threading
import tkinter as tk
from tkinter import messagebox
import customtkinter as ctk
import websockets
import logging

from config import load_config, save_config, format_id
from input_handler import WindowsInputHandler
from screen_streamer import ScreenStreamer
from viewer import RemoteViewerWindow

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("DeskClient")

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

class AnyDeskCloneApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("AnyDesk Clone - Remote Desktop")
        self.geometry("820x570")
        self.resizable(False, False)

        # Load permanent configuration (stored in %APPDATA%\AnyDeskClone\config.json)
        self.config = load_config()
        self.my_id = self.config["id"]
        self.my_pin = self.config.get("pin", "1234")
        self.server_url = self.config.get("server_url", "wss://anydesk-relay-production.up.railway.app")

        # Network & Session State
        self.websocket = None
        self.is_connected_to_server = False
        self.viewer_window = None
        self.streamer = None
        self.input_handler = WindowsInputHandler()

        # Dedicated latest-frame buffer (prevents queue backup)
        self.latest_frame_to_send = None
        self.frame_send_event = asyncio.Event()

        # Asyncio event loop running on a dedicated background thread
        self.loop = asyncio.new_event_loop()
        self.net_thread = threading.Thread(target=self._run_async_loop, daemon=True)
        self.net_thread.start()

        # Build UI
        self._build_ui()

        # Connect to signaling server
        self.connect_to_server()

        # Periodic presence checker
        self.after(2000, self._periodic_presence_check)

        self.protocol("WM_DELETE_WINDOW", self.on_app_close)

    def _run_async_loop(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def _build_ui(self):
        # 1. Header Bar
        self.header_frame = ctk.CTkFrame(self, height=60, corner_radius=0, fg_color="#18181b")
        self.header_frame.pack(fill="x", side="top")

        self.title_label = ctk.CTkLabel(
            self.header_frame, 
            text="⚡ ANYDESK CLONE", 
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color="#ef4444"
        )
        self.title_label.pack(side="left", padx=20, pady=15)

        self.server_status_badge = ctk.CTkLabel(
            self.header_frame, 
            text="🔴 Server Offline", 
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#ef4444"
        )
        self.server_status_badge.pack(side="right", padx=20, pady=15)

        # 2. Main Content Frame (Two side-by-side cards)
        self.content_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.content_frame.pack(fill="both", expand=True, padx=20, pady=15)

        # LEFT CARD: This Device (Host)
        self.left_card = ctk.CTkFrame(self.content_frame, width=380, corner_radius=12, fg_color="#202024")
        self.left_card.pack(side="left", fill="both", expand=True, padx=(0, 10))

        self.lbl_this_desk = ctk.CTkLabel(
            self.left_card, 
            text="THIS DESK (YOUR PERMANENT ID)", 
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#a1a1aa"
        )
        self.lbl_this_desk.pack(anchor="w", padx=20, pady=(15, 3))

        self.lbl_desk_sub = ctk.CTkLabel(
            self.left_card, 
            text="Share this number to let others connect to this PC.", 
            font=ctk.CTkFont(size=11),
            text_color="#71717a"
        )
        self.lbl_desk_sub.pack(anchor="w", padx=20, pady=(0, 8))

        # ID Display Box
        self.id_box = ctk.CTkFrame(self.left_card, fg_color="#27272a", corner_radius=8)
        self.id_box.pack(fill="x", padx=20, pady=5)

        self.lbl_my_id = ctk.CTkLabel(
            self.id_box, 
            text=format_id(self.my_id), 
            font=ctk.CTkFont(size=26, weight="bold"),
            text_color="#38bdf8"
        )
        self.lbl_my_id.pack(pady=(10, 4))

        self.btn_copy_id = ctk.CTkButton(
            self.id_box, 
            text="📋 Copy ID", 
            width=100, 
            height=28,
            fg_color="#3f3f46",
            hover_color="#52525b",
            command=self.copy_id_to_clipboard
        )
        self.btn_copy_id.pack(pady=(0, 10))

        # Security PIN Section
        self.lbl_pin_title = ctk.CTkLabel(
            self.left_card, 
            text="Unattended Access PIN (Optional):", 
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#e4e4e7"
        )
        self.lbl_pin_title.pack(anchor="w", padx=20, pady=(12, 3))

        self.pin_row = ctk.CTkFrame(self.left_card, fg_color="transparent")
        self.pin_row.pack(fill="x", padx=20, pady=3)

        self.entry_my_pin = ctk.CTkEntry(
            self.pin_row, 
            width=140, 
            font=ctk.CTkFont(size=14, weight="bold")
        )
        self.entry_my_pin.insert(0, self.my_pin)
        self.entry_my_pin.pack(side="left")

        self.btn_save_pin = ctk.CTkButton(
            self.pin_row, 
            text="Save PIN", 
            width=90, 
            command=self.save_my_pin
        )
        self.btn_save_pin.pack(side="left", padx=10)

        self.lbl_access_note = ctk.CTkLabel(
            self.left_card, 
            text="💡 If a caller doesn't know your PIN, you will see\nan 'Accept / Reject' popup on this screen.", 
            font=ctk.CTkFont(size=11),
            text_color="#71717a",
            justify="left"
        )
        self.lbl_access_note.pack(anchor="w", padx=20, pady=(8, 0))

        # RIGHT CARD: Remote Device (Controller)
        self.right_card = ctk.CTkFrame(self.content_frame, width=380, corner_radius=12, fg_color="#202024")
        self.right_card.pack(side="right", fill="both", expand=True, padx=(10, 0))

        self.lbl_remote_desk = ctk.CTkLabel(
            self.right_card, 
            text="REMOTE DESK", 
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#a1a1aa"
        )
        self.lbl_remote_desk.pack(anchor="w", padx=20, pady=(15, 3))

        self.lbl_remote_sub = ctk.CTkLabel(
            self.right_card, 
            text="Enter remote 9-digit ID to control another PC.", 
            font=ctk.CTkFont(size=11),
            text_color="#71717a"
        )
        self.lbl_remote_sub.pack(anchor="w", padx=20, pady=(0, 8))

        # Remote ID Input + Online/Offline Badge
        self.lbl_remote_id_title = ctk.CTkLabel(
            self.right_card, 
            text="Remote ID:", 
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#e4e4e7"
        )
        self.lbl_remote_id_title.pack(anchor="w", padx=20, pady=(5, 3))

        self.remote_id_row = ctk.CTkFrame(self.right_card, fg_color="transparent")
        self.remote_id_row.pack(fill="x", padx=20, pady=3)

        self.entry_remote_id = ctk.CTkEntry(
            self.remote_id_row, 
            placeholder_text="e.g. 524 819 023",
            font=ctk.CTkFont(size=14, weight="bold"),
            width=200
        )
        self.entry_remote_id.pack(side="left")
        self.entry_remote_id.bind("<KeyRelease>", self._on_remote_id_typed)

        self.lbl_remote_status = ctk.CTkLabel(
            self.remote_id_row, 
            text="⚪ Checking", 
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#a1a1aa"
        )
        self.lbl_remote_status.pack(side="left", padx=10)

        # Remote PIN Input (Optional if unattended access)
        self.lbl_remote_pin_title = ctk.CTkLabel(
            self.right_card, 
            text="Remote Security PIN (Optional - or request access):", 
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#e4e4e7"
        )
        self.lbl_remote_pin_title.pack(anchor="w", padx=20, pady=(12, 3))

        self.entry_remote_pin = ctk.CTkEntry(
            self.right_card, 
            show="*", 
            placeholder_text="Enter PIN (Leave blank to prompt host)",
            font=ctk.CTkFont(size=13),
            width=260
        )
        self.entry_remote_pin.pack(anchor="w", padx=20, pady=3)

        # Connect Button
        self.btn_connect = ctk.CTkButton(
            self.right_card, 
            text="🔗 Connect", 
            height=40,
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color="#ef4444",
            hover_color="#dc2626",
            command=self.request_connection
        )
        self.btn_connect.pack(fill="x", padx=20, pady=(20, 5))

        self.lbl_connect_status = ctk.CTkLabel(
            self.right_card, 
            text="", 
            font=ctk.CTkFont(size=12),
            text_color="#a1a1aa"
        )
        self.lbl_connect_status.pack(padx=20)

        # 3. Bottom Settings & Background Bar
        self.footer_frame = ctk.CTkFrame(self, height=45, corner_radius=0, fg_color="#18181b")
        self.footer_frame.pack(fill="x", side="bottom")

        self.btn_bg = ctk.CTkButton(
            self.footer_frame, 
            text="🗕 Run in Background", 
            width=140, 
            height=28,
            fg_color="#27272a",
            hover_color="#3f3f46",
            font=ctk.CTkFont(size=11),
            command=self.minimize_to_background
        )
        self.btn_bg.pack(side="left", padx=15, pady=8)

        self.lbl_srv = ctk.CTkLabel(
            self.footer_frame, 
            text="Server:", 
            font=ctk.CTkFont(size=11),
            text_color="#a1a1aa"
        )
        self.lbl_srv.pack(side="left", padx=(10, 5), pady=8)

        self.entry_server_url = ctk.CTkEntry(
            self.footer_frame, 
            width=270, 
            height=26, 
            font=ctk.CTkFont(size=11)
        )
        self.entry_server_url.insert(0, self.server_url)
        self.entry_server_url.pack(side="left", padx=5, pady=8)

        self.btn_reconnect = ctk.CTkButton(
            self.footer_frame, 
            text="Reconnect", 
            width=80, 
            height=26,
            font=ctk.CTkFont(size=11),
            command=self.update_server_url
        )
        self.btn_reconnect.pack(side="left", padx=5, pady=8)

        self.btn_exit = ctk.CTkButton(
            self.footer_frame, 
            text="Quit App", 
            width=70, 
            height=26,
            fg_color="#7f1d1d",
            hover_color="#991b1b",
            font=ctk.CTkFont(size=11),
            command=self.quit_app
        )
        self.btn_exit.pack(side="right", padx=15, pady=8)

    # ------------------ Action Handlers ------------------

    def copy_id_to_clipboard(self):
        self.clipboard_clear()
        self.clipboard_append(self.my_id)
        self.btn_copy_id.configure(text="✅ Copied!")
        self.after(1500, lambda: self.btn_copy_id.configure(text="📋 Copy ID"))

    def save_my_pin(self):
        new_pin = self.entry_my_pin.get().strip()
        self.my_pin = new_pin
        self.config["pin"] = new_pin
        save_config(self.config)
        
        if self.websocket:
            self._send_json({"type": "update_pin", "pin": new_pin})
        messagebox.showinfo("Success", "Security PIN saved successfully!")

    def update_server_url(self):
        new_url = self.entry_server_url.get().strip()
        if new_url:
            self.server_url = new_url
            self.config["server_url"] = new_url
            save_config(self.config)
            self.connect_to_server()

    def minimize_to_background(self):
        self.withdraw()  # Hide window into background
        # Create a notification popup or console log
        logger.info("AnyDesk Clone is running in the background. Connections will be accepted.")

    def restore_from_background(self):
        self.deiconify()
        self.lift()
        self.focus_force()

    def quit_app(self):
        self._disconnect_session()
        self.destroy()
        sys.exit(0)

    def on_app_close(self):
        # Instead of suddenly terminating, ask user or minimize to background
        res = messagebox.askyesnocancel(
            "Close AnyDesk Clone",
            "Do you want to keep running in the background to accept remote connections?\n\n"
            "• Yes: Keep running in background\n"
            "• No: Completely exit the app\n"
            "• Cancel: Do nothing"
        )
        if res is True:
            self.minimize_to_background()
        elif res is False:
            self.quit_app()

    def _on_remote_id_typed(self, event=None):
        raw = self.entry_remote_id.get().replace(" ", "").strip()
        if len(raw) >= 6:
            self.check_remote_status(raw)
        else:
            self.lbl_remote_status.configure(text="⚪ Incomplete", text_color="#a1a1aa")

    def _periodic_presence_check(self):
        raw = self.entry_remote_id.get().replace(" ", "").strip()
        if len(raw) == 9:
            self.check_remote_status(raw)
        self.after(3000, self._periodic_presence_check)

    # ------------------ Networking ------------------

    def connect_to_server(self):
        asyncio.run_coroutine_threadsafe(self._async_connect(), self.loop)

    async def _async_connect(self):
        try:
            if self.websocket:
                await self.websocket.close()
        except Exception:
            pass

        self._set_server_status("🟡 Connecting...", "#eab308")
        try:
            self.websocket = await websockets.connect(
                self.server_url,
                max_size=10 * 1024 * 1024,
                ping_interval=15,
                ping_timeout=30
            )
            # Register local ID and PIN
            await self.websocket.send(json.dumps({
                "type": "register",
                "id": self.my_id,
                "pin": self.my_pin
            }))
            # Start message listener and dedicated fast frame sender
            asyncio.create_task(self._listen_server_messages())
            asyncio.create_task(self._stream_sender_worker())
        except Exception as e:
            logger.error(f"Failed to connect to server: {e}")
            self._set_server_status("🔴 Server Offline", "#ef4444")
            await asyncio.sleep(4)
            asyncio.create_task(self._async_connect())

    async def _stream_sender_worker(self):
        """Dedicated high-speed loop: always transmits the latest frame with zero queue delay"""
        while self.websocket and not self.websocket.closed:
            await self.frame_send_event.wait()
            self.frame_send_event.clear()
            frame = self.latest_frame_to_send
            if frame:
                try:
                    await self.websocket.send(frame)
                except Exception as e:
                    logger.error(f"Error sending frame: {e}")
                    break

    async def _listen_server_messages(self):
        try:
            async for message in self.websocket:
                # 1. Binary message (Incoming video frame)
                if isinstance(message, bytes):
                    if self.viewer_window:
                        self.after(0, self.viewer_window.update_frame, message)
                    continue

                # 2. JSON control messages
                data = json.loads(message)
                msg_type = data.get("type")

                if msg_type == "registered":
                    self._set_server_status("🟢 Server Ready", "#22c55e")
                    raw = self.entry_remote_id.get().replace(" ", "").strip()
                    if len(raw) == 9:
                        self.check_remote_status(raw)

                elif msg_type == "status_response":
                    target_id = data.get("target_id")
                    is_online = data.get("online", False)
                    current_entered = self.entry_remote_id.get().replace(" ", "").strip()
                    if target_id == current_entered:
                        if is_online:
                            self._set_remote_status("🟢 Online", "#22c55e")
                        else:
                            self._set_remote_status("🔴 Offline", "#ef4444")

                elif msg_type == "connect_response":
                    status = data.get("status")
                    if status == "success":
                        target_id = data.get("target_id")
                        self.after(0, self._open_viewer, target_id)
                    elif status == "pending_approval":
                        msg = data.get("message", "Waiting for remote user to accept...")
                        self.lbl_connect_status.configure(text=msg, text_color="#f59e0b")
                    else:
                        err_msg = data.get("message", "Connection failed.")
                        self.after(0, self._show_connect_error, err_msg)

                # Incoming connection request prompt for the Host PC
                elif msg_type == "incoming_prompt":
                    from_id = data.get("from_id")
                    self.after(0, self._show_incoming_prompt, from_id)

                elif msg_type == "start_streaming":
                    controller_id = data.get("controller_id")
                    logger.info(f"Host received start_streaming for controller {controller_id}")
                    self.after(0, self._start_host_streaming)

                elif msg_type == "mouse_event":
                    action = data.get("action")
                    x = data.get("x", 0)
                    y = data.get("y", 0)
                    btn = data.get("button", 1)
                    delta = data.get("delta", 0)
                    self.input_handler.handle_mouse(action, x, y, button=btn, delta=delta)

                elif msg_type == "key_event":
                    action = data.get("action")
                    key = data.get("key", "")
                    char = data.get("char", "")
                    self.input_handler.handle_keyboard(action, key, char=char)

                elif msg_type == "session_ended":
                    logger.info("Session ended notification received.")
                    self.after(0, self._handle_session_ended)

        except websockets.exceptions.ConnectionClosed:
            logger.info("Server connection closed. Auto-reconnecting in 3s...")
            self._set_server_status("🟡 Reconnecting...", "#eab308")
            await asyncio.sleep(3)
            asyncio.create_task(self._async_connect())
        except Exception as e:
            logger.error(f"Error in server listener: {e}")
            self._set_server_status("🔴 Server Error", "#ef4444")
            await asyncio.sleep(4)
            asyncio.create_task(self._async_connect())

    def _show_incoming_prompt(self, from_id):
        # Bring window to front if in background
        self.restore_from_background()

        # AnyDesk-style Accept / Reject prompt dialog
        prompt_win = ctk.CTkToplevel(self)
        prompt_win.title("Incoming Connection Request")
        prompt_win.geometry("420x220")
        prompt_win.resizable(False, False)
        prompt_win.attributes("-topmost", True)

        lbl = ctk.CTkLabel(
            prompt_win,
            text=f"🔔 Incoming Connection Request\n\nDevice ID {format_id(from_id)} wants to control this PC.\nDo you allow this session?",
            font=ctk.CTkFont(size=13, weight="bold"),
            justify="center"
        )
        lbl.pack(pady=(25, 20), padx=20)

        btn_row = ctk.CTkFrame(prompt_win, fg_color="transparent")
        btn_row.pack(fill="x", padx=40, pady=10)

        def on_accept():
            self._send_json({"type": "accept_prompt", "from_id": from_id})
            prompt_win.destroy()

        def on_reject():
            self._send_json({"type": "reject_prompt", "from_id": from_id})
            prompt_win.destroy()

        btn_accept = ctk.CTkButton(
            btn_row, 
            text="✔ Accept", 
            fg_color="#16a34a", 
            hover_color="#15803d",
            font=ctk.CTkFont(size=14, weight="bold"),
            width=150,
            height=38,
            command=on_accept
        )
        btn_accept.pack(side="left", padx=10)

        btn_reject = ctk.CTkButton(
            btn_row, 
            text="✖ Reject", 
            fg_color="#dc2626", 
            hover_color="#b91c1c",
            font=ctk.CTkFont(size=14, weight="bold"),
            width=150,
            height=38,
            command=on_reject
        )
        btn_reject.pack(side="right", padx=10)

    def _set_server_status(self, text, color):
        self.after(0, lambda: self.server_status_badge.configure(text=text, text_color=color))

    def _set_remote_status(self, text, color):
        self.after(0, lambda: self.lbl_remote_status.configure(text=text, text_color=color))

    def check_remote_status(self, target_id):
        self._send_json({
            "type": "check_status",
            "target_id": target_id
        })

    def request_connection(self):
        target_id = self.entry_remote_id.get().replace(" ", "").strip()
        pin = self.entry_remote_pin.get().strip()

        if not target_id:
            messagebox.showwarning("Input Error", "Please enter a Remote Device ID.")
            return

        if target_id == self.my_id:
            messagebox.showwarning("Notice", "You cannot connect to your own ID.")
            return

        self.lbl_connect_status.configure(text="Requesting connection...", text_color="#38bdf8")
        self.btn_connect.configure(state="disabled")

        self._send_json({
            "type": "connect_request",
            "target_id": target_id,
            "pin": pin
        })

    def _open_viewer(self, target_id):
        self.btn_connect.configure(state="normal")
        self.lbl_connect_status.configure(text="Connected!", text_color="#22c55e")

        if self.viewer_window is None or not self.viewer_window.winfo_exists():
            self.viewer_window = RemoteViewerWindow(
                self, 
                target_id, 
                send_cmd_callback=self._send_json, 
                disconnect_callback=self._disconnect_session
            )
        else:
            self.viewer_window.focus()

    def _show_connect_error(self, message):
        self.btn_connect.configure(state="normal")
        self.lbl_connect_status.configure(text=message, text_color="#ef4444")
        messagebox.showerror("Connection Notice", message)

    def _start_host_streaming(self):
        if self.streamer is None or not self.streamer.is_running:
            self.streamer = ScreenStreamer(
                send_callback=self._push_new_frame,
                quality=self.config.get("quality", 55),
                fps_limit=self.config.get("fps_limit", 25),
                scale=self.config.get("scale", 0.75)
            )
            self.streamer.start()

    def _push_new_frame(self, binary_data):
        """Called by streamer thread: replaces latest frame and notifies sender loop"""
        self.latest_frame_to_send = binary_data
        self.loop.call_soon_threadsafe(self.frame_send_event.set)

    def _disconnect_session(self):
        logger.info("Disconnecting session...")
        self._send_json({"type": "end_session"})
        self._handle_session_ended()

    def _handle_session_ended(self):
        if self.streamer:
            self.streamer.stop()
            self.streamer = None
        if self.viewer_window and self.viewer_window.winfo_exists():
            self.viewer_window.destroy()
            self.viewer_window = None
        self.btn_connect.configure(state="normal")
        self.lbl_connect_status.configure(text="Session Disconnected", text_color="#a1a1aa")

    def _send_json(self, payload):
        if self.websocket:
            asyncio.run_coroutine_threadsafe(
                self.websocket.send(json.dumps(payload)), 
                self.loop
            )

if __name__ == "__main__":
    app = AnyDeskCloneApp()
    app.mainloop()
