#!/usr/bin/env bash
# ============================================================================
# run-warmup.sh
# ----------------------------------------------------------------------------
# Launches a one-off ECS Fargate task that runs scripts/nightly_batch.py with
# the right --skip-* flags for the requested phase. Replaces the copy-paste
# JSON workflow we were doing by hand (build container-overrides JSON, look
# up subnet/SG, aws ecs run-task, then aws logs tail).
#
# Network config (subnets, security group, assignPublicIp) is pulled live
# from the `qsight-backend` service so we don't drift if VPC/SG changes.
# Task definition defaults to the `qsight-backend` family (LATEST revision).
#
# Auth: uses your active AWS profile. The QmetrumOpsPolicy attached to
# qmetrum-ops grants ecs:RunTask + iam:PassRole on the two qsight task roles.
#
# Examples:
#   # Re-warm TSLA's forecast cache (Phase 4 only)
#   ./scripts/run-warmup.sh --symbols=TSLA --phase=forecast --watch
#
#   # Re-run Phase 5 portfolios after a Phase 4 cache update
#   ./scripts/run-warmup.sh --phase=portfolios --watch
#
#   # Full nightly on a custom universe
#   ./scripts/run-warmup.sh --symbols=SPY,QQQ,AAPL --phase=full
# ============================================================================
set -euo pipefail

REGION="${REGION:-eu-north-1}"
CLUSTER="${CLUSTER:-qsight-cluster}"
SERVICE="${SERVICE:-qsight-backend}"
TASK_DEF="${TASK_DEF:-qsight-backend}"
CONTAINER="${CONTAINER:-qsight-backend}"
LOG_GROUP="${LOG_GROUP:-/ecs/qsight-backend}"

SYMBOLS=""
PHASE="forecast"
WATCH=0
DRY_RUN=0

usage() {
  sed -n '2,29p' "$0" | sed 's/^# \{0,1\}//'
  cat <<EOF

Options:
  --symbols=<csv>     CSV of tickers to forecast. Empty = nightly_batch's "key assets" default.
  --phase=<mode>      forecast | portfolios | full      (default: forecast)
                        forecast    — Phase 4 only      (--skip-returns --skip-risk --skip-portfolios)
                        portfolios  — Phase 5 only      (--skip-returns --skip-forecasts --skip-risk)
                        full        — all five phases
  --task-def=<fam>    Task definition family[:rev]      (default: ${TASK_DEF})
  --region=<region>   AWS region                        (default: ${REGION})
  --cluster=<name>    ECS cluster                       (default: ${CLUSTER})
  --watch             Tail CloudWatch logs after launch until task stops.
  --dry-run           Print the run-task JSON and exit.
  -h, --help          Show this help.
EOF
  exit "${1:-0}"
}

for arg in "$@"; do
  case "$arg" in
    --symbols=*)   SYMBOLS="${arg#*=}" ;;
    --phase=*)     PHASE="${arg#*=}" ;;
    --task-def=*)  TASK_DEF="${arg#*=}" ;;
    --region=*)    REGION="${arg#*=}" ;;
    --cluster=*)   CLUSTER="${arg#*=}" ;;
    --watch)       WATCH=1 ;;
    --dry-run)     DRY_RUN=1 ;;
    -h|--help)     usage 0 ;;
    *)             echo "Unknown arg: $arg" >&2; usage 1 ;;
  esac
done

case "$PHASE" in
  forecast)    SKIPS="--skip-returns --skip-risk --skip-portfolios" ;;
  portfolios)  SKIPS="--skip-returns --skip-forecasts --skip-risk" ;;
  full)        SKIPS="" ;;
  *)           echo "Unknown phase: $PHASE (want forecast|portfolios|full)" >&2; exit 1 ;;
esac

SYMBOLS_FLAG=""
if [[ -n "$SYMBOLS" ]]; then
  SYMBOLS_FLAG="--forecast-symbols=$SYMBOLS"
fi

# Build the python invocation the container will run.
CMD="python scripts/nightly_batch.py ${SKIPS} ${SYMBOLS_FLAG}"
CMD="$(echo "$CMD" | tr -s ' ')"  # collapse double spaces from empty SKIPS/SYMBOLS_FLAG

echo "[run-warmup] phase=$PHASE  symbols='${SYMBOLS:-<key assets>}'  task-def=$TASK_DEF"
echo "[run-warmup] container command: $CMD"

# Pull live network config from the running service so we don't drift.
NET_JSON="$(aws --region "$REGION" ecs describe-services \
  --cluster "$CLUSTER" --services "$SERVICE" \
  --query 'services[0].networkConfiguration.awsvpcConfiguration' \
  --output json)"

if [[ -z "$NET_JSON" || "$NET_JSON" == "null" ]]; then
  echo "[run-warmup] ERROR: could not read networkConfiguration from $SERVICE in $CLUSTER" >&2
  exit 2
fi

OVERRIDES_FILE="$(mktemp -t run-warmup-overrides.XXXXXX.json)"
trap 'rm -f "$OVERRIDES_FILE"' EXIT

cat > "$OVERRIDES_FILE" <<JSON
{
  "containerOverrides": [
    {
      "name": "$CONTAINER",
      "command": ["bash", "-c", "echo '[run-warmup] starting'; exec $CMD"]
    }
  ]
}
JSON

if [[ "$DRY_RUN" == "1" ]]; then
  echo "[run-warmup] --dry-run: would launch with overrides:"
  cat "$OVERRIDES_FILE"
  echo
  echo "[run-warmup] networkConfiguration:"
  echo "$NET_JSON" | sed 's/^/  /'
  exit 0
fi

RESULT="$(aws --region "$REGION" ecs run-task \
  --cluster "$CLUSTER" \
  --task-definition "$TASK_DEF" \
  --launch-type FARGATE \
  --platform-version LATEST \
  --network-configuration "awsvpcConfiguration=$NET_JSON" \
  --overrides "file://$OVERRIDES_FILE" \
  --query 'tasks[0].{TaskArn:taskArn,LastStatus:lastStatus}' \
  --output json)"

TASK_ARN="$(echo "$RESULT" | python3 -c 'import sys,json;print(json.load(sys.stdin)["TaskArn"])')"
TASK_ID="${TASK_ARN##*/}"
STREAM_NAME="ecs/${CONTAINER}/${TASK_ID}"
echo "[run-warmup] launched task $TASK_ID"
echo "[run-warmup] CloudWatch: log-group=$LOG_GROUP  stream=$STREAM_NAME"

if [[ "$WATCH" == "1" ]]; then
  echo "[run-warmup] tailing logs (Ctrl-C to stop tail; task keeps running):"
  exec aws --region "$REGION" logs tail "$LOG_GROUP" \
    --log-stream-names "$STREAM_NAME" --follow --since 30s
fi
