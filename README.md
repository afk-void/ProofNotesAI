# ProofNotes

**Study smarter, with answers grounded in your own notes.**

ProofNotes is a private, local-first AI study workspace. Upload course material, ask questions, explore citations, and practice what you've learned.

Built for SBUHacks 2026.

## Features

- **AI Chat** — Ask questions about uploaded course material.
- **Course Libraries** — Keep documents and conversations organized by course.
- **Source Citations** — Trace answers to their original PDF pages.
- **Recall Lab** — Practice with source-backed questions and different difficulty levels.
- **Coverage Radar** — Identify potential gaps between lecture materials and personal notes.
- **Claim Inspector** — Check whether a statement is supported by uploaded documents.
- **Local AI** — Run inference on your own computer without a cloud API.

## Tech Stack

- Python and FastAPI
- Ollama with Qwen3.6 27B
- Qwen3 Embedding 0.6B
- SQLite and hybrid retrieval
- PyMuPDF
- HTML, CSS, and JavaScript

## Getting Started

### macOS

Requirements: Python 3.10+ and Ollama.

1. Install Ollama: https://ollama.com
2. Clone this repository.
3. Open Terminal inside the project folder.

Run:

    bash setup_models_mac.command
    bash run_mac.command

Open http://127.0.0.1:8765

### Windows

Requirements: Python 3.10+ and Ollama.

Run `setup_models_windows.bat`, then `run_windows.bat`.

## Privacy

Documents, conversations, and model inference remain local to your device. Models and dependencies require an initial download.

No OpenAI API key is required.

## Limitations

AI-generated explanations and study questions can contain mistakes. Citations improve traceability but do not guarantee correctness. Verify important answers against the original course material.

## Hackathon

Created for **SBUHacks 2026**.

