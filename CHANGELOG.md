# Changelog

El changelog principal fue movido para ordenar la raíz:

- `docs/CHANGELOG_PROJECT.md`

# Changelog

All notable changes to this project should be documented in this file.

The format is inspired by [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added
- Initial public-ready repository documentation set.

### Changed
- README reorganized with professional installation and usage flow.
- Packaging metadata aligned with MIT license.
- `.gitignore` reinforced for runtime data and local tooling files.

## [v2.0.0] - 2026-04-27

### Added
- Zero-Trust security module in `src/eda/utils/security.py` with global sanitization, strict command whitelist and sensitive-data redaction.
- Enterprise approval flow in orchestrator for critical actions requiring explicit `Sí/No`.
- Sandboxed execution path for learned skills with 30s timeout guard.
- Encrypted memory at rest (Fernet when available) and semantic lightweight vector retrieval fallback.
- Plugin system foundation: `skills/`, `skills/manifest.json`, and `src/eda/plugin_loader.py`.
- Internationalization foundation with `data/resources/locales/es.json` and `src/eda/i18n.py`.
- New telemetry module `src/eda/telemetry.py` for RAM/fallback monitoring.
- New test suite `tests/test_v2_core.py` covering security injection blocks, memory encryption, redaction and approval flow.

### Changed
- `MemoryManager` now applies PII/secret redaction before persistence and includes 30-day retention maintenance.
- Logging now uses a global redaction filter to mask sensitive content.
- Action execution paths (`open_app`, shell command execution) now enforce sanitizer checks.

## [v1.1.0] - 2026-04-27

### Added
- New automated test battery (72+ unit/integration tests) covering intent parsing, orchestrator routing, response quality, and web/app detection.
- GitHub Actions CI workflow for Windows and Ubuntu with Python 3.12.

### Changed
- Voice stabilization: dynamic fallback behavior and guided repair flow when PyAudio is unavailable.
- URL normalization and robust web/app distinction (`open_app`) to prevent `.exe`-style failures for web targets.
- Error handling and sanitization in app opening flow with web-first fallbacks when appropriate.
- Better intent quality split for technical/theoretical/general questions.

### Fixed
- False positives where technical questions were misclassified as `system_info`.
- Web targets like `youtube`, domains, and localhost routes now open directly in browser paths.
