import collections
import math
import struct
import threading
import time
import numpy as np
import pygame
import serial
import random

# ==============================================================================
# SERIAL & EEG CONFIGURATION (ARDUINO UNO R3)
# ==============================================================================

PORT = "COM7"
BAUD_RATE = 115200

NUM_CHANNELS = 6
HEADER_LEN = 3
PACKET_LEN = NUM_CHANNELS * 2 + HEADER_LEN + 1

SYNC_BYTE_1 = 0xC7
SYNC_BYTE_2 = 0x7C
END_BYTE = 0x01

SAMP_RATE = 500.0

# Keep about 2 seconds of EEG
BUFFER_SIZE = int(SAMP_RATE * 2)
eeg_data_buffer = collections.deque(maxlen=BUFFER_SIZE)

serial_running = True

# This is the value used by the existing GUI.
current_focus_level = 50.0

# ------------------------------------------------------------------------------
# Focus-calibration variables
# ------------------------------------------------------------------------------

baseline_ratios = collections.deque(maxlen=8)
baseline_ratio = None

last_focus_update = 0
last_status_print = 0

# Number of seconds used to establish the user's resting EEG baseline.
CALIBRATION_SECONDS = 5.0

# ------------------------------------------------------------------------------
# EEG band-power helper
# ------------------------------------------------------------------------------

def calculate_bandpower(signal, fs, low_freq, high_freq):
    """
    Calculate average FFT power in a frequency band.
    This is a game-oriented EEG activity metric, not a clinical measurement.
    """

    signal = np.asarray(signal, dtype=float)

    if len(signal) < 256:
        return 0.0

    # Remove DC offset
    signal = signal - np.mean(signal)

    # Remove linear drift
    x = np.arange(len(signal), dtype=float)
    try:
        slope, intercept = np.polyfit(x, signal, 1)
        signal = signal - (slope * x + intercept)
    except Exception:
        pass

    # Hanning window reduces spectral leakage
    window = np.hanning(len(signal))
    windowed = signal * window

    # FFT
    spectrum = np.fft.rfft(windowed)
    frequencies = np.fft.rfftfreq(len(windowed), d=1.0 / fs)

    power = (np.abs(spectrum) ** 2) / np.sum(window ** 2)

    band = (frequencies >= low_freq) & (frequencies < high_freq)

    if not np.any(band):
        return 0.0

    return float(np.mean(power[band]))


def calculate_focus_score(samples):
    """
    Convert the current EEG spectrum into a smooth 0-100 game focus score.

    Bands:
        Theta: 4-8 Hz
        Alpha: 8-13 Hz
        Beta : 13-30 Hz

    Game metric:
        beta / (alpha + theta)

    The ratio is compared against a personal baseline established during
    the first few seconds of the recording.
    """

    global baseline_ratio

    samples = np.asarray(samples, dtype=float)

    if len(samples) < int(SAMP_RATE):
        return None

    # Use the most recent ~2 seconds
    samples = samples[-int(SAMP_RATE * 2):]

    theta = calculate_bandpower(
        samples, SAMP_RATE, 4.0, 8.0
    )

    alpha = calculate_bandpower(
        samples, SAMP_RATE, 8.0, 13.0
    )

    beta = calculate_bandpower(
        samples, SAMP_RATE, 13.0, 30.0
    )

    denominator = alpha + theta

    if denominator <= 1e-12:
        return None

    ratio = beta / denominator

    # Protect against numerical/noise spikes.
    ratio = float(np.clip(ratio, 0.001, 1000.0))

    # --------------------------------------------------------------------------
    # Calibration
    # --------------------------------------------------------------------------

    if baseline_ratio is None:

        baseline_ratios.append(ratio)

        if len(baseline_ratios) >= 5:
            baseline_ratio = float(np.median(baseline_ratios))

        return 50.0

    # --------------------------------------------------------------------------
    # Relative focus score
    # --------------------------------------------------------------------------

    relative_ratio = ratio / max(baseline_ratio, 1e-6)

    # Log-ratio makes increases/decreases behave more symmetrically.
    log_change = math.log(relative_ratio)

    # Convert to approximately 0-100.
    raw_focus = 50.0 + 28.0 * math.tanh(log_change * 1.8)

    return float(np.clip(raw_focus, 0.0, 100.0))


# ==============================================================================
# SERIAL STREAMING & EEG SIGNAL PROCESSING THREAD
# ==============================================================================

def read_eeg_serial():

    global serial_running
    global current_focus_level
    global last_focus_update
    global last_status_print

    try:

        ser = serial.Serial(
            PORT,
            BAUD_RATE,
            timeout=0.1
        )

        time.sleep(2)

        # Clear anything left in the serial buffer after UNO reset.
        ser.reset_input_buffer()

        # Keep your existing Arduino handshake.
        ser.write(b"START\n")

        print("================================")
        print("CONNECTED:", PORT)
        print("BAUD:", BAUD_RATE)
        print("EEG STREAM STARTED")
        print("5-second baseline calibration...")
        print("================================")

    except Exception as e:

        print("SERIAL ERROR:", e)
        return

    buffer = bytearray()
    packet_count = 0

    while serial_running:

        try:

            if ser.in_waiting > 0:

                incoming = ser.read(ser.in_waiting)
                buffer.extend(incoming)

                while len(buffer) >= PACKET_LEN:

                    # ----------------------------------------------------------
                    # Find packet header
                    # ----------------------------------------------------------

                    if (
                        buffer[0] == SYNC_BYTE_1
                        and buffer[1] == SYNC_BYTE_2
                    ):

                        # ------------------------------------------------------
                        # Check packet terminator
                        # ------------------------------------------------------

                        if buffer[PACKET_LEN - 1] == END_BYTE:

                            packet = bytes(buffer[:PACKET_LEN])
                            del buffer[:PACKET_LEN]

                            channels = []

                            for i in range(NUM_CHANNELS):

                                idx = HEADER_LEN + (i * 2)

                                raw_val = (
                                    (packet[idx] << 8)
                                    | packet[idx + 1]
                                )

                                channels.append(raw_val)

                            # Primary EEG channel = channel 0 / A0
                            eeg_data_buffer.append(channels[0])

                            packet_count += 1

                        else:

                            # Header was found but packet was invalid.
                            # Move forward one byte and resynchronize.
                            del buffer[0]

                    else:

                        # Search for the next possible header.
                        del buffer[0]

            # ------------------------------------------------------------------
            # EEG processing
            # ------------------------------------------------------------------

            if len(eeg_data_buffer) >= int(SAMP_RATE):

                samples = np.asarray(
                    eeg_data_buffer,
                    dtype=float
                )

                target_focus = calculate_focus_score(samples)

                if target_focus is not None:

                    # Smooth the focus value.
                    current_focus_level += (
                        target_focus - current_focus_level
                    ) * 0.08

                    current_focus_level = float(
                        np.clip(
                            current_focus_level,
                            0.0,
                            100.0
                        )
                    )

                    last_focus_update = time.time()

            # ------------------------------------------------------------------
            # Low-rate terminal status so the console doesn't get flooded.
            # ------------------------------------------------------------------

            if time.time() - last_status_print > 1.0:

                print(
                    "Packets:",
                    packet_count,
                    "| Samples:",
                    len(eeg_data_buffer),
                    "| Focus:",
                    round(current_focus_level, 1)
                )

                last_status_print = time.time()

            time.sleep(0.005)

        except Exception as e:

            print("PROCESSING ERROR:", e)
            break

    # Clean serial shutdown
    if "ser" in locals() and ser.is_open:

        try:
            ser.write(b"STOP\n")
        except Exception:
            pass

        try:
            ser.close()
        except Exception:
            pass


# ==============================================================================
# IMPORTANT: START THE EEG THREAD
# ==============================================================================

serial_thread = threading.Thread(
    target=read_eeg_serial,
    daemon=True
)

serial_thread.start()


# ==============================================================================
# PYGAME GRAPHICS & GAME LOOP
# ==============================================================================

pygame.init()

WIDTH, HEIGHT = 1280, 720
screen = pygame.display.set_mode((WIDTH, HEIGHT))
pygame.display.set_caption("🐸 Brain Frog - Focus Survival (UNO R3 EEG)")
clock = pygame.time.Clock()

SKY = (135, 206, 250)
GRASS = (90, 180, 75)
WATER = (70, 150, 255)
WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
GREEN = (70, 190, 70)
BELLY = (190, 255, 180)
YELLOW = (255, 220, 0)

font = pygame.font.SysFont("arial", 30, True)
big = pygame.font.SysFont("arial", 60, True)

ground = HEIGHT - 100
water_level = HEIGHT - 40

score = 0
game_over = False

frog_x = WIDTH // 2 - 30
frog_y = ground - 80

clouds = [
    [
        random.randint(0, WIDTH),
        random.randint(40, 180),
        random.randint(35, 60),
    ]
    for _ in range(6)
]


def draw_cloud(x, y, s):
    pygame.draw.circle(screen, WHITE, (int(x), int(y)), s)
    pygame.draw.circle(screen, WHITE, (int(x + s), int(y + 8)), s - 8)
    pygame.draw.circle(screen, WHITE, (int(x + 2 * s), int(y)), s)
    pygame.draw.circle(screen, WHITE, (int(x + s), int(y - 12)), s - 5)


def draw_frog(x, y):
    pygame.draw.ellipse(screen, GREEN, (x, y, 60, 42))
    pygame.draw.ellipse(screen, BELLY, (x + 12, y + 14, 36, 18))
    pygame.draw.circle(screen, GREEN, (x + 30, y), 18)
    pygame.draw.circle(screen, GREEN, (x + 17, y - 12), 8)
    pygame.draw.circle(screen, GREEN, (x + 43, y - 12), 8)
    pygame.draw.circle(screen, WHITE, (x + 17, y - 12), 5)
    pygame.draw.circle(screen, WHITE, (x + 43, y - 12), 5)
    pygame.draw.circle(screen, BLACK, (x + 17, y - 12), 2)
    pygame.draw.circle(screen, BLACK, (x + 43, y - 12), 2)
    pygame.draw.arc(screen, BLACK, (x + 18, y + 2, 22, 10), 0.2, 3.0, 2)


running = True

while running:

    dt = clock.tick(60) / 1000

    for event in pygame.event.get():

        if event.type == pygame.QUIT:
            running = False

    keys = pygame.key.get_pressed()

    # --------------------------------------------------------------------------
    # EEG focus is now the actual game control.
    #
    # UP is ONLY a temporary test override:
    # hold UP to see the water respond while debugging.
    # --------------------------------------------------------------------------

    focus = current_focus_level

    if keys[pygame.K_UP]:
        focus = min(100.0, current_focus_level + 25.0)

    if not game_over:

        # Water level dynamics
        water_level -= 0.7
        water_level += (focus / 100.0) * 1.8

        water_level = max(
            120,
            min(HEIGHT - 40, water_level)
        )

        score += dt

    # Drawing frame components
    screen.fill(SKY)

    pygame.draw.circle(
        screen,
        YELLOW,
        (1120, 90),
        45
    )

    for c in clouds:

        c[0] -= 0.4

        if c[0] < -150:
            c[0] = WIDTH + 100

        draw_cloud(*c)

    pygame.draw.rect(
        screen,
        GRASS,
        (0, ground, WIDTH, 100)
    )

    draw_frog(
        frog_x,
        frog_y
    )

    pygame.draw.rect(
        screen,
        WATER,
        (0, water_level, WIDTH, HEIGHT - water_level)
    )

    for i in range(0, WIDTH, 40):

        pygame.draw.arc(
            screen,
            (220, 240, 255),
            (i, water_level - 6, 40, 12),
            0,
            3.14,
            2
        )

    frog_head = frog_y - 12

    if water_level <= frog_head:
        game_over = True

    # Focus bar UI overlay
    pygame.draw.rect(
        screen,
        (40, 40, 40),
        (20, 20, 300, 30),
        border_radius=8
    )

    pygame.draw.rect(
        screen,
        (100, 255, 100),
        (23, 23, int(focus * 2.94), 24),
        border_radius=8,
    )

    screen.blit(
        font.render(
            f"Focus : {int(focus)}%",
            True,
            BLACK
        ),
        (20, 60)
    )

    screen.blit(
        font.render(
            f"Survival : {score:.1f}s",
            True,
            BLACK
        ),
        (980, 25)
    )

    screen.blit(
        font.render(
            f"Hardware: UNO R3 @ 115200 Baud",
            True,
            BLACK
        ),
        (360, 25)
    )

    if game_over:

        txt = big.render(
            "FROG DROWNED!",
            True,
            (180, 0, 0)
        )

        screen.blit(
            txt,
            (WIDTH // 2 - 220, 260)
        )

        screen.blit(
            font.render(
                "Press ESC to Exit",
                True,
                BLACK
            ),
            (WIDTH // 2 - 90, 340)
        )

    if keys[pygame.K_ESCAPE]:
        running = False

    pygame.display.flip()


# Stop EEG thread
serial_running = False

pygame.quit()