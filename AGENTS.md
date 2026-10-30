# ColliderML Production

## Repository boundaries

- Never auto-commit changes. Only create a commit when the user explicitly requests one; do not invoke tools or pipeline commands that implicitly commit changes.
- User-facing code (the `colliderml` pip package, benchmark tasks, HuggingFace Spaces, and documentation) lives in the **public repo**: [`OpenDataDetector/ColliderML`](https://github.com/OpenDataDetector/ColliderML). `colliderml/` and `benchmarks/` are absent here. The public library's `colliderml.simulate` module auto-clones this repo at a pinned ref (`pipeline-v0.1.0`) for local Docker/Podman simulations.
- **This repo** (`colliderml-production`) is the home for:
  - Pipeline scripts (`scripts/simulation/`, `scripts/postprocessing/`, `scripts/cli/`)
  - FastAPI backend service (`backend/`)
  - Container image workflow (`Dockerfile`, `docker/`, `.devcontainer/`)
  - SFAPI runner and sbatch templates
  - Admin dashboard (`spaces/colliderml-admin/`)
  - Development and production configs (`configs_development/`, `configs_production/`)
- Docker runner arguments such as `simulation/pythia_gen.py` are relative to `scripts/`, not the repo root.
- Root `pyproject.toml` and `setup.py` retain conflicting package metadata; do not use root `pip install -e .` as backend setup.
- `TESTING.md` includes public-repo components no longer present here.

## Backend development and verification

Run these commands from `backend/` (CI uses Python 3.12):

```bash
pip install -e '.[dev]'
pip install polars pyarrow
# Focused, service-free tests:
env -u DATABASE_URL pytest tests/test_cap.py tests/test_abuse.py -v
# Single test selection: pytest tests/test_cap.py::<test_name> -v
```

- The backend installs the public `colliderml[all]>=0.4.0` dependency; its task registry is external to this checkout.
- Full suite: `pytest tests/ -v --tb=short`, after starting Postgres 16, exporting `DATABASE_URL`, and applying **all** `migrations/*.sql` in filename order (`for f in migrations/*.sql; do psql "$DATABASE_URL" -f "$f"; done`). See `.github/workflows/test.yml` for CI settings.
- Use a disposable test database: the autouse fixture resets `e2e_alice` records and the global submission-freeze flag before every test when `DATABASE_URL` is exported, including unit tests. Integration tests skip without that environment variable; setting it only in `.env` does not enable them.
- Local stack: `docker compose up --build`. Compose mounts migrations as first-initialization scripts; an existing `pg_data` volume does not automatically receive migration changes.
- Native server: `uvicorn app.main:app --reload`. Settings load `.env` relative to the working directory and are cached by `get_settings()`; app startup connects to Postgres. Empty SFAPI credentials enable mock job execution, not a mock database.
- CI sets `COLLIDERML_TRACKING_DATASET=ttbar_pu0` and `COLLIDERML_TRACKING_EVAL_RANGE=0:1000`; Compose uses the same small-data defaults.

## Pipeline execution (Docker)

From the repo root:

```bash
# Full Higgs portal pipeline
./scripts/cli/run_pipeline_docker.sh --channel higgs_portal

# Full ttbar pipeline
./scripts/cli/run_pipeline_docker.sh --channel ttbar

# Single stage
./scripts/cli/run_docker.sh simulation/pythia_gen.py \
    configs_development/docker_test/higgs_portal/pythia_config.yaml

# Prepared 10-event ttbar PU0 run
bash scripts/cli/run_ttbar_pu0_docker.sh
```

| Script | Purpose |
|--------|---------|
| `scripts/cli/run_pipeline_docker.sh` | Run a complete pipeline (all stages) |
| `scripts/cli/run_docker.sh` | Run a single stage in Docker |
| `scripts/cli/run_ttbar_pu0_docker.sh` | Prepared 10-event ttbar PU0 run |
| `scripts/cli/setup_container_env.sh` | Environment setup inside the container (sourced automatically) |

- Full Docker runner supports `higgs_portal` and `ttbar`; it runs generation → detector simulation → digitization/reconstruction → parquet conversion. ttbar prepends MadGraph init/generation and copies HepMC from `runs/all/0/` to `runs/0/` for Pythia. It accepts `--skip-conversion` for configs that emit native parquet.
- `run_ttbar_pu0_docker.sh` uses the local `colliderml/acts-arrow:0.2.2-arrow-dev` image and skips legacy conversion. Its cache override points directly at `../data/production/`, where the existing dependencies were transferred; outputs default to `../data/production/runs/ttbar_pu0_dev_seed42/`.
- Both Docker runners activate `/opt/acts-arrow/setup.sh` after the common environment when available.
- Runners source `setup_container_env.sh` inside the physics container; a normal Python environment is insufficient for ACTS/DD4hep/Geant4.
- Store simulation dependencies and outputs outside the repo under `../data/production`, resolved relative to the repository root (on this machine: `/Users/chrisizeh/Documents/PhD/data/production`). Docker runners default to `../data/production/cache` for dependencies and `../data/production/runs/<channel>` for full-pipeline output (`runs/single-stage` for the single-stage runner). Stage files are nested under `runs/<RUN_ID>/` within that output directory. Set `OUTPUT_DIR` to a fresh sample directory for independent datasets.
- Overrides: `COLLIDERML_CACHE` (host cache), `OUTPUT_DIR`, `CONTAINER_IMAGE`, `SEED`; the single-stage runner also accepts `RUN_ID`. Container mounts remain `/cache` and `/output`.
- The full runner's `EVENTS` comment is misleading: that variable is not consumed. Event counts come from configs; single-stage extra arguments are forwarded to the stage script.

### Docker container

**Default image:** `ghcr.io/opendatadetector/sw:0.2.2_linux-ubuntu24.04_gcc-13.3.0`

Contains: MadGraph 5.3.9, Pythia 8.313, DD4hep (ddsim), Geant4 11.3, ROOT 6.38, HepMC3 3.3, ACTS (main).

- **Python:** System python3.12 is used. ACTS bindings (.cpython-313) are symlinked under `/tmp/acts` so `import acts` works.
- **ODD:** OpenDataDetector v5.0.0 (the tag the released ColliderML dataset uses). The setup script prefers a baked-in ODD at `/opt/odd` + `/opt/odd-install`; otherwise it clones from CERN GitLab into `<cache>/odd-v5/` and builds `libOpenDataDetector.so` into `<cache>/odd-v5-install/`.
- **Geant4 data:** ~2 GB of physics datasets, auto-downloaded and cached in `<cache>/g4data/`.
- **Pip packages:** `pyarrow`, `uproot`, `pandas`, `awkward`, `h5py`, `tqdm`, `pyhepmc`, `psutil`, `pyedm4hep` — installed to `<cache>/pip/` on first run.
- **No network inside container:** the runner scripts fetch network dependencies (MG5aMC_PY8_interface source, `bc` .deb) on the host before launching Docker. Inside the container, `setup_container_env.sh` handles building ODD, compiling the interface, and installing cached packages.

Cache layout (`<cache>` = `../data/production/cache` by default, mounted at `/cache`):
```
<cache>/
  odd-v5/                 # ODD v5.0.0 source (only if no baked-in /opt/odd)
  odd-v5-install/         # Built libOpenDataDetector.so
  g4data/                 # Geant4 physics datasets (~2 GB)
  pip/                    # Python packages for postprocessing
  MG5aMC_PY8_interface/   # Interface source + compiled binary
  bc_*.deb                # bc package for MadGraph shower
```

### Pipeline stages

**Higgs Portal (Pythia-only generation)** — configs: `configs_development/docker_test/higgs_portal/`

| # | Stage | Config | Script | Time (10 evts) |
|---|-------|--------|--------|----------------|
| 1 | Pythia generation | `pythia_config.yaml` | `simulation/pythia_gen.py` | ~8s |
| 2 | DDSim simulation | `simulation_config.yaml` | `simulation/ddsim_run.py` | ~10 min |
| 3 | Digi + Reco | `digitization_config.yaml` | `simulation/digi_and_reco.py` | ~11s |
| 4 | Parquet conversion | `convert_all.yaml` | `postprocessing/convert_all.py` | ~5s |

**ttbar (MadGraph + Pythia)** — configs: `configs_development/docker_test/ttbar/`

| # | Stage | Config | Script | Time (est.) |
|---|-------|--------|--------|-------------|
| 1 | MadGraph init | `madgraph_init_config.yaml` | `simulation/madgraph_init.py` | ~5-20 min |
| 2 | MadGraph gen | `madgraph_generation_config.yaml` | `simulation/madgraph_gen.py` | ~1-2 min |
| 3 | Pythia generation | `pythia_config.yaml` | `simulation/pythia_gen.py` | ~10s |
| 4 | DDSim simulation | `simulation_config.yaml` | `simulation/ddsim_run.py` | ~10 min |
| 5 | Digi + Reco | `digitization_config.yaml` | `simulation/digi_and_reco.py` | ~11s |
| 6 | Parquet conversion | `convert_all.yaml` | `postprocessing/convert_all.py` | ~5s |

Script paths are relative to `scripts/`. Digi can now emit native ACTS parquet, replacing `convert_all` (use `--skip-conversion`).

### Expected output

```
<OUTPUT_DIR>/runs/0/
  merged_events.hepmc3       # Pythia output (merged signal + pileup)
  events.hepmc3              # MadGraph output (ttbar only)
  edm4hep.root               # DDSim output (~220 MB for 10 events)
  measurements.root          # Digitized tracker hits
  particles.root             # Truth particles
  tracksummary_ambi.root     # Reconstructed tracks
```

### Tested pipeline results

Higgs Portal (10 events, pileup mu=10)

| Stage | Status | Output | Time |
|-------|--------|--------|------|
| Pythia + pileup | **PASS** | `merged_events.hepmc3` (11 MB) | 8s |
| DDSim (Geant4) | **PASS** | `edm4hep.root` (220 MB) | ~10 min |
| Digi + Reco | **PASS** | `measurements.root`, `particles.root`, `tracksummary_ambi.root` | 11s |
| Parquet conversion | **BLOCKED** | needed `pyedm4hep` (since added to install list) | — |

ttbar NLO (5 events, pileup mu=10)

| Stage | Status | Output | Time |
|-------|--------|--------|------|
| MadGraph init (NLO) | **PASS** | `madgraph_process.tgz` (54 MB), σ=794 pb | ~8 min |
| MadGraph gen + shower | **PASS** | `events.hepmc.gz` (3.6 MB) | ~3 min |
| Pythia merge + pileup | **PASS** | `merged_events.hepmc3` (8.6 MB) | 6s |
| DDSim (Geant4) | **PASS** | `edm4hep.root` (106 MB) | ~7 min |
| Digi + Reco | **PASS** | `measurements.root`, `particles.root`, `tracksummary_ambi.root` | 6s |
| Parquet conversion | **BLOCKED** | needed `pyedm4hep` (since added to install list) | — |

### ACTS API notes (container version)

The ACTS build in this container uses the main branch (version 999.999.999). Key differences from released versions:

- `RootParticleWriter` / `RootMeasurementWriter` → `acts.examples.root` module
- `PodioReader` → `acts.examples.edm4hep` module
- `addCounter(geoIds, min, max)` instead of `addCounter(geoIds, count)`

### Troubleshooting

- **"ODD_PATH not set":** The setup script handles this. If manual: `export ODD_PATH=/opt/odd` (or `<cache>/odd-v5`).
- **"libOpenDataDetector.so not found":** Rebuild into `<cache>/odd-v5-install` from `<cache>/odd-v5` with `cmake ... -DCMAKE_INSTALL_PREFIX=odd-v5-install && make install`.
- **"No module named 'acts'":** The setup script symlinks ACTS Python bindings. Check `/tmp/acts` exists.
- **Geant4 data missing:** Run `download_geant4_datasets.sh` inside the container, or populate `<cache>/g4data/`.
- **"No module named 'pyedm4hep'":** Ensure `pyedm4hep` is in the pip install list in `setup_container_env.sh`.

## HPC execution

- Entrypoint: `python scripts/cli/run_stage.py <config.yaml>`. Configure site paths in `scripts/cli/env_setup.yaml`. Execution mode is CLI override → `job_config.execution_mode` → `distributed_slurm`; multiple configs require `multi_node_slurm`.
- **Do not run `run_stage.py` while its automatic commit behavior is enabled:** it can `git add .` and commit even with `--dry-run`. Dry-run controls batch submission, not the earlier commit/config-snapshot phase. Use the Docker runners or direct stage scripts instead. It rejects main/master unless `--allow-master` is supplied.
- Preserve the documented storage contract: simulation/public datasets are immutable; processing space holds mutable intermediates.

## Parquet regression checks

- Root `tests/regression/` is separate from backend tests. It requires generated parquet fixtures; unset/missing fixture directories cause skips, not successful data validation. See `tests/regression/README.md` for generation commands.
- Focused comparison: `COLLIDERML_V1_PARQUET_DIR=<legacy-parquet> COLLIDERML_ACTSNATIVE_PARQUET_DIR=<native-parquet> pytest tests/regression/test_actsnative_vs_v1.py -v` (requires Polars/NumPy).
- Legacy tracker rows represent measurements; ACTS-native rows represent simhits. Particle IDs also differ between pipelines: use the fixture's per-event kinematic mapping rather than comparing raw IDs.

## Admin Space deployment

- `.github/workflows/sync-spaces.yml` syncs only `spaces/colliderml-admin/` on relevant `staging` pushes or manual dispatch. It uploads code but does not set Space secrets; older docs describing five Spaces are stale.

## Container image fix checklist

The current container (`ghcr.io/opendatadetector/sw:0.2.2`) has issues to fix in the next image build.

### 1. Missing `bc` command (blocks MadGraph shower)

MadGraph checks for `bc` to calculate shower parameters. Without it, MadGraph falls back to `noshower` mode and only produces LHE files (no HepMC output).

**Fix:** `RUN apt-get update && apt-get install -y bc`

**Workaround (implemented):** the runners download a `bc` .deb into the cache on the host; `setup_container_env.sh` installs it with `dpkg -i`.

### 2. mg5amc_py8_interface incompatible with Pythia 8.3+ (blocks ttbar NLO+PS)

The container ships Pythia 8.313, but the `mg5amc_py8_interface` (C++ driver MadGraph uses to steer Pythia8 showering) only works with Pythia 8.2.x — a [known upstream issue](https://gitlab.com/Pythia8/releases/-/issues/24). Without it, ttbar NLO events cannot be showered inside MadGraph; only LHE is produced, which the downstream Pythia merge stage cannot read (expects HepMC).

**Fix options (choose one):**
1. **Pre-install the interface with `--pythia8_makefile`** — dynamic HepMC2 linking; requires `libHepMC.so` at runtime (present in the container):
   `cd /path/to/MG5aMC_PY8_interface && python compile.py /pythia8/prefix --pythia8_makefile`
2. **Add Pythia 8.2.x alongside 8.313** (e.g. 8.245 via spack) and set `pythia8_path` in `mg5_configuration.txt`.
3. **Port the interface to the Pythia 8.3 API** — cleanest long-term, low upstream priority.

**Workaround (implemented in `setup_container_env.sh`):** `compile.py --pythia8_makefile` fails because the spack Pythia8 lacks HepMC2 support in its `Makefile.inc`, so the interface is compiled directly with explicit HepMC2 flags:

```bash
# Clone interface source on host (done by the runners):
git clone https://github.com/mg5amcnlo/MG5aMC_PY8_interface.git <cache>/MG5aMC_PY8_interface

# Compile inside container (done automatically):
g++ MG5aMC_PY8_interface.cc -o MG5aMC_PY8_interface \
    -I$PY8/include -I$HEPMC2/include -I$ZLIB/include \
    -O2 -std=c++20 -fPIC -pthread -DGZIP \
    -L$PY8/lib -Wl,-rpath,$PY8/lib -lpythia8 \
    -L$HEPMC2/lib -Wl,-rpath,$HEPMC2/lib -lHepMC \
    -L$ZLIB/lib -Wl,-rpath,$ZLIB/lib -lz -ldl
```

This compiles against Pythia 8.313 + HepMC2 (deprecation warnings only). The binary is cached in `<cache>/MG5aMC_PY8_interface/`.

References: [MG5 Launchpad: HepMC2 static linking](https://answers.launchpad.net/mg5amcnlo/+question/693533) · [Pythia GitLab: MG5-PY8 interface issue](https://gitlab.com/Pythia8/releases/-/issues/24) · [MG5 Launchpad: Pythia8 path config](https://answers.launchpad.net/mg5amcnlo/+question/709602)

### 3. Missing `pyedm4hep` pip package (blocks legacy parquet conversion)

`postprocessing/convert_all.py` requires `pyedm4hep`. **Fix:** `pip install pyedm4hep` in the image. Already added to the `setup_container_env.sh` pip install list.

### 4. ACTS Python bindings path

ACTS installs Python files in `<prefix>/python/` but they must be importable as `import acts`. The setup script symlinks `python/` → `/tmp/acts`.

**Fix:** the ACTS spack package should install to `<prefix>/lib/pythonX.Y/site-packages/acts/`, or add an `acts.pth` file.
