# ✒️ Novelist Agent (Alpha)

> **Create immersive fiction with an AI that remembers.**

![Status](https://img.shields.io/badge/Status-Alpha-orange)
![Python](https://img.shields.io/badge/Python-3.10+-blue)
![License](https://img.shields.io/badge/License-MIT-green)
![Backend](https://img.shields.io/badge/Backend-SQLite-lightgrey)

**Novelist** is an agentic writing system designed for long-form fiction. Unlike chatty assistants that forget details after a few pages, Novelist uses a dedicated **Database Memory** and a **Parallel Critic Tribunal** to maintain consistency, tone, and plot threads across tens of thousands of words.

⚠️ **Alpha Software**: This project is in active development. Expect API changes, experimental features, and the occasional hallucination.

---

## ✨ Key Features

### 🧠 Deep Context Memory

- **SQLite Backend**: Migrated from fragile JSON files to a robust SQL database (`story.db`).
- **Entity Tracking**: Automatically updates the "World State" (Time, Location, Inventory) and "Character Bible" (Relationships, Hidden Agendas).
- **Arc Ledger**: Tracks unresolved plot threads, promises to the reader, and thematic resonance.

### ⚡ Parallel Drafting Engine

- **"Best of 3" Generation**: The agent drafts three variations of every scene simultaneously.
- **Agentic Tribunal**: Three distinct Critic Agents (Prose, Redundancy, Arc) vote on the best draft.
- **Self-Correction**: The system automatically fixes common AI tics (purple prose, repetition) before you ever see the text.

### 📊 Writer's Dashboard

- **Real-Time Monitoring**: Watch your story grow with a Streamlit-based dashboard.
- **Structure Visualization**: Track word counts, arc progression, and character status visually.
- **Project Management**: Create and switch between multiple story projects seamlessly.
- **Log Control**: Real-time agent logs and control directly from the browser.

### 🖼️ Visuals

<p align="center">
  <img src="screenshots/home.png" width="700" alt="Novelist Dashboard Home">
  <br><em>The Mission Control Dashboard</em>
</p>

<p align="center">
  <img src="screenshots/story_setup.png" width="700" alt="Story Configuration">
  <br><em>Comprehensive Story Setup</em>
</p>

<p align="center">
  <img src="screenshots/terminal.png" width="700" alt="Agent Terminal Output">
  <br><em>The Agent Reasoning in Real-Time</em>
</p>

---

## 🚀 Getting Started

## 💻 System Requirements

**Option A: Cloud Intelligence (Recommended for most users)**

- **Machine**: Any standard laptop/desktop (Windows, Mac, Linux).
- **RAM**: 8GB+
- **Backend**: Uses APIs (OpenAI, DeepSeek, Anthropic, etc.). Fast and lightweight.

**Option B: Local Intelligence (For high-end workstations)**

- **Machine**: High-performance PC or Mac (M-series).
- **RAM**: 32GB+ System RAM.
- **GPU**: NVIDIA RTX 3060 (12GB VRAM) or better.
- **Backend**: Runs Ollama locally. Total privacy, but requires heavy hardware.
- _Dev Note: This system was developed on a high-end rig with 64GB RAM and RTX 4090 to support local 32B parameter models._

### ⚠️ WSL Users: Important Ollama Setup

If you run the agent from **WSL** (Windows Subsystem for Linux) but want to use **Windows Ollama with CUDA/GPU acceleration**, you must configure it correctly:

1. **Run Ollama on Windows only.** Do NOT install or run `ollama serve` inside WSL—this will load models onto your CPU instead of GPU.

2. **Start Ollama with all-interfaces binding:**

   ```powershell
   # In Windows PowerShell (Admin)
   $env:OLLAMA_HOST="0.0.0.0:11434"; ollama serve
   ```

3. **Add a Windows Firewall rule** (one-time):

   ```powershell
   netsh advfirewall firewall add rule name="Ollama WSL Access" dir=in action=allow protocol=TCP localport=11434
   ```

4. **Find your Windows host IP from WSL:**

   ```bash
   ip route | grep default | awk '{print $3}'
   ```

5. **Update your `.env` file** with the Windows IP:
   ```env
   OLLAMA_BASE_URL=http://<YOUR_WINDOWS_IP>:11434
   ```

> **Why?** WSL2 runs in a virtual network. `localhost` inside WSL does not automatically reach Windows. You must use the Windows host IP to ensure requests hit the GPU-enabled Windows Ollama instance.

### Prerequisites

- **Python 3.10+**
- **LLM backend** (Choose one):
  - **Local (Ollama):** Free, private. Requires [Ollama](https://ollama.ai) installed on **Windows** (for CUDA support).
  - **Cloud (BYOK):** Fast, powerful. Requires an API Key (OpenAI, Groq, Together, etc.).

### Installation

1. **Clone the Repository**

   ```bash
   git clone https://github.com/AxolDad/novelist.git
   cd novelist
   ```

2. **Setup Environment (BYOK)**
   Create a `.env` file in the root directory. Choose your path:

   **Option A: Local Power (Ollama)**

   ```env
   LLM_PROVIDER=ollama
   OLLAMA_HOST=http://localhost:11434
   WRITER_MODEL=mistral
   CRITIC_MODEL=mistral
   ```

   **Option B: Cloud Speed (OpenAI / Comparable)**

   ```env
   LLM_PROVIDER=openai
   OPENAI_API_KEY=sk-your-key-here
   WRITER_MODEL=gpt-4o
   CRITIC_MODEL=gpt-4o-mini
   # Optional: Custom Base URL for Groq/Together
   # OPENAI_BASE_URL=https://api.groq.com/openai/v1
   ```

3. **Install Dependencies**
   ```bash
   pip install -r requirements.txt
   ```

---

## 🏎️ Usage

### 1. Launch the System (Recommended)

Double-click `start.bat` on Windows to launch both the Dashboard and the Agent.

### 2. Manual Launch

**Start the Dashboard:**

```bash
streamlit run dashboard.py
```

> Go to the **Home Tab** to create a new Story Project.
>
> **💡 Note: "Create Project" vs. "Story Title"**
>
> - **Create Project (Home Tab):** Creates a physical folder on your disk. Do this once to start a book. The name you choose here is the folder name.
> - **Story Title (Story Setup Tab):** Changes the _display title_ of your book in `story_manifest.json`. Use this to rename your book creatively without breaking file paths.

**Start the Agent:**

```bash
python novelist.py --project "projects/my_story_title"
```

> The agent will begin drafting scenes based on your Manifest.

---

## 🏗️ Architecture

```mermaid
graph TD
    A[User Manifest] -->|Config| B(Novelist Agent)
    B -->|Generates 3x| C{Parallel Drafts}
    C -->|Review| D[Tribunal Critics]
    D -->|Vote & Select| E[Best Draft]
    E -->|Update| F[(SQLite Story DB)]
    F -->|Persist| G[Manuscript.md]
    F -->|Visualise| H[Streamlit Dashboard]
```

## 🤝 Contributing

Contributions are welcome! Since we are in **Alpha**, please open an issue before submitting a PR for major architectural changes.

## 📄 License

MIT License. Build something beautiful.
