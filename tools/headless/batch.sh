#!/usr/bin/env bash
# One batch of 100-year headless Alice campaigns, one per core, resumable (s<seed>.done marks a finished campaign).
# Usage: tools/headless/batch.sh OUT CWD HOME SCEN BIN FIRST_SEED COUNT "core core ..."   e.g. vanilla: CWD=runs/root HOME=runs/home SCEN=6BA00CA6-0.bin
set -uo pipefail
export OUT=$(realpath -m "$1") CWD=$(realpath "$2") MHOME=$(realpath "$3") SCEN=$4 BIN=$(realpath "$5") YEARS=${YEARS:-100}
FIRST=$6; N=$7; read -ra CORES <<< "$8"; mkdir -p "$OUT"
one() {  # one SEED CORE
  local S=$1 C=$2 D=$OUT/s$1
  [ -f "$OUT/s$S.done" ] && return 0
  rm -rf "${D:?}.tmp"; local t0=$(date +%s)
  ( cd "$CWD" && HOME=$MHOME systemd-run --user --scope -q -p MemoryMax=6G -p MemorySwapMax=0 nice -n 19 taskset -c "$C" \
    "$BIN" "$SCEN" -headless -seed "$S" -threads 1 -years "$YEARS" -dump "$D.tmp" ) > "$OUT/s$S.log" 2>&1
  local rc=$?; echo "exit=$rc" >> "$OUT/s$S.log"
  [ $rc -eq 0 ] || { echo "$S FAILED rc=$rc" >> "$OUT/failed.txt"; return 1; }
  for f in "$D.tmp"/*.csv; do zstd -q -f --rm "$f"; done
  mv "$D.tmp" "$D"; echo "$S,$(( $(date +%s) - t0 ))" >> "$OUT/timing.csv"; touch "$OUT/s$S.done"
}
export -f one
# seeds are dealt to cores round-robin; each core runs its seeds one after another
for i in "${!CORES[@]}"; do
  ( for ((k=i; k<N; k+=${#CORES[@]})); do one $((FIRST+k)) "${CORES[$i]}"; done ) &
done
wait
