import asyncio
import json
import time
import logging
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
    """Captures desktop frames and feeds them into the WebRTC H.264/VP8 video encoder"""
    def __init__(self, fps=30, scale=0.85):
        super().__init__()
        self.fps = fps
        self.scale = scale
        self.sct = None
        self.monitor = None

        # 64-bit Windows Desktop Station attachment
        try:
            u32 = windll.user32
            u32.OpenInputDesktop.argtypes = [c_uint, c_int, c_uint]
            u32.OpenInputDesktop.restype = c_void_p
            u32.SetThreadDesktop.argtypes = [c_void_p]
            u32.SetThreadDesktop.restype = c_int

            desk = u32.OpenInputDesktop(0, 0, 0x01FF)
            if desk:
                u32.SetThreadDesktop(desk)
        except Exception as e:
            logger.warning(f"Desktop attachment warning: {e}")

        try:
            self.sct = mss.MSS()
            self.monitor = self.sct.monitors[1]
        except Exception:
            pass

    async def recv(self):
        pts, time_base = await self.next_timestamp()
        frame = None

        # Primary capture: MSS
        if self.sct and self.monitor:
            try:
                raw = self.sct.grab(self.monitor)
                frame_bgra = np.array(raw, dtype=np.uint8)
                frame = cv2.cvtColor(frame_bgra, cv2.COLOR_BGRA2BGR)
            except Exception:
                pass

        # Fallback capture: PIL ImageGrab
        if frame is None:
            try:
                pil_img = ImageGrab.grab()
                frame_rgb = np.array(pil_img, dtype=np.uint8)
                frame = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)
            except Exception as e:
                logger.error(f"Fallback grab error: {e}")
                frame = np.zeros((720, 1280, 3), dtype=np.uint8)

        # Scale down slightly for silky 30-60 FPS
        if self.scale != 1.0:
            w = int(frame.shape[1] * self.scale)
            h = int(frame.shape[0] * self.scale)
            frame = cv2.resize(frame, (w, h), interpolation=cv2.INTER_LINEAR)

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
            logger.info(f"WebRTC Connection State: {pc.connectionState}")
            if pc.connectionState == "failed":
                await self.close()

        return pc

    # ----------------- CONTROLLER METHODS -----------------

    async def start_controller_session(self, target_id):
        """Controller creates the Offer and initializes direct P2P data channel"""
        self.target_id = target_id
        self.is_host = False
        self.pc = self._create_pc()

        # Create Direct P2P UDP DataChannel for mouse and keyboard commands
        self.data_channel = self.pc.createDataChannel("input", ordered=False, maxRetransmits=0)
        
        @self.data_channel.on("open")
        def on_channel_open():
            logger.info("Direct P2P DataChannel OPEN! Ultra-low latency inputs enabled.")

        # Listen for remote video track
        @self.pc.on("track")
        def on_track(track):
            logger.info(f"Received remote track: {track.kind}")
            if track.kind == "video":
                asyncio.create_task(self._receive_video_stream(track))

        # Create and send Offer
        offer = await self.pc.createOffer()
        await self.pc.setLocalDescription(offer)

        self.send_signaling({
            "type": "webrtc_offer",
            "target_id": target_id,
            "sdp": self.pc.localDescription.sdp
        })
        logger.info(f"Sent WebRTC Offer to target {target_id}")

    async def _receive_video_stream(self, track):
        """Continuously decodes raw P2P video frames with sub-frame latency"""
        while self.pc and self.pc.connectionState not in ("closed", "failed"):
            try:
                frame = await track.recv()
                img_bgr = frame.to_ndarray(format="bgr24")
                if self.frame_callback:
                    self.frame_callback(img_bgr)
            except Exception as e:
                logger.error(f"Error receiving WebRTC frame: {e}")
                break

    def send_input_command(self, cmd_dict):
        """Sends mouse/keyboard command through direct P2P data channel"""
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

        # Add screen capture track
        screen_track = ScreenVideoTrack(fps=30, scale=0.85)
        self.pc.addTrack(screen_track)

        # Listen for direct P2P data channel
        @self.pc.on("datachannel")
        def on_datachannel(channel):
            self.data_channel = channel
            logger.info("Host accepted direct P2P DataChannel from Controller!")

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

        self.send_signaling({
            "type": "webrtc_answer",
            "target_id": from_id,
            "sdp": self.pc.localDescription.sdp
        })
        logger.info(f"Host sent WebRTC Answer back to {from_id}")

    async def handle_webrtc_answer(self, sdp_text):
        """Controller receives Answer from Host and finalizes P2P connection"""
        if self.pc:
            answer_desc = RTCSessionDescription(sdp=sdp_text, type="answer")
            await self.pc.setRemoteDescription(answer_desc)
            logger.info("WebRTC Answer applied. P2P Direct Tunnel established!")

    async def handle_ice_candidate(self, candidate_dict):
        """Adds incoming ICE candidate for STUN hole punching"""
        if self.pc:
            try:
                candidate = RTCIceCandidate(
                    candidate=candidate_dict["candidate"],
                    sdpMid=candidate_dict.get("sdpMid"),
                    sdpMLineIndex=candidate_dict.get("sdpMLineIndex")
                )
                await self.pc.addIceCandidate(candidate)
            except Exception as e:
                logger.warning(f"Error adding ICE candidate: {e}")

    async def close(self):
        if self.data_channel:
            self.data_channel.close()
            self.data_channel = None
        if self.pc:
            await self.pc.close()
            self.pc = None
