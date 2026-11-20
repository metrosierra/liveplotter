# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and versions follow [Semantic Versioning](https://semver.org/).

## [0.1.0] - 2026-11-20

First packaged release.

### Added
- Installable package (`src/liveplotter/`) built with uv (`pyproject.toml`, `uv.lock`).
- Optional extras for the Qt binding: `pyqt5`, `pyqt6`, `pyside6`.
- `liveplotter.__version__`.
- Docstrings and comments throughout; README; examples; `CITATION.cff`.

### Changed
- Modules moved from the repository root into the package and switched to
  relative imports. The public entry point is now `from liveplotter import LivePlotAgent`.
- Qt imports go through `pyqtgraph.Qt` (binding-agnostic) instead of `PyQt5` directly.
- Heatmap colour bar: `ColorBarItem(cmap=...)` → `ColorBarItem(colorMap=...)`.
  `cmap` was removed in pyqtgraph 0.13.4, so heatmaps failed with newer pyqtgraph.
  Behaviour is unchanged on older versions.
