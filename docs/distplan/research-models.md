# models

**Question:** Distributing local speech models with a desktop app (DeskIT, Windows 11, Hebrew push-to-talk): ivrit-ai Hebrew whisper models on Hugging Face (exact license of ivrit-ai/whisper-large-v3-turbo-ct2 and siblings, sizes, can an app download them for a user, HF token needed?, smaller ivrit-ai model for CPU users), realistic CPU latency of whisper-large-v3-turbo int8 on a laptop for a 5-10 s Hebrew clip and smaller Hebrew-capable alternatives (whisper.cpp, sherpa-onnx, distil, moonshine, parakeet), NVIDIA cuBLAS/cuDNN pip wheel sizes and redistribution terms, AMD/Intel GPU options (Vulkan via whisper.cpp, DirectML), how apps handle an Ollama dependency, Hugging Face download UX (resumable, progress, HF_HOME, offline mode), Groq free-tier Whisper limits as opt-in cloud fallback.

Researched 2026-09-16. Findings appended per source below.

## Findings (per source)

### S1. ivrit-ai/whisper-large-v3-turbo-ct2 model card (https://huggingface.co/ivrit-ai/whisper-large-v3-turbo-ct2)
- License tag on the card: **apache-2.0** ("License: apache-2.0"). Base model: openai/whisper-large-v3-turbo (itself Apache-2.0 / MIT-family from OpenAI). Not gated: files list is public, no accept-terms banner seen -> **no HF token needed** for anonymous download.
- Card text: "This is ivrit.ai's faster-whisper model, based on the ivrit-ai/whisper-large-v3-turbo Whisper model" ... training "295 hours of volunteer-transcribed speech from the ivrit-ai/crowd-transcribe-v5 dataset, as well as 93 hours of professional transcribed speech".
- Usage in card is a faster-whisper snippet (WhisperModel(..., language="he")). ~7.6k downloads/month. Last update Oct 27, 2025. Size not printed on card (see S3 file listing).

### S2. ivrit-ai org page (https://huggingface.co/ivrit-ai)
- Models: whisper-large-v3-turbo-ct2, whisper-large-v3-ct2, whisper-large-v3-turbo-onnx (Dec 2025), yi-whisper-large-v3-turbo (+ -ct2, + -ggml, Feb 2026 = newest turbo line), yi-whisper-large-v3 (+ -ct2, -ggml), pyannote diarization.
- **No small/base/tiny/distil Hebrew model in the org** — everything is large-v3 (1.55B) or large-v3-turbo (0.8B). For CPU users the turbo model is the only ivrit-ai option; a "yi-...-ggml" whisper.cpp build exists (Feb 2026) which is the route to Vulkan/AMD/Intel GPUs.

### S3. Search snippets: Groq free tier (secondary sources; verify on console.groq.com/docs/rate-limits — see S6)
- Snippet: whisper-large-v3-turbo free tier = 20 RPM, 2,000 RPD, 7,200 audio-seconds/hour, 28,800 audio-seconds/day.

### S4. Search snippets: HF download UX
- huggingface_hub: interrupted downloads keep a .incomplete temp file and resume on next call; progress bars via tqdm (disable with HF_HUB_DISABLE_PROGRESS_BARS); cache = $HF_HOME/hub, default ~/.cache/huggingface/hub -> on Windows C:\Users\<u>\.cache\huggingface\hub; HF_HUB_OFFLINE=1 forces cache-only; cache_dir param overrides per call.

### S5. Search snippets: whisper.cpp Vulkan
- whisper.cpp 1.8.3 (Phoronix): "12x performance boost" with integrated graphics via Vulkan; Vulkan runs on NVIDIA, AMD, Intel Arc/iGPU. Windows faster-whisper GPU pain: nvidia pip wheels' DLLs land in site-packages/nvidia/<pkg>/bin which Windows does not search -> app must os.add_dll_directory them (backtalk issue #28). faster-whisper README points Windows users to Purfview/whisper-standalone-win "cuBLAS and cuDNN" archive.

### S6. ivrit-ai/whisper-large-v3-turbo-ct2 file tree (https://huggingface.co/ivrit-ai/whisper-large-v3-turbo-ct2/tree/main)
- model.bin **1.62 GB** (float16 CT2 weights), tokenizer.json 2.71 MB, vocabulary.json 1.07 MB, config.json, preprocessor_config.json, README. Total ~1.625 GB. No LICENSE file in repo, only the apache-2.0 tag in the card metadata. (Note: faster-whisper converts fp16->int8 at load time; on disk it stays 1.62 GB unless the owner re-converts with `ct2-transformers-converter --quantization int8` -> roughly 0.8 GB, which he could host himself under Apache-2.0 with attribution.)

### S7. Groq rate limits page (https://console.groq.com/docs/rate-limits) — PRIMARY
- Free plan rows: whisper-large-v3 and whisper-large-v3-turbo both: **RPM 20, RPD 2K, ASH 7.2K, ASD 28.8K** (audio-seconds per hour/day = 2 h/h, 8 h/day).
- Quote: "Rate limits apply at the organization level, not individual users." -> if the OWNER's key were shared, all users would share 2,000 requests/day; a per-user Groq key (each user makes own free account) keeps limits per user and keeps audio off the owner's account.
- "Upgrade to Developer plan to access higher limits, Batch and Flex processing, and more." Free-tier audio file cap not on this page (Groq docs elsewhere say 25 MB free / 100 MB dev — uncertainty, verify).

### S8. NVIDIA pip wheels on PyPI — PRIMARY (pypi.org/project/nvidia-cudnn-cu12, nvidia-cublas-cu12)
- nvidia-cudnn-cu12 9.26.0.51 (Sep 10 2026): **win_amd64 wheel 746.5 MB**. nvidia-cublas-cu12 12.9.2.10: **win_amd64 wheel 553.2 MB**, license field "LicenseRef-NVIDIA-Proprietary". Together ~1.3 GB download, more on disk (cuDNN 9 unpacks to ~1+ GB). These are the two libs CTranslate2 needs on top of the driver (CUDA runtime is statically linked in ctranslate2 wheels).
- Windows gotcha: DLLs land in site-packages/nvidia/cublas/bin and nvidia/cudnn/bin; Windows does not search there, so the app must call os.add_dll_directory() on both before importing ctranslate2 (or set PATH).

### S9. NVIDIA EULA (search snippets of docs.nvidia.com/cuda/eula and cuDNN EULA) — needs a direct read for exact clause
- CUDA EULA lists cuBLAS/cuDNN runtime libs as redistributable "at no charge" under attachment A; condition: distributor must have end user accept NVIDIA's terms ("written or clickwrap agreement ... no less restrictive"). Practical implication: an installer that runs `pip install nvidia-cublas-cu12 nvidia-cudnn-cu12` from PyPI at install time (user downloads from NVIDIA's own PyPI package) sidesteps bundling; if bundled inside the installer, show NVIDIA's EULA clickwrap. Marked as uncertainty until the exact clause is quoted (see S12).

### S10. faster-whisper issue #1030 (https://github.com/SYSTRAN/faster-whisper/issues/1030)
- GPU only: turbo int8 19.6 s for 13 min audio (RTF ~0.025) on GPU, 1.5 GB VRAM; fp16 19.2 s, 2.5 GB VRAM. Confirms turbo int8 fits in ~1.5 GB VRAM -> GTX 1650 / MX-class laptops can run it. No CPU numbers here.

### S11. yi-whisper models: "yi" = **Yiddish** finetune, NOT a newer Hebrew line. Ignore for DeskIT. So the Hebrew set is: whisper-large-v3 (+ct2), whisper-large-v3-turbo (+ct2, +onnx). No official ivrit-ai ggml for Hebrew -> a whisper.cpp/Vulkan path needs the owner to convert HF weights to ggml himself (whisper.cpp models/convert-h5-to-ggml.py) and host the file.

### S12. Search snippets, CPU RTF (secondary: tesseraai, snailtext, vexascribe)
- Claimed: full large-v3 int8 on CPU (i9/Ryzen 9) RTF ~2.5; turbo ~6x faster on CPU than large-v3 -> RTF ~0.4-0.6 on a desktop-class CPU; typical thin laptop (4-8 cores) plausibly RTF 0.8-1.5 -> **5-10 s clip ≈ 5-15 s wait, plus a 3-10 s first-load** for 1.6 GB weights. Needs a primary benchmark (see S13).
- sherpa-onnx families: Zipformer, Paraformer, Parakeet, Canary, Whisper, GigaAM, Moonshine, SenseVoice. Parakeet v3 is multilingual (25 European languages) — Hebrew not listed; Moonshine is English (+ a few langs); SenseVoice = zh/en/ja/ko/yue. **No small non-Whisper Hebrew model found**; Whisper-family is the only credible Hebrew option, and the ivrit-ai finetune is the only Hebrew-specialised one.

### S13. snailtext CPU benchmark table (https://snailtext.app/blog/do-you-need-a-gpu-for-voice-to-text/) — secondary, but concrete
- Whisper small int8 on i7-12700K: RTF 0.13; large-v3 on Ryzen 7 5700G: RTF 3.0; Parakeet TDT v3 on i7-12700KF: RTF 0.033 (but Parakeet has no Hebrew); M1 CPU-only: tiny 0.04, base 0.07, small 0.17, medium 0.40. Turbo (0.8B, 4 decoder layers) sits between medium and large -> **expect RTF ~0.5-1.0 on a desktop CPU, ~1-2 on a 4-core thin laptop; a 7 s Hebrew clip ≈ 5-15 s.** Usable for dictation only with a "transcribing..." indicator; not snappy.

### S14. NVIDIA CUDA EULA (https://docs.nvidia.com/cuda/eula/index.html) — PRIMARY
- "The portions of the SDK that are distributable under the Agreement are listed in Attachment A." (cuBLAS is in Attachment A). Conditions: "Your application must have material additional functionality, beyond the included portions of the SDK." / "The distributable portions of the SDK shall only be accessed by your application." / "You agree that you will not... distribute or sublicense the SDK as a stand-alone product." / attribution "This software contains source code provided by NVIDIA Corporation."
- cuDNN is NOT in this EULA; it has its own SLA (docs.nvidia.com/deeplearning/cudnn/.../eula.html) with a similar redistribution grant plus the clause that end users must accept terms via written/clickwrap agreement. => Bundling cuBLAS+cuDNN inside DeskIT's installer is permitted with an EULA screen + NOTICE; **simpler and safer: don't bundle, have the installer/first-run `pip install nvidia-cublas-cu12 nvidia-cudnn-cu12` from PyPI only when an NVIDIA GPU is detected** (user downloads NVIDIA's own package, ~1.3 GB).

### S15. Groq speech-to-text docs (https://console.groq.com/docs/speech-to-text) — PRIMARY
- Free tier max upload "25 MB"; Dev tier "100MB". Formats flac, mp3, mp4, mpeg, mpga, m4a, ogg, wav, webm. Paid price: turbo $0.04/h, large-v3 $0.111/h; "Minimum Billed Length 10 seconds". language = ISO-639-1 ("he"). No retention statement on this page -> check Groq privacy/terms before telling users what happens to audio (uncertainty).

### S16. huggingface_hub download guide (https://huggingface.co/docs/huggingface_hub/guides/download) — PRIMARY
- hf_hub_download / snapshot_download cache "in a version-aware way"; cache_dir param or HF_HOME env; `local_dir=` writes plain files into a folder of your choosing (with a .cache/huggingface metadata subfolder) — best for a per-user AppData\Local\DeskIT\models folder. snapshot_download "Downloads are made concurrently". dry_run=True returns per-file sizes -> can show "1.6 GB to download" before starting. hf_xet chunked downloads installed by default since 0.32. Public repos need no token. Resume: interrupted .incomplete files resume on next call (from file_download reference). Progress: tqdm class can be swapped (tqdm_class= param) to drive a Tk progress bar. HF_HUB_OFFLINE=1 => never touch network.

### S17. DirectML / whisper.cpp for non-NVIDIA GPUs (search snippets)
- whisper.cpp ships Windows release zips with CPU, CUDA and Vulkan builds; Vulkan runs on AMD/Intel/NVIDIA (whisper.cpp 1.8.3 "12x" iGPU gain per Phoronix). Route for Hebrew = convert ivrit-ai HF weights to ggml (owner hosts ~1.6 GB f16 or ~0.5-0.9 GB q5/q8 file) and drive whisper-cli.exe or pywhispercpp. DirectML: ONNX Runtime DirectML works on any DX12 GPU; ivrit-ai publishes whisper-large-v3-turbo-onnx (Dec 2025) but Whisper-on-DirectML export is fiddly (Olive issue #813, onnxruntime-genai #1771) — treat as experimental, not v1.

### S18. Ollama (search snippets; Ollama is MIT-licensed, ~5 MB Windows installer, background service at http://localhost:11434 answering "Ollama is running")
- Common desktop-app pattern (Open WebUI, AnythingLLM, electron-gpt): **detect-and-prompt** — GET localhost:11434 at startup; if absent, show "Install Ollama (free, ollama.com)" link and keep LLM features hidden; some (AnythingLLM) bundle their own llama.cpp instead. Bundling ollama.exe is legal (MIT) but adds a service the user did not ask for; for DeskIT the LLM passes are optional (Groq/Gemini cover them), so detect-and-prompt is enough.

### S19. whisper.cpp discussion #3752 (https://github.com/ggml-org/whisper.cpp/discussions/3752) — PRIMARY benchmark, but 2010 CPU
- Intel i5-460M (2C/4T, no AVX), 11 s clip: large-v3-turbo q4_0 = 142 s total (13x slower than real time), q8_0 = 179 s; small q4_0 = 40 s; base = 13 s. "q4_0: UNDISPUTED CHAMPION. Fastest inference time on legacy hardware across all model sizes." Scaling to a 2022+ 8-core AVX2 laptop (roughly 10-15x this chip) gives turbo ~10-14 s for an 11 s clip -> **RTF ~1 on CPU**, matching S13's estimate. whisper.cpp q4_0 is a lossier quant than CT2 int8; Hebrew accuracy of q4 ivrit weights would need the owner's own check.

### S20. cuDNN SLA (https://docs.nvidia.com/deeplearning/cudnn/backend/latest/reference/eula.html) — PRIMARY
- Distributable: "the runtime files .so and .dll"; conditions identical to CUDA EULA: "Your application must have material additional functionality, beyond the included portions of the SDK." / "The distributable portions of the SDK shall only be accessed by your application." / attribution "This software contains source code provided by NVIDIA Corporation." / end-user terms "consistent with the terms of this Agreement". => bundling is allowed for an app like DeskIT with an EULA/NOTICE; pip-at-install avoids the paperwork.
- whisper.cpp latest release v1.9.4 (Sep 11 2025) ships Windows zips (cpu / cuda / vulkan variants per project README; asset list failed to load, sizes unverified).

## Options compared

| Option | Hebrew quality | Download | Latency, 7 s clip | Hardware | License / cost | Verdict for DeskIT |
|---|---|---|---|---|---|---|
| A. faster-whisper + ivrit-ai/whisper-large-v3-turbo-ct2, CUDA | best (Hebrew finetune) | 1.62 GB model + ~1.3 GB nvidia wheels | ~0.3-1 s | NVIDIA GPU, >=2 GB VRAM | Apache-2.0 model; NVIDIA libs proprietary but redistributable; $0 | **Tier 1 (what he has today)** |
| B. same model, faster-whisper CPU int8 | same | 1.62 GB (0.8 GB if owner re-converts to int8) | ~5-15 s (RTF ~1) + 3-10 s cold load | any x64 with >=4 GB free RAM | $0 | **Tier 2 default for no-GPU users**, with a visible "transcribing" state |
| C. whisper.cpp Vulkan + owner-converted ivrit ggml (q8/q5) | same weights, quant loss unknown | ~0.9-1.6 GB + 10-30 MB exe | ~1-4 s on iGPU/AMD/Intel Arc | any Vulkan GPU incl. Intel/AMD iGPUs | MIT engine, Apache model; owner must convert + host | **Tier 2b later** — biggest win for "no big GPU" users, but a second engine |
| D. ONNX Runtime DirectML + ivrit-ai/whisper-large-v3-turbo-onnx | same | ~1.6 GB | unknown | any DX12 GPU | MIT | experimental; Whisper-on-DirectML export is fragile — skip for v1 |
| E. Groq whisper-large-v3-turbo (user's own free key) | good generic Hebrew (not ivrit finetune) | 0 | ~1-2 s network | none | free: 20 RPM, 2K req/day, 7.2K audio-s/h, 28.8K/day, 25 MB/file; org-level limits | **opt-in cloud fallback**; audio leaves the machine — explicit consent screen |
| F. Smaller non-Whisper models (Parakeet v3, Moonshine, SenseVoice, Zipformer via sherpa-onnx) | **no Hebrew** | small | fast | CPU | Apache/CC | not applicable |
| G. Whisper small/base multilingual (OpenAI) | weak Hebrew | 0.2-0.5 GB | ~1-2 s CPU | CPU | MIT | only as a "fast draft" mode if measured acceptable |

## Recommendation for DeskIT
1. Keep **ivrit-ai/whisper-large-v3-turbo-ct2** as the one model for all users (Apache-2.0, ungated, no HF token, 1.62 GB). Download at first run with snapshot_download(local_dir=%LOCALAPPDATA%\DeskIT\models\...) — concurrent, resumable, dry_run for a size preview, tqdm_class hooked to the dashboard; never ship the model inside the installer. Pin revision= to a commit hash so model updates are deliberate. Set HF_HOME / HF_HUB_OFFLINE per process so the app never touches the user's global HF cache. Owner may publish his own int8-converted copy (~0.8 GB) under his HF account to halve the download; Apache-2.0 allows it with attribution.
2. **Hardware tiers chosen at first run**: (1) NVIDIA GPU detected (nvml/nvidia-smi) -> offer "Install GPU acceleration (1.3 GB from NVIDIA via PyPI)" which pip-installs nvidia-cublas-cu12 + nvidia-cudnn-cu12 into the app's venv and calls os.add_dll_directory on both bin dirs. This avoids bundling NVIDIA libs in the installer (no EULA clickwrap needed; if bundled later the EULAs permit it with a NOTICE). (2) No NVIDIA -> CPU int8, compute_type="int8", cpu_threads=cores, model kept warm; UI shows a live "transcribing" state; honest expectation "about as long as the clip". (3) Optional, user-enabled **Groq cloud fallback** with the user's own free key (owner's key never involved; limits are per Groq org so per-user keys keep quotas separate): consent screen "audio will be sent to Groq", 25 MB cap irrelevant for 10 s clips, language="he".
3. Post-v1: add a whisper.cpp Vulkan engine for AMD/Intel GPU users (owner converts ivrit weights to ggml q8_0, hosts on his HF account, measures Hebrew WER vs CT2 int8 before shipping). Skip DirectML.
4. Ollama: **detect-and-prompt** only (GET http://localhost:11434 -> "Ollama is running"); if absent, hide local-LLM options and link to ollama.com. Do not bundle; Groq/Gemini already cover the LLM passes.

## What the owner must do by hand
- Model: nothing to sign — Apache-2.0, ungated. Add ivrit.ai attribution + Apache notice to About/user guide. Optional: re-convert to int8 or ggml and upload under his own free HF account (one-time `hf auth login` for upload only; users never need a token).
- NVIDIA: with pip-at-first-run, nothing. If he ever bundles cuBLAS/cuDNN DLLs: add NVIDIA EULA acceptance to the installer and the "This software contains source code provided by NVIDIA Corporation." notice.
- Groq: no owner account needed for the fallback; write the user-guide steps for creating a free key at console.groq.com and the consent text; read Groq's privacy/retention terms and quote them on the consent screen.
- Measure on one no-GPU laptop the real CPU int8 latency for a 7 s Hebrew clip before writing the guide's expectations.
- Decide after v1 problem reports whether the whisper.cpp/Vulkan engine is worth adding.

## Sources
- https://huggingface.co/ivrit-ai/whisper-large-v3-turbo-ct2 and /tree/main (license tag, files, sizes)
- https://huggingface.co/ivrit-ai (model list); https://huggingface.co/ivrit-ai/yi-whisper-large-v3-turbo (Yiddish)
- https://console.groq.com/docs/rate-limits ; https://console.groq.com/docs/speech-to-text
- https://pypi.org/project/nvidia-cudnn-cu12/ ; https://pypi.org/project/nvidia-cublas-cu12/#files
- https://docs.nvidia.com/cuda/eula/index.html ; https://docs.nvidia.com/deeplearning/cudnn/backend/latest/reference/eula.html
- https://github.com/SYSTRAN/faster-whisper/issues/1030 ; https://github.com/jaredrhod/backtalk/issues/28 (Windows DLL path)
- https://github.com/ggml-org/whisper.cpp/discussions/3752 ; https://github.com/ggml-org/whisper.cpp/releases ; https://www.phoronix.com/news/Whisper-cpp-1.8.3-12x-Perf
- https://huggingface.co/docs/huggingface_hub/guides/download ; https://huggingface.co/docs/huggingface_hub/en/package_reference/environment_variables
- https://snailtext.app/blog/do-you-need-a-gpu-for-voice-to-text/ (CPU RTF table, secondary)
- https://onnxruntime.ai/docs/execution-providers/DirectML-ExecutionProvider.html ; https://github.com/microsoft/Olive/issues/813
- https://github.com/k2-fsa/sherpa-onnx (model families) ; https://pinggy.io/know_your_port/localhost_11434/ (Ollama port)

## Uncertainties
- CPU latency for turbo int8 on a modern laptop is an estimate (RTF ~0.5-2) extrapolated from S13/S19; no primary 2025-26 measurement on an 8-core laptop was found. Must be measured.
- Hebrew accuracy of a q4/q5/q8 ggml conversion of the ivrit weights is unmeasured.
- whisper.cpp v1.9.4 Windows Vulkan binary names/sizes not verified (GitHub asset list failed to load).
- Groq audio retention / training-use policy for the free tier not read; the "org-level" limits sentence was verified, per-key behaviour not.
- HF card says apache-2.0 but the repo has no LICENSE file; ivrit.ai's site has a separate "The License" page for its datasets — the weights' Apache-2.0 tag on every ivrit-ai model card is taken as authoritative.
- nvidia wheel sizes are for the newest versions (cuDNN 9.26 / cuBLAS 12.9); CTranslate2 4.x needs cuDNN 9 + CUDA 12 — pin the exact versions that work in his venv today.
