import ctypes
import logging

logger = logging.getLogger("InputHandler")
user32 = ctypes.windll.user32

# Mouse flags
MOUSEEVENTF_MOVE       = 0x0001
MOUSEEVENTF_LEFTDOWN   = 0x0002
MOUSEEVENTF_LEFTUP     = 0x0004
MOUSEEVENTF_RIGHTDOWN  = 0x0008
MOUSEEVENTF_RIGHTUP    = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP   = 0x0040
MOUSEEVENTF_WHEEL      = 0x0800

# Key flags
KEYEVENTF_KEYUP        = 0x0002
KEYEVENTF_EXTENDEDKEY  = 0x0001

# Virtual Key mapping for special keys
SPECIAL_KEYS = {
    "Return": 0x0D,
    "BackSpace": 0x08,
    "Tab": 0x09,
    "Escape": 0x1B,
    "space": 0x20,
    "Delete": 0x2E,
    "Up": 0x26,
    "Down": 0x28,
    "Left": 0x25,
    "Right": 0x27,
    "Home": 0x24,
    "End": 0x23,
    "Prior": 0x21, # Page Up
    "Next": 0x22,  # Page Down
    "Shift_L": 0xA0,
    "Shift_R": 0xA1,
    "Control_L": 0xA2,
    "Control_R": 0xA3,
    "Alt_L": 0x12,
    "Alt_R": 0x12,
    "Caps_Lock": 0x14,
    "F1": 0x70, "F2": 0x71, "F3": 0x72, "F4": 0x73,
    "F5": 0x74, "F6": 0x75, "F7": 0x76, "F8": 0x77,
    "F9": 0x78, "F10": 0x79, "F11": 0x7A, "F12": 0x7B
}

class WindowsInputHandler:
    def __init__(self):
        self.screen_width = user32.GetSystemMetrics(0)
        self.screen_height = user32.GetSystemMetrics(1)
        logger.info(f"Input handler initialized for screen: {self.screen_width}x{self.screen_height}")

    def refresh_screen_metrics(self):
        self.screen_width = user32.GetSystemMetrics(0)
        self.screen_height = user32.GetSystemMetrics(1)

    def handle_mouse(self, action, x_ratio, y_ratio, button=1, delta=0):
        # Convert ratio (0.0 to 1.0) into actual pixel coordinates
        x = int(x_ratio * self.screen_width)
        y = int(y_ratio * self.screen_height)

        if action == "move":
            user32.SetCursorPos(x, y)
        elif action == "down":
            user32.SetCursorPos(x, y)
            if button == 1:
                user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
            elif button == 3:
                user32.mouse_event(MOUSEEVENTF_RIGHTDOWN, 0, 0, 0, 0)
            elif button == 2:
                user32.mouse_event(MOUSEEVENTF_MIDDLEDOWN, 0, 0, 0, 0)
        elif action == "up":
            user32.SetCursorPos(x, y)
            if button == 1:
                user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
            elif button == 3:
                user32.mouse_event(MOUSEEVENTF_RIGHTUP, 0, 0, 0, 0)
            elif button == 2:
                user32.mouse_event(MOUSEEVENTF_MIDDLEUP, 0, 0, 0, 0)
        elif action == "scroll":
            # delta in Windows mouse_event is typically 120 per notch
            wheel_delta = int(delta * 120)
            user32.mouse_event(MOUSEEVENTF_WHEEL, 0, 0, wheel_delta, 0)

    def handle_keyboard(self, action, key_name, char=""):
        vk_code = 0
        if key_name in SPECIAL_KEYS:
            vk_code = SPECIAL_KEYS[key_name]
        elif char and len(char) == 1:
            scan = user32.VkKeyScanW(ord(char))
            if scan != -1:
                vk_code = scan & 0xFF

        if vk_code > 0:
            if action == "down":
                user32.keybd_event(vk_code, 0, 0, 0)
            elif action == "up":
                user32.keybd_event(vk_code, 0, KEYEVENTF_KEYUP, 0)
