import asyncio
import json
import time
import logging
import threading
import concurrent.futures
import ctypes
from ctypes import c_void_p, c_int, c_uint, windll
import cv2
import numpy as np
import mss
from PIL import ImageGrab
import av

from aiortc import (
    RTCPeerConnection, 
    RTCConfiguration, 
    RTCIceServer, 
    RTCSessionDescription,
    RTCIceCandidate,
    VideoStreamTrack
)

logger = logging.getLogger("WebRTCManager")

# Free Google STUN servers for NAT Traversal (UDP Hole-Punching)
STUN_SERVERS = [
    RTCIceServer(urls="stun:stun.l.google.com:19302"),
    RTCIceServer(urls="stun:stun1.l.google.com:19302"),
    RTCIceServer(urls="stun:stun2.l.google.com:19302"),
    RTCIceServer(urls="stun:stun3.l.google.com:19302"),
    RTCIceServer(urls="stun:stun4.l.google.com:19302"),
]

class ScreenVideoTrack(VideoStreamTrack):
    """
    Captures desktop frames in a DEDICATED THREAD (non-blocking) and feeds
    them into the WebRTC H.264/VP8 encoder. The asyncio event loop is NEVER
    blocked — ICE negotiation and signaling run freely alongside capture.
    """
    def __init__(self, fps=30, scale=0.75):
        super().__init__()
        self.fps = fps
        self.scale = scale
        # Dedicated single-thread executor for screen capture
        # (MSS is not thread-safe across multiple threads, one dedicated is safest)
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        self._thread_ready = False   # True after first capture init succeeds
        self._sct = None
        self._monitor = None

    def _init_thread(self):
        """
        Called INSIDE the executor thread on first use.
        Desktop attachment + MSS init must happen on the SAME thread that does grabbing.
        """
        if self._thread_ready:
            return
        try:
            u32 = windll.user32
            u32.OpenInputDesktop.argtypes = [c_uint, c_int, c_uint]
            u32.OpenInputDesktop.restype = c_void_p
            u32.SetThreadDesktop.argtypes = [c_void_p]
            u32.SetThreadDesktop.restype = c_int
            desk = u32.OpenInputDesktop(0, 0, 0x01FF)
            if desk:
                u32.SetThreadDesktop(desk)
                logger.info("ScreenCapture: Desktop attached successfully")
        except Exception as e:
            logger.warning(f"ScreenCapture: Desktop attach skipped: {e}")
        try:
            self._sct = mss.MSS()
            self._monitor = self._sct.monitors[1]
            logger.info(f"ScreenCapture: MSS ready. Monitor: {self._monitor}")
        except Exception as e:
            logger.warning(f"ScreenCapture: MSS init failed, will use PIL: {e}")
        self._thread_ready = True

    def _capture_sync(self):
        """
        Runs SYNCHRONOUSLY in the executor thread.
        Returns a BGR numpy array — ready to encode.
        """
        self._init_thread()

        frame = None

        # Primary: MSS (fastest on Windows)
        if self._sct and self._monitor:
            try:
                raw = self._sct.grab(self._monitor)
                bgra = np.array(raw, dtype=np.uint8)
                frame = cv2.cvtColor(bgra, cv2.COLOR_BGRA2BGR)
            except Exception as e:
                logger.warning(f"MSS grab error: {e} — switching to PIL")
                self._sct = None   # Force PIL fallback permanently

        # Fallback: PIL ImageGrab
        if frame is None:
            try:
                pil_img = ImageGrab.grab()
                rgb = np.array(pil_img, dtype=np.uint8)
                frame = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
            except Exception as e:
                logger.error(f"PIL grab error: {e}")
                frame = np.zeros((720, 1280, 3), dtype=np.uint8)

        # Scale down for bandwidth / latency improvement
        if self.scale != 1.0 and frame is not None:
            w = int(frame.shape[1] * self.scale)
            h = int(frame.shape[0] * self.scale)
            frame = cv2.resize(frame, (w, h), interpolation=cv2.INTER_LINEAR)

        return frame

    async def recv(self):
        """
        Async recv — the asyncio event loop is NEVER blocked.
        Screen capture runs in the executor thread, result awaited cleanly.
        """
        pts, time_base = await self.next_timestamp()

        # Run blocking capture off the event loop
        loop = asyncio.get_event_loop()
        frame = await loop.run_in_executor(self._executor, self._capture_sync)

        video_frame = av.VideoFrame.from_ndarray(frame, format="bgr24")
        video_frame.pts = pts
        video_frame.time_base = time_base
        return video_frame


class WebRTCManager:
    def __init__(self, send_signaling_callback, input_handler=None, frame_callback=None):
        self.send_signaling = send_signaling_callback
        self.input_handler = input_handler
        self.frame_callback = frame_callback
        self.pc = None
        self.data_channel = None
        self.is_host = False
        self.target_id = None

    def _create_pc(self):
        config = RTCConfiguration(iceServers=STUN_SERVERS)
        pc = RTCPeerConnection(configuration=config)

        @pc.on("icecandidate")
        def on_ice_candidate(candidate):
            if candidate and self.target_id:
                self.send_signaling({
                    "type": "webrtc_candidate",
                    "target_id": self.target_id,
                    "candidate": {
                        "candidate": candidate.candidate,
                        "sdpMid": candidate.sdpMid,
                        "sdpMLineIndex": candidate.sdpMLineIndex
                    }
                })

        @pc.on("connectionstatechange")
        async def on_connection_state_change():
            state = pc.connectionState
            logger.info(f"WebRTC Connection State → {state}")
            if state == "failed":
                logger.error("WebRTC P2P failed. Check NAT/firewall. Closing.")
                await self.close()

        @pc.on("icegatheringstatechange")
        def on_ice_gathering():
            logger.info(f"ICE Gathering → {pc.iceGatheringState}")

        @pc.on("iceconnectionstatechange")
        def on_ice_connection():
            logger.info(f"ICE Connection → {pc.iceConnectionState}")

        return pc

    # ----------------- CONTROLLER METHODS -----------------

    async def start_controller_session(self, target_id):
        """Controller creates the Offer and initializes direct P2P data channel"""
        self.target_id = target_id
        self.is_host = False
        self.pc = self._create_pc()

        # Create Direct P2P UDP DataChannel for mouse/keyboard — ordered=False, maxRetransmits=0
        # gives UDP-like semantics: each input command sent immediately, never queued
        self.data_channel = self.pc.createDataChannel(
            "input", ordered=False, maxRetransmits=0
        )

        @self.data_channel.on("open")
        def on_channel_open():
            logger.info("🟢 Direct P2P DataChannel OPEN — ultra-low latency inputs active!")

        # Listen for remote video track from host
        @self.pc.on("track")
        def on_track(track):
            logger.info(f"🎥 Received remote video track: {track.kind}")
            if track.kind == "video":
                asyncio.ensure_future(self._receive_video_stream(track))

        # Create offer — aiortc gathers ALL ICE candidates during setLocalDescription
        # (complete ICE, not trickle), so the SDP already contains full routing info
        offer = await self.pc.createOffer()
        await self.pc.setLocalDescription(offer)
        logger.info(f"ICE gathering complete. Sending offer to {target_id}")

        self.send_signaling({
            "type": "webrtc_offer",
            "target_id": target_id,
            "sdp": self.pc.localDescription.sdp
        })
        logger.info(f"WebRTC Offer sent to target {target_id}")

    async def _receive_video_stream(self, track):
        """Continuously decodes raw P2P video frames — runs fully async, never blocks"""
        logger.info("Video stream receiver started")
        frame_count = 0
        t0 = time.time()
        while True:
            try:
                if self.pc is None or self.pc.connectionState in ("closed", "failed"):
                    break
                frame = await asyncio.wait_for(track.recv(), timeout=5.0)
                img_bgr = frame.to_ndarray(format="bgr24")
                if self.frame_callback:
                    self.frame_callback(img_bgr)
                frame_count += 1
                elapsed = time.time() - t0
                if elapsed >= 5.0:
                    logger.info(f"P2P video: {frame_count / elapsed:.1f} FPS")
                    frame_count = 0
                    t0 = time.time()
            except asyncio.TimeoutError:
                logger.warning("Video frame timeout — still waiting for P2P frames...")
                continue
            except Exception as e:
                logger.error(f"Video stream error: {e}")
                break
        logger.info("Video stream receiver stopped")

    def send_input_command(self, cmd_dict):
        """Sends mouse/keyboard command through direct P2P data channel (UDP-like)"""
        if self.data_channel and self.data_channel.readyState == "open":
            try:
                self.data_channel.send(json.dumps(cmd_dict))
                return True
            except Exception:
                pass
        return False

    # ----------------- HOST METHODS -----------------

    async def handle_webrtc_offer(self, from_id, sdp_text):
        """Host receives the Offer, adds the Screen Video Track, and returns Answer"""
        self.target_id = from_id
        self.is_host = True
        self.pc = self._create_pc()

        # Add screen capture track — ScreenVideoTrack uses a thread executor,
        # so the asyncio loop stays free during capture
        screen_track = ScreenVideoTrack(fps=30, scale=0.75)
        self.pc.addTrack(screen_track)
        logger.info("ScreenVideoTrack added to WebRTC peer connection")

        # Listen for direct P2P data channel from controller
        @self.pc.on("datachannel")
        def on_datachannel(channel):
            self.data_channel = channel
            logger.info("🟢 Host accepted P2P DataChannel — inputs will arrive here")

            @channel.on("message")
            def on_message(message):
                if self.input_handler:
                    try:
                        cmd = json.loads(message)
                        mtype = cmd.get("type")
                        if mtype == "mouse_event":
                            self.input_handler.handle_mouse(
                                cmd.get("action"),
                                cmd.get("x", 0),
                                cmd.get("y", 0),
                                button=cmd.get("button", 1),
                                delta=cmd.get("delta", 0)
                            )
                        elif mtype == "key_event":
                            self.input_handler.handle_keyboard(
                                cmd.get("action"),
                                cmd.get("key", ""),
                                char=cmd.get("char", "")
                            )
                    except Exception as e:
                        logger.error(f"Input handler error: {e}")

        # Set remote offer and create answer
        offer_desc = RTCSessionDescription(sdp=sdp_text, type="offer")
        await self.pc.setRemoteDescription(offer_desc)

        answer = await self.pc.createAnswer()
        await self.pc.setLocalDescription(answer)
        logger.info("ICE gathering complete on host. Sending answer.")

        self.send_signaling({
            "type": "webrtc_answer",
            "target_id": from_id,
            "sdp": self.pc.localDescription.sdp
        })
        logger.info(f"WebRTC Answer sent back to controller {from_id}")

    async def handle_webrtc_answer(self, sdp_text):
        """Controller receives Answer from Host and finalizes P2P connection"""
        if self.pc:
            answer_desc = RTCSessionDescription(sdp=sdp_text, type="answer")
            await self.pc.setRemoteDescription(answer_desc)
            logger.info("WebRTC Answer applied — P2P tunnel negotiating...")

    async def handle_ice_candidate(self, candidate_dict):
        """Adds incoming ICE candidate for STUN hole punching (trickle ICE)"""
        if self.pc:
            try:
                candidate = RTCIceCandidate(
                    candidate=candidate_dict["candidate"],
                    sdpMid=candidate_dict.get("sdpMid"),
                    sdpMLineIndex=candidate_dict.get("sdpMLineIndex")
                )
                await self.pc.addIceCandidate(candidate)
            except Exception as e:
                logger.warning(f"ICE candidate add: {e}")

    async def close(self):
        if self.data_channel:
            try:
                self.data_channel.close()
            except Exception:
                pass
            self.data_channel = None
        if self.pc:
            try:
                await self.pc.close()
            except Exception:
                pass
            self.pc = None
        logger.info("WebRTC peer connection closed")
