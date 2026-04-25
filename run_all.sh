#run_all.sh
#!/bin/bash
set -euo pipefail

PROJECT_DIR="/Users/tmkd/Desktop/tmkd/FindexHub"
SUPPORT_BOT_FILE="/Users/tmkd/Desktop/tmkd/FindexHub/support_bot/support_bot.py"

cd "$PROJECT_DIR" || exit 1

source venv/bin/activate

# Подхватываем .env, если он есть
if [ -f .env ]; then
  set -a
  source .env
  set +a
fi

export REDIS_HOST="${REDIS_HOST:-127.0.0.1}"
export REDIS_PORT="${REDIS_PORT:-6379}"

BOT_PID=""
JOBS_PID=""
RES_PID=""
SUPPORT_PID=""

cleanup() {
  echo
  echo "🛑 run_all.sh: stopping child processes..."

  for pid in "$BOT_PID" "$JOBS_PID" "$RES_PID" "$SUPPORT_PID"; do
    if [ -n "${pid:-}" ] && kill -0 "$pid" 2>/dev/null; then
      kill -TERM "$pid" 2>/dev/null || true
    fi
  done

  sleep 2

  for pid in "$BOT_PID" "$JOBS_PID" "$RES_PID" "$SUPPORT_PID"; do
    if [ -n "${pid:-}" ] && kill -0 "$pid" 2>/dev/null; then
      kill -KILL "$pid" 2>/dev/null || true
    fi
  done
}

trap cleanup INT TERM EXIT

if [ ! -f "$SUPPORT_BOT_FILE" ]; then
  echo "⛔ Не найден файл support bot: $SUPPORT_BOT_FILE"
  exit 1
fi

echo "Starting bot..."
python -m findex_bot.bot &
BOT_PID=$!

echo "Starting jobs..."
python -m findex_bot.jobs &
JOBS_PID=$!

echo "Starting resurrection worker..."
python -m findex_bot.resurrection_worker &
RES_PID=$!

echo "Starting support bot..."
python "$SUPPORT_BOT_FILE" &
SUPPORT_PID=$!

echo "✅ bot pid=$BOT_PID"
echo "✅ jobs pid=$JOBS_PID"
echo "✅ resurrection pid=$RES_PID"
echo "✅ support pid=$SUPPORT_PID"

# Ждём завершения процессов
wait "$BOT_PID" "$JOBS_PID" "$RES_PID" "$SUPPORT_PID"