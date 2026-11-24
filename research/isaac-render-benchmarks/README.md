<!-- register: research repository README | reader: Isaac Sim users and maintainers | consumed: skim the result and run the commands -->
# Check that the Isaac Sim camera benchmark rendered

On one NVIDIA RTX PRO 6000 Blackwell Server Edition, the stock Isaac Sim 6.0.1 warehouse benchmark reported **57.11 app updates/s** and **0.0 ms mean GPU frame time** in a one-camera run that requested 120 frames at 1280×720. The investigation separately recorded empty RGB and depth buffer probes.

A recovery run loaded a stage with 3,473 warehouse meshes using `Usd.Stage.LoadAll`, attached it to Kit, and captured a **1280×720 RGB frame**. The historical receipt records its digest and verification results. The image is omitted. Some later patched timings again reported zero GPU frame time after a separate successful capture. The historical empty buffers and zero timing were recorded in separate runs. [Run records](reference/timing-measurements.json)

## Earlier fresh containers reproduced zero GPU timing and a missing PNG

The revised stock diagnostic exited 0 and reported **60.533 app updates/s** and **0.0 ms mean GPU frame time** across 119 samples. In a separate fresh container, the revised capture exited 1 after Replicator timed out waiting for its writer. The capture directory contained no PNG. Kit also segfaulted during teardown. The 30-frame diagnostic and the matched 200-frame repeat were skipped because the frame check failed.

An earlier capture helper also exited 1 with no PNG. A separate variant that attached all Hydra engines reported multiple engines and stalled in the RTX command list. Those trials used an earlier capture helper. [Live validation records](reference/timing-measurements.json)

## Waiting for RTX before stage attachment restored warehouse capture

The helper now waits for Kit's default USD context to report one RTX engine before attaching the warehouse. With that wait as the only change, BasicWriter produced a valid 1280×720 image with no writer-drain warnings. The launcher still exited 1 during Kit shutdown.

The current helper allows 20 minutes for stage attachment, checks whether the attachment completed after each Kit update, and uses fast shutdown with an explicit failure exit. In two fresh containers, the launcher exited 0 and the independent PNG check passed. The warehouse had 3,473 meshes. One cold run spent 247 seconds inside a single Kit update during attachment. [Capture run records](reference/timing-measurements.json)

## Run the stock timing diagnostic

Use a Linux host with exactly one visible, idle RTX PRO 6000 Blackwell Server Edition GPU, Docker with the NVIDIA Container Toolkit, outbound access to NVIDIA's public warehouse assets, and permission to assign ownership of a fresh results directory. The reference driver was 580.173.02. Read the NVIDIA terms before setting `ACCEPT_EULA=Y`.

```bash
cd research/isaac-render-benchmarks
docker pull nvcr.io/nvidia/isaac-sim@sha256:783444c706538aa76cf5126e911ddc5e618779e6105305ad4af4260362a30aa9
results=$(mktemp -d)
ACCEPT_EULA=Y bash scripts/run-repro.sh original "$results/original"
```

The launcher runs the installed vendor script with one camera at 1280×720, requesting 120 frames and collecting GPU timing. It selects the vendor JSON backend so the measurements can be retained. You can run this diagnostic independently of capture. If the historical symptom recurs, benchmark-phase Mean GPU Frametime will report zero while the app-update rate can remain positive. The stock mode does not record a mesh count, so treat its numbers here as diagnostic.

Both timing modes retain the invoked command in `data/benchmark-command.txt`, the vendor process exit in `data/benchmark-exit.txt`, and vendor JSON in `data/metrics/` when produced. The outer process records its exit in `exit-code.txt` and the container log in `console.log`. Exit 0 and a retained metrics file establish that the launch returned and wrote metrics.

## Verify a 720p warehouse frame before patched timing

```bash
if ACCEPT_EULA=Y bash scripts/run-repro.sh capture "$results/capture"; then
  cat "$results/capture/data/frame-gate.json"
elif test -f "$results/capture/exit-code.txt"; then
  cat "$results/capture/exit-code.txt"
  tail -n 40 "$results/capture/console.log"
fi
```

The launcher uses the pinned image's `isaac-sim` user (UID 1234), a fresh writable home and cache per launch, bridge networking, and telemetry opt-out. The receipt records the PNG digest, GPU, renderer, asset URL and observed Docker image ID. The verifier decodes the PNG and requires at least 16 distinct sampled RGB colors. On success, open `capture/data/capture/frame-720p.png` under the results root and check for visible warehouse geometry. [Capture source and stage URL](scripts/capture-warehouse.py) · [Verifier](scripts/verify-frame.py)

After the capture and visual checks pass, run the 30-frame diagnostic. The launcher rereads the PNG and receipt before it runs the hash-checked stage-load patch. The patch preserves NVIDIA's timing loop.

```bash
ACCEPT_EULA=Y bash scripts/run-repro.sh patched "$results/patched" "$results/capture"
```

To assess patched timing, require exit 0 in `data/benchmark-exit.txt`, a successful warehouse attachment with a positive mesh count in `console.log`, and a positive `benchmark_camera benchmark Mean GPU Frametime` in the retained benchmark-phase JSON. The historical camera results requested 200 frames per repeat. The two diagnostics use different frame counts and serve separate evidence checks.

## Waiting for RTX after attachment restored GPU timing

After a verified capture, the unchanged 30-frame diagnostic loaded all 3,473 meshes and reported 353.357 app updates/s. All 29 GPU samples were zero. That result kept the historical 200-frame repeat gated.

A second stage loader waited for the default USD context to report exactly one RTX engine **after** warehouse attachment and before camera creation. The camera pose, 15 warmup updates and measured vendor loop stayed the same. The 30-frame run reported 148.810 app updates/s and 2.93 ms mean GPU time, with 29 positive samples. A fresh 200-frame run using the same loader reported 122.399 app updates/s and 2.89 ms, with 199 positive samples. These runs use a different startup sequence from the historical one-camera table below. [Timing records](reference/timing-measurements.json)

To reproduce the RTX-ready 30-frame diagnostic on Linux, start from the benchmark directory and the verified capture above.

```bash
cp -R . "$results/rtx-ready"
(cd "$results/rtx-ready" && patch -p1 -i reference/rtx-ready-timing.patch)
ACCEPT_EULA=Y bash "$results/rtx-ready/scripts/run-repro.sh" patched "$results/ready-30" "$results/capture"
```

Before running 200 frames, confirm both exits are zero, the console reports 3,473 meshes and one RTX engine, and all 29 benchmark-phase GPU frame-time samples are positive. To repeat at 200 frames, change only the requested frame count in a separate copy of the launcher.

```bash
cp -R "$results/rtx-ready" "$results/rtx-ready-200"
sed -i 's/^    frames=30$/    frames=200/' "$results/rtx-ready-200/scripts/run-repro.sh"
ACCEPT_EULA=Y bash "$results/rtx-ready-200/scripts/run-repro.sh" patched "$results/ready-200" "$results/capture"
```

Check for 199 positive benchmark-phase GPU frame-time samples in the 200-frame result. The measured loop reports application updates per second. BasicWriter ran in the separate frame verification step.

## Reference measurements on one RTX PRO 6000

The camera workload used RTX Real-Time 2.0. Estimated camera-frames/s multiplies the vendor app-update FPS by camera count. Synthetic data generation (SDG) rows use the vendor Replicator images/s field. Concurrent SDG totals sum each worker's full-interval average. Five groups have measured overlap. The first two-worker group has about 19 seconds of overlap estimated from phase timestamps.

| Workload | Accepted repeats | Median | Range |
|---|---:|---:|---:|
| 1 camera | 2 | 67.94 estimated camera-frames/s | 67.57 to 68.31 |
| 2 cameras | 3 | 90.17 estimated camera-frames/s | 87.68 to 91.20 |
| 4 cameras | 3 | 295.42 estimated camera-frames/s | 189.39 to 299.62 |
| 8 cameras | 3 | 318.86 estimated camera-frames/s | 311.77 to 319.10 |
| SDG RGB and depth | 3 | 50.04 images/s | 48.39 to 50.48 |
| SDG all annotations | 3 | 19.17 images/s | 19.10 to 19.34 |
| SDG two workers, 12 CPUs each | 3 | 32.12 images/s | 31.61 to 32.61 |
| SDG three workers, 8 CPUs each | 3 | 37.44 images/s | 35.94 to 39.77 |
| Isaac Lab RGB Cartpole, adapted RSL-RL policy | 3 | 10,965.8 total FPS | 10,929.0 to 11,042.8 |

The SDG reference used two 720p cameras per worker with disk writes disabled. The RGB training result used the Isaac Lab 3.0.0-beta2-post1 image, RSL-RL 5.0.1, 1,024 environments, 10 iterations and seed 42. Its process-local RGB policy used the installed convolutional network and a channel transpose. The adapter source is outside this reference. The table uses the cohorts listed in the run records. The short path-tracing and non-RL Lab runs are supplemental observations. [Per-run evidence and cohorts](reference/timing-measurements.json) · [Recomputed summary](reference/verified-summary.json)

## The 1080p write run stored 5.38 GB

Four cameras produced 40 RGB images and their annotations over a **655.660 s** capture window. Point clouds and motion vectors contributed 86% of the 5.38 GB across 1,161 files. The scene, camera count, resolution, and synchronization differed from the write-disabled series, so these runs cannot isolate disk cost. [File inventory](reference/write-file-inventory.json)

The archived write record gives the exact vendor flags, wrapper digest, successful scene attachment and measured capture window. A 600-second scheduling cutoff allowed the final in-flight step to finish before the writer drained. File counts and bytes came from the writer output tree. The included wrapper illustrates the historical method. Its current version has not been run from the clean checkout. [Write record](reference/timing-measurements.json) · [Write wrapper](scripts/timed_repeat.py)
