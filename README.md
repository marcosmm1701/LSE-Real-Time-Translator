<div align="center">

# 🤟 LSE Real-Time Translator

### Real-time translation from Spanish Sign Language to spoken language, running on consumer hardware

*Bachelor's Thesis · Computer Engineering · Universidad Autónoma de Madrid · 2026*

[![Python](https://img.shields.io/badge/Python-3.11-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![TensorFlow](https://img.shields.io/badge/TensorFlow-2.16-FF6F00?style=flat-square&logo=tensorflow&logoColor=white)](https://www.tensorflow.org/)
[![MediaPipe](https://img.shields.io/badge/MediaPipe-0.10-0097A7?style=flat-square&logo=google&logoColor=white)](https://google.github.io/mediapipe/)
[![PyQt6](https://img.shields.io/badge/PyQt6-GUI-41CD52?style=flat-square&logo=qt&logoColor=white)](https://riverbankcomputing.com/software/pyqt/)
[![License](https://img.shields.io/badge/License-Restricted%20use-red?style=flat-square)](#-license-and-usage)
[![Status](https://img.shields.io/badge/Status-Functional-success?style=flat-square)]()

**97.55%** standard accuracy · **83.50%** cross-session · **17.5 FPS** · **104 signs** · **no GPU**

[What it does](#-what-it-does) ·
[Demo](#-demo) ·
[Results](#-results) ·
[What this repo includes](#-what-this-repository-includes) ·
[Installation](#-installation) ·
[Contact](#-contact-and-permissions)

</div>

---

## 🎯 What it does

> **Even today, more than 100,000 users of Spanish Sign Language (LSE) live with a constant communication barrier**, since the vast majority of hearing people do not know this language.

In this project, **I designed and developed a complete real-time LSE-to-speech translation system** that runs entirely on consumer hardware. **To the best of my knowledge, it is the most complete and accurate LSE translation system reported to date.** To achieve this, **I also created the largest LSE dataset reported in the scientific literature**, comprising **104 different signs**, which was specifically collected and annotated for training and evaluating this system.

A signer stands in front of the camera, performs a sign, and the system **recognizes it, displays it on screen, adds it to a running sentence, and speaks it aloud through synthesized voice** — all in real time, with **no GPU, no servers, and no data sent to the cloud**.

The system achieves **97.55% standard accuracy** and **83.50% cross-session accuracy** while maintaining **17.5 FPS** on a standard mid-range laptop, demonstrating that high-quality real-time sign language translation is possible without specialized hardware.

---

## 🎥 Demo

<div align="center">

*Real-time recognition on a low-power Intel Core i7, no dedicated GPU.*

<p align="center">
  <img src="assets/Demo1.gif" width="48%" alt="Demo 1">
  <img src="assets/Demo2.gif" width="48%" alt="Demo 2">
</p>

<p align="center">
  <img src="assets/Demo3.gif" width="48%" alt="Demo 3">
  <img src="assets/Demo4.gif" width="48%" alt="Demo 4">
</p>

</div>

---

## ✨ Features

### 🖥️ Desktop application

- **Native graphical interface** showing the camera feed, the recognized sign, and the sentence being built in real time.
- **Text-to-speech (TTS)** that speaks each detected sign aloud in Spanish.
- **Sentence building** word by word, with interactive editing.
- **Live indicators** for FPS, detection status, and confidence level.
- **Keyboard shortcuts** to control capture, clear the sentence, and trigger voice playback.

### 🧠 Recognition engine

- **104 recognized signs**: full fingerspelling alphabet + everyday vocabulary.
- **Real-time recognition** at **17.5 FPS on CPU**, no dedicated GPU required.
- **Confidence filtering** that discards unreliable predictions for a stable output.
- Compact model (**9.6 MB**) optimized for deployment on consumer hardware.

### 🔬 Technical foundation *(detailed in the thesis)*

The system combines body landmark extraction, a **proprietary multi-level geometric normalization system**, **laterality-aware data augmentation** techniques, and a **recurrent architecture with temporal attention**, validated through a **dual evaluation protocol** that measures performance under real usage conditions.

> 📄 *Methodological and implementation details are documented in the thesis itself, not in this repository (see [What this repository includes](#-what-this-repository-includes)).*

---

## 📈 Results

<div align="center">

| Metric | Value |
|---|---|
| **Accuracy (standard test)** | **97.55 %** |
| **Accuracy (cross-session, real conditions)** | **83.50 %** |
| **Sustained FPS** | **17.5** |
| **Mean inference latency** | **14.6 ms** |
| **Recognized classes** | **104** |
| **Model size** | **9.6 MB** |
| **Hardware** | **CPU (no GPU)** |

</div>

**The core methodological finding:** the system maintains **83.50% accuracy under entirely new conditions** (different day, lighting, and posture), degrading far less than alternative architectures. This robustness to real-world variation — not just raw test accuracy — is the project's differentiating contribution, validated through an exhaustive ablation study.

---

## 📦 What this repository includes

> ⚠️ **This repository contains only the graphical interface application and the already-trained model.**
> **It does not include** the data capture, augmentation, normalization, training, or evaluation code, nor the dataset. Those form the original core of the thesis and **are not public** (see [License and usage](#-license-and-usage)).

### ✅ Included

```
LSE-Translator/
│
├── run_app.py               # Application entry point
├── app_desktop/
│   ├── detector.py          # Real-time detection and inference module
│   └── glossary.py          # Built-in sign glossary
├── lse_model_best.keras     # Trained model (104 classes)
├── actions.npy              # Recognized class mapping
├── words_to_capture.json    # System vocabulary
├── requirements.txt         # Dependencies
└── README.md                # This file
```

### 🔒 Not included *(private — thesis core)*

- ❌ **Dataset capture** code
- ❌ **Data augmentation** code and techniques
- ❌ **Geometric normalization** and feature extraction code
- ❌ **Training pipeline** and hyperparameter tuning
- ❌ **Evaluation, ablation, and benchmarking** scripts
- ❌ The **dataset** itself (original and augmented captures)

This separation is deliberate: the repository lets you **see and run** the working system, without being able to reproduce or derive the research work behind it.

---

## 🚀 Installation

### Requirements

- Python 3.11 or higher
- A working webcam
- Windows 10/11 recommended (text-to-speech relies on the system's engine)
- ~3 GB of free space for the environment and dependencies

### Steps

```bash
# 1. Clone the repository
git clone https://github.com/marcosmm1701/LSE-Translator.git
cd LSE-Translator

# 2. Create and activate a virtual environment
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # Linux/macOS

# 3. Install dependencies
pip install -r requirements.txt

# 4. Run the application
python run_app.py
```

> 💡 The trained model is already included: **you don't need the dataset or any retraining** to use the system. Just run it and start signing.

---

## 🎓 Academic context

Bachelor's Thesis for the **Bachelor's Degree in Computer Engineering** at the **Escuela Politécnica Superior, Universidad Autónoma de Madrid**, 2025/2026 academic year.

### Differentiating contributions *(detailed in the thesis)*

1. Proprietary **multi-level geometric normalization** system.
2. **Hardware-invariant temporal scaling**.
3. **Laterality-aware data augmentation** (right-/left-handed signers).
4. **Dual evaluation protocol** quantifying performance under real conditions.
5. **Proprietary 104-class dataset** captured under real usage conditions.

### Citation

If this work is useful to you, please cite it accordingly:

```bibtex
@thesis{Sistema-de-traducción-de-lengua-de-signos-a-lengua-oral-en-tiempo-real,
  author = {Marcos Muñoz Merchán},
  title  = {Real-Time Spanish Sign Language to Spoken Language Translation System},
  school = {Universidad Autónoma de Madrid, Escuela Politécnica Superior},
  year   = {2026},
  type   = {Bachelor's Thesis},
  address = {Madrid, Spain}
}
```

---

## ⚠️ License and usage

### Authorship disclaimer

> **This project is the exclusive work of its author** and constitutes their university Bachelor's Thesis. The code, the trained model, the normalization system, the data augmentation techniques, and the associated dataset are the result of individual, personal work carried out over more than a year.

### ✅ Permitted

- **Reviewing and running** the included application for educational and demonstration purposes.
- **Studying** how the interface works.
- **Citing** the work in academic publications.

### ❌ Requires the author's explicit permission

- **Reusing the code** in other projects, especially commercial ones.
- **Publishing derivatives** or forks with substantial modifications.
- **Using the model** in production applications or third-party products.
- **Accessing the training dataset** *(not included in this repository)*.
- **Adapting the techniques** in other academic projects without proper citation.

### About the dataset

The proprietary dataset — over **10,000 original sequences** (and **73,150 after augmentation**) across 104 classes, with more than **7 hours of recorded video** — **will not be made public**. Its distribution requires the author's explicit authorization, given the personal effort invested in building it and the ethical considerations around biometric data.

If you need access for academic or research purposes, **contact the author** explaining your intended use. Requests are evaluated individually.

---

## 🛣️ Future work

- 🌍 Expansion to **multiple signers** and conversational vocabulary.
- 🔄 **Continuous signing** (chained sentences, not just isolated signs).
- 📝 **Linguistic post-processing** to reconstruct grammatically correct sentences.
- 📱 **Mobile deployment** leveraging the model's lightweight footprint.
- 🔁 **Reverse generation**, text → LSE, via animated avatars.

---

## 📞 Contact and permissions

For inquiries, usage requests, dataset access, or academic collaborations:

- 📧 **Email**: marcosmunozmerchan@gmail.com
- 💼 **LinkedIn**: www.linkedin.com/in/marcos-muñozm
- 🎓 **University**: Universidad Autónoma de Madrid · Escuela Politécnica Superior

Please include **who you are**, **what you intend to use the material for**, and whether the use is **academic, commercial, or personal**.

---

<div align="center">

### 💙 Acknowledgments

To my tutor, my family, my girlfriend, and my friends, for their support throughout the process.

And to **me**, for never surrender when all was going wrong and it seemed impossible to achieve.

---

⭐ *If you find this project interesting, consider leaving a star.*

</div>