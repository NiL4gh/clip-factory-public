# Contributing to ClipFactory

Thanks for taking a look. This is a small, single-maintainer project, so keep
changes focused and easy to review.

## Development setup

Requirements: **Python 3.9+**, **Node.js 20+**, and **ffmpeg** on `PATH`.

```bash
git clone https://github.com/NiL4gh/clip-factory-public.git
cd clip-factory-public

python -m venv .venv
# Windows: .venv\Scripts\activate
source .venv/bin/activate

pip install -r requirements.txt

cd frontend
npm ci
npm run build
cd ..
```

Copy `.env.example` to `.env` if you want to point the pipeline at a cloud LLM
provider. All keys are optional; without one, LLM extraction is unavailable.

```bash
uvicorn server.main:app --port 8000
```

## Before you open a PR

Both checks below must pass locally. CI runs the same commands.

**Backend tests**

```bash
python -m pytest tests -q
```

If you do not want the full GPU stack installed, the tests only need:

```bash
pip install fastapi uvicorn pydantic python-dotenv numpy librosa \
    opencv-python-headless scenedetect pillow huggingface-hub httpx pytest
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install faster-whisper
```

**Frontend typecheck + build**

```bash
cd frontend
npx tsc --noEmit
npm run build
```

## Pull request guidelines

- One logical change per PR. Keep diffs small enough to read in one sitting.
- Do not change pipeline behaviour (download → transcribe → extract → render)
  in a refactor. Behaviour changes belong in their own PR with a clear rationale.
- Add or update a test in `tests/` for any bug fix or new backend behaviour.
- Do not commit secrets, cookies, model weights, rendered videos, or build
  output. `.env`, `cookies.txt`, `output/`, `work/*` and `dist/` are ignored.
- Describe **what** changed and **why** in the PR body. Screenshots help for
  frontend changes.
- Keep existing error handling intact — it is there for a reason.

## Reporting bugs

Open an issue using the bug report template. Include your OS, whether you are
running on Colab or locally, the exact command you ran, and the relevant log
lines.
