#!/usr/bin/env bash
set -euo pipefail

case "${1:-}:$#" in
    capture:2|original:2|patched:3) ;;
    *)
        echo "Usage: ACCEPT_EULA=Y bash scripts/run-repro.sh {capture|original} NEW_RESULTS_DIR" >&2
        echo "       ACCEPT_EULA=Y bash scripts/run-repro.sh patched NEW_RESULTS_DIR CAPTURE_RESULTS_DIR" >&2
        exit 2
        ;;
esac
if [[ ${ACCEPT_EULA:-} != Y ]]; then
    echo "Read the NVIDIA terms and set ACCEPT_EULA=Y to launch." >&2
    exit 2
fi

mode=$1
capture_data=
if [[ $mode == patched ]]; then
    if [[ ! -r $3/exit-code.txt || $(<"$3/exit-code.txt") != 0 ]]; then
        echo "Patched timing requires a successful capture results directory." >&2
        exit 2
    fi
    capture_data=$(cd -- "$3/data" && pwd -P)
fi

gpu=$(nvidia-smi --query-gpu=name --format=csv,noheader)
if [[ $gpu != "NVIDIA RTX PRO 6000 Blackwell Server Edition" ]]; then
    echo "This reference configuration requires exactly one visible RTX PRO 6000 Blackwell Server Edition GPU." >&2
    exit 2
fi

bench=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
image=nvcr.io/nvidia/isaac-sim@sha256:783444c706538aa76cf5126e911ddc5e618779e6105305ad4af4260362a30aa9
expected=sha256:2d4ebfef053f740b634e30723e38ed736255f677553425ef35552437d74c3b21
read -r image_id image_user < <(docker image inspect --format '{{.Id}} {{.Config.User}}' "$image")
if [[ $image_id != "$expected" || $image_user != isaac-sim ]]; then
    echo "Unexpected Docker image ID or image user." >&2
    exit 2
fi

mkdir -- "$2"
results=$(cd -- "$2" && pwd -P)
printf '%s %s\n' "$image_id" "$image_user" > "$results/image.txt"
mkdir -- "$results/data"
sudo chown "1234:$(id -g)" "$results/data"
sudo chmod 2770 "$results/data"
mounts=(
    --mount "type=bind,source=$bench,target=/bench,readonly"
    --mount "type=bind,source=$results/data,target=/results"
)
if [[ -n $capture_data ]]; then
    mounts+=(--mount "type=bind,source=$capture_data,target=/verified-capture,readonly")
fi

exit_code=0
docker run --rm --interactive --pull never --runtime=nvidia --gpus all --network bridge \
    --label purpose=isaac-warehouse-repro --cidfile "$results/container.cid" \
    --env ACCEPT_EULA=Y --env PRIVACY_CONSENT=N --env NVIDIA_DRIVER_CAPABILITIES=all \
    --env PYTHONDONTWRITEBYTECODE=1 --env ISAAC_SIM_IMAGE_ID="$image_id" \
    --env HOME=/results/home --env XDG_CACHE_HOME=/results/home/.cache \
    --env XDG_CONFIG_HOME=/results/home/.config \
    "${mounts[@]}" \
    --workdir /results --entrypoint /bin/bash "$image" -s -- "$mode" \
    > "$results/console.log" 2>&1 <<'CONTAINER' || exit_code=$?
set -euo pipefail
umask 0022
mkdir -p "$XDG_CACHE_HOME" "$XDG_CONFIG_HOME"
if [[ $1 == capture ]]; then
    /isaac-sim/python.sh /bench/scripts/capture-warehouse.py /results/capture
    /isaac-sim/python.sh /bench/scripts/verify-frame.py \
        /results/capture/frame-720p.png /results/capture/capture.json > /results/frame-gate.json
    exit 0
fi

vendor=/isaac-sim/standalone_examples/benchmarks/benchmark_camera.py
script=$vendor
frames=120
if [[ $1 == patched ]]; then
    /isaac-sim/python.sh /bench/scripts/verify-frame.py \
        /verified-capture/capture/frame-720p.png /verified-capture/capture/capture.json \
        > /results/frame-gate.json
    script=/results/benchmark_camera.py
    /isaac-sim/python.sh /bench/scripts/stage-camera.py "$vendor" "$script" > /results/stage.json
    frames=30
fi

benchmark_args=(--num-cameras 1 --resolution 1280 720 --num-frames "$frames" \
    --gpu-frametime --backend-type JSONFileMetrics)
printf '%q ' /isaac-sim/python.sh "$script" "${benchmark_args[@]}" > /results/benchmark-command.txt
printf '\n' >> /results/benchmark-command.txt
benchmark_exit=0
/isaac-sim/python.sh "$script" "${benchmark_args[@]}" || benchmark_exit=$?
printf '%s\n' "$benchmark_exit" > /results/benchmark-exit.txt
shopt -s nullglob
metrics=(/tmp/metrics*.json)
if [[ -n ${metrics[0]:-} ]]; then
    mkdir /results/metrics
    cp -- "${metrics[@]}" /results/metrics/
elif (( benchmark_exit == 0 )); then
    echo "Vendor benchmark did not write a metrics JSON file." >&2
    exit 1
fi
exit "$benchmark_exit"
CONTAINER
printf '%s\n' "$exit_code" > "$results/exit-code.txt"
exit "$exit_code"
