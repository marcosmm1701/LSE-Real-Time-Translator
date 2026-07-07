import time
import numpy as np
import cv2
import mediapipe as mp
import tensorflow as tf
from PyQt6.QtCore import QThread, pyqtSignal

# Puntos clave de MediaPipe para pose y cara, seleccionados por su relevancia para la detección de signos.
FACE_KEYPOINTS = [
    1, 33, 263, 61, 291, 199,   # ojos (externos)
    159, 145, 386, 374,         # ojos (internos)
    13, 14, 17, 0,              # nariz y centro rostro
    78, 308, 82, 87,            # boca
    70, 63, 105, 66, 107,       # ceja derecha
    336, 296, 334, 293, 300     # ceja izquierda
]

SEQUENCE_LENGTH = 40        # número de frames en la ventana deslizante para la detección temporal
CONFIDENCE_THRESHOLD = 0.7  # umbral de confianza para considerar una predicción como válida
SMOOTHING_WINDOW = 10       # número de predicciones recientes a considerar para el suavizado de la salida (votación mayoritaria)
SMOOTHING_MIN_VOTES = 7     # número mínimo de votos idénticos en la ventana de suavizado para aceptar una predicción como estable
MAX_SENTENCE = 10           # número máximo de palabras a mostrar en la frase detectada (para evitar desbordamientos visuales)

# Especificaciones de dibujo para los landmarks de MediaPipe, con colores y grosores diferenciados para manos y pose.
_HAND_DOT  = mp.solutions.drawing_utils.DrawingSpec(color=(120, 220, 255), thickness=1, circle_radius=3)
_HAND_CONN = mp.solutions.drawing_utils.DrawingSpec(color=(80,  170, 220), thickness=2)
_POSE_DOT  = mp.solutions.drawing_utils.DrawingSpec(color=(200, 140, 255), thickness=1, circle_radius=3)
_POSE_CONN = mp.solutions.drawing_utils.DrawingSpec(color=(150, 100, 220), thickness=2)

# Capa de atención temporal
class TemporalAttention(tf.keras.layers.Layer):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.score_dense = tf.keras.layers.Dense(1)

    def call(self, x):
        scores = self.score_dense(x)
        weights = tf.nn.softmax(scores, axis=1)
        return tf.reduce_sum(weights * x, axis=1)

    def build(self, input_shape):
        self.score_dense.build(input_shape)
        super().build(input_shape)

    def get_config(self):
        return super().get_config()


# Función extract and normalize: idéntica a la de real_time_turbo.py
def _extract_and_normalize(results):
    if results.pose_landmarks:
        pose = np.array([
            [r.x, r.y, r.z, r.visibility]
            for r in results.pose_landmarks.landmark
        ])
        shoulder_center = (pose[11][:3] + pose[12][:3]) / 2
        shoulder_dist = np.linalg.norm(pose[11][:3] - pose[12][:3])
        pose[:, :3] -= shoulder_center
        if shoulder_dist > 0:
            pose[:, :3] /= shoulder_dist
        pose = pose.flatten()
    else:
        pose = np.zeros(132)

    if results.face_landmarks:
        face = np.array([
            [results.face_landmarks.landmark[i].x,
             results.face_landmarks.landmark[i].y,
             results.face_landmarks.landmark[i].z]
            for i in FACE_KEYPOINTS
        ])
        face -= face[0]
        face = face.flatten()
    else:
        face = np.zeros(84)

    def _hand(lm):
        if lm:
            h = np.array([[r.x, r.y, r.z] for r in lm.landmark])
            h -= h[0]
            d = np.linalg.norm(h[0] - h[9])
            if d > 0:
                h /= d
            d1 = np.linalg.norm(h[4] - h[8])
            d2 = np.linalg.norm(h[4] - h[20])
            d3 = np.linalg.norm(h[8] - h[0])
            z_diff = h[3][2] - h[6][2]
            return h.flatten(), [d1, d2, d3, z_diff]
        return np.zeros(63), [0.0, 0.0, 0.0, 0.0]

    lh, ld = _hand(results.left_hand_landmarks)
    rh, rd = _hand(results.right_hand_landmarks)
    return np.concatenate([pose, face, lh, rh, ld, rd])

# DetectorThread: hilo de detección que captura video, procesa con MediaPipe, extrae características, ejecuta el modelo de TensorFlow y emite señales para actualizar la interfaz.
# Está separado del hilo principal de la interfaz para separa responsabilidades y evitar bloqueos.
class DetectorThread(QThread):
    frame_signal      = pyqtSignal(object)   # np.ndarray BGR (with landmarks)
    prediction_signal = pyqtSignal(str, float)
    sentence_signal   = pyqtSignal(list)
    fps_signal        = pyqtSignal(float)
    hands_signal      = pyqtSignal(bool)
    buffer_signal     = pyqtSignal(int)       # 0-40: frames accumulated
    status_signal     = pyqtSignal(str)       # loading | detecting | idle | error
    error_signal      = pyqtSignal(str)

    def __init__(self, model_path: str, actions_path: str, parent=None):
        super().__init__(parent)
        self.model_path = model_path
        self.actions_path = actions_path
        self._running = False
        self._clear_requested = False
        self._pending_sentence: list | None = None   # set via set_sentence()
        self._sequence: list = []
        self._sentence: list = []
        self._history: list = []
        self._fps_samples: list = []
        self._current_fps = 16.0

    # ------------------------------------------------------------------ public
    def stop(self):
        self._running = False
        self.wait(5000)

    def request_clear(self):
        self._clear_requested = True

    def set_sentence(self, words: list):
        """Replace the current sentence (thread-safe via flag pattern)."""
        self._pending_sentence = list(words)

    # ----------------------------------------------------------------- private
    def run(self):
        self._running = True
        self.status_signal.emit("loading")

        try:
            model = tf.keras.models.load_model(
                self.model_path,
                custom_objects={
                    "TemporalAttention": TemporalAttention,
                    "Custom>TemporalAttention": TemporalAttention,
                },
            )
            predict_fn = tf.function(model, reduce_retracing=True)
            actions = np.load(self.actions_path)
        except Exception as exc:
            self.error_signal.emit(str(exc))
            self.status_signal.emit("error")
            return

        cap = cv2.VideoCapture(0)
        if not cap.isOpened():
            self.error_signal.emit("No se pudo abrir la cámara")
            self.status_signal.emit("error")
            return

        self.status_signal.emit("detecting")

        mp_draw   = mp.solutions.drawing_utils
        mp_hands  = mp.solutions.hands
        mp_hol    = mp.solutions.holistic

        with mp_hol.Holistic(
            static_image_mode=False,
            model_complexity=0,
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5,
        ) as holistic:
            while self._running and cap.isOpened():
                t0 = time.perf_counter()

                ret, frame = cap.read()
                if not ret:
                    break

                # --- Pending mutations (flag pattern, GIL-safe) ---
                if self._clear_requested:
                    self._sentence.clear()
                    self._history.clear()
                    self._sequence.clear()
                    self._clear_requested = False
                    self.sentence_signal.emit([])

                if self._pending_sentence is not None:
                    self._sentence = self._pending_sentence
                    self._pending_sentence = None
                    self.sentence_signal.emit(list(self._sentence))

                # --- MediaPipe ---
                frame = cv2.flip(frame, 1)
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                rgb.flags.writeable = False
                results = holistic.process(rgb)
                rgb.flags.writeable = True
                bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)

                # --- Landmark overlay ---
                mp_draw.draw_landmarks(bgr, results.left_hand_landmarks,
                                       mp_hands.HAND_CONNECTIONS, _HAND_DOT, _HAND_CONN)
                mp_draw.draw_landmarks(bgr, results.right_hand_landmarks,
                                       mp_hands.HAND_CONNECTIONS, _HAND_DOT, _HAND_CONN)
                mp_draw.draw_landmarks(bgr, results.pose_landmarks,
                                       mp_hol.POSE_CONNECTIONS, _POSE_DOT, _POSE_CONN)

                self.frame_signal.emit(bgr.copy())

                has_hands = bool(
                    results.left_hand_landmarks or results.right_hand_landmarks
                )
                self.hands_signal.emit(has_hands)

                # --- Feature extraction & buffer ---
                kp = _extract_and_normalize(results)
                self._sequence.append(kp)
                self._sequence = self._sequence[-SEQUENCE_LENGTH:]
                self.buffer_signal.emit(len(self._sequence))

                # --- Inference ---
                action_str = ""
                conf = 0.0

                if len(self._sequence) == SEQUENCE_LENGTH:
                    seq = np.array(self._sequence, dtype=np.float32)
                    deltas = np.diff(seq, axis=0)
                    deltas = np.vstack([np.zeros((1, 350), dtype=np.float32), deltas])
                    deltas *= self._current_fps
                    inp = tf.convert_to_tensor(
                        [np.hstack([seq, deltas])], dtype=tf.float32
                    )
                    pred = predict_fn(inp, training=False).numpy()[0]
                    idx = int(np.argmax(pred))

                    self._history.append(idx)
                    self._history = self._history[-SMOOTHING_WINDOW:]

                    mc = max(set(self._history), key=self._history.count)
                    if self._history.count(mc) > SMOOTHING_MIN_VOTES:
                        action_str = str(actions[mc])
                        conf = float(pred[mc])
                        if conf > CONFIDENCE_THRESHOLD:
                            if not self._sentence or action_str != self._sentence[-1]:
                                self._sentence.append(action_str)
                            if len(self._sentence) > MAX_SENTENCE:
                                self._sentence = self._sentence[-MAX_SENTENCE:]
                            self.sentence_signal.emit(list(self._sentence))

                self.prediction_signal.emit(action_str, conf)
                self.fps_signal.emit(self._current_fps)

                elapsed = time.perf_counter() - t0
                if elapsed > 0:
                    self._fps_samples.append(1.0 / elapsed)
                    self._fps_samples = self._fps_samples[-30:]
                    self._current_fps = sum(self._fps_samples) / len(self._fps_samples)

        cap.release()
        self.status_signal.emit("idle")
