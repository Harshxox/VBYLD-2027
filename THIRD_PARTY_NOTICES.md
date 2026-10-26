# Third-party notices

ErgoCare's own code is MIT-licensed (see [LICENSE](LICENSE)). It uses or bundles the following, each under its own license.

## Bundled in this repository

| Component | Where | License |
|---|---|---|
| Chart.js 4.4.0 | `public/vendor/chart-4.4.0.umd.min.js` | MIT — © 2023 Chart.js Contributors |
| Three.js r128 | `public/vendor/three-r128.min.js` | MIT — © 2010-2021 Three.js Authors |
| Noto Sans Devanagari, Noto Sans Kannada | `ergo_ml_backend/app/fonts/` | SIL Open Font License 1.1 — © 2022 The Noto Project Authors (full text in `ergo_ml_backend/app/fonts/OFL.txt`) |

## Downloaded at install / first run (not stored in the repository)

| Component | Used for | License |
|---|---|---|
| sentence-transformers/all-MiniLM-L6-v2 (ONNX build via FastEmbed) | AI answer matcher | Apache 2.0 |
| FastAPI, Pydantic, SQLAlchemy, Uvicorn | Backend | MIT / BSD (see each package) |
| ReportLab | PDF reports | BSD |
| FastEmbed, NumPy | Embeddings | Apache 2.0 / BSD |
| Vite, TypeScript | Web app build | MIT / Apache 2.0 |
| SparkFun MAX3010x Arduino library | ESP32 firmware (installed via Arduino IDE) | see the library's own license file |

Google Fonts (Instrument Serif, DM Sans, Playfair Display, Outfit) are loaded by the web page from fonts.googleapis.com under the SIL Open Font License.
