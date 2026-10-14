# Implementation decisions · 2026-09-24

The user's request now authorizes a working browser app. The plan's first execution unit (P0, P1 validation, P2 preparation) remains the data-quality gate, while P5 is developed against explicitly unresolved records as allowed by §9.1. This does not imply that scientific annotation or P2 human review is complete.

- Python 3.12, SQLite, FastAPI; static HTML/CSS/JavaScript; Electrobun 2.0.1/Bun desktop shell with native WKWebView. The same Python core serves HTTP and local stdio MCP.
- Packaged backend runtime with PyInstaller, not the user's Terminal PATH. macOS arm64 local app bundle; original collection stays external.
- Visual thesis: warm paper surfaces, charcoal typography, muted teal actions; original scientific illustrations dominate.
- Content: topic navigation → searchable artwork gallery → exact-file inspector → persistent selection tray.
- Interaction: restrained gallery entrance, inspector slide, image hover enlargement; reduced-motion respected.
- One provisional representation per file until source mapping is verified. Artwork-level grouping avoids variant domination without inventing PNG/SVG pairings.
- Human/AI visual annotation is not fabricated. Source metadata, title-derived concept candidates, and image measurements remain separate; every file begins in pending visual review.
- Local alias/concept retrieval is the baseline. No unmeasured embedding/LLM accuracy or cost claims.
- Export and scene outputs are constrained to workspace exports/projects. Original input files are read-only. Export verifies current SHA-256.


## Electrobun migration

The follow-up request replaces the hand-written Swift host with `src/bun/index.ts`. Python HTTP and MCP continue to share the existing catalog; no data migration or re-inventory is required. The browser retains its plain HTTP fallback. A sandboxed Electrobun webview has a narrow event-only channel for external links and revealing existing export files. Native requests are validated; symlink/path escapes are rejected. Navigation is restricted to the exact loopback origin.

The packaged worker is launched by absolute resource path, signals readiness over stdout, and is health-checked before navigation. A parent watchdog exits if the desktop process crashes. `before-quit` waits for worker termination, with a bounded kill fallback. Mutable state stays in the selected workspace; desktop selection and logs use Electrobun's userData/userLogs paths.

Electrobun's stable self-extractor failed while installing from the external workspace volume. The build script now unpacks the stable payload into the final `.app` during packaging and ad-hoc signs that real bundle. No first-launch installation rename is required. The older Swift source under `native/` is retained as historical code and is not built.
