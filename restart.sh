#restart.sh
#!/bin/bash
set -euo pipefail

PROJECT_DIR="/Users/tmkd/Desktop/tmkd/FindexHub"
SUPPORT_BOT_FILE="/Users/tmkd/Desktop/tmkd/FindexHub/support_bot/support_bot.py"

echo "--------------------------------------"
echo "FindexHub restart script"
echo "--------------------------------------"

if [ ! -f "$SUPPORT_BOT_FILE" ]; then
  echo "⛔ Не найден файл support bot:"
  echo "   $SUPPORT_BOT_FILE"
  exit 1
fi

echo "🛑 Останавливаем старые процессы..."

# Основной бот
pkill -f "python -m findex_bot.bot" 2>/dev/null || true

# Фоновые воркеры
pkill -f "python -m findex_bot.jobs" 2>/dev/null || true
pkill -f "python -m findex_bot.resurrection_worker" 2>/dev/null || true

# Support bot
pkill -f "$SUPPORT_BOT_FILE" 2>/dev/null || true

# На всякий случай: если где-то запуск шёл через файл
pkill -f "jobs.py" 2>/dev/null || true
pkill -f "resurrection_worker.py" 2>/dev/null || true
pkill -f "support_bot.py" 2>/dev/null || true

pkill -f "run_all.sh" 2>/dev/null || true

# Даём шанс мягко завершиться
sleep 2

# Если кто-то пережил TERM — добиваем жёстко
pkill -9 -f "python -m findex_bot.bot" 2>/dev/null || true
pkill -9 -f "python -m findex_bot.jobs" 2>/dev/null || true
pkill -9 -f "python -m findex_bot.resurrection_worker" 2>/dev/null || true
pkill -9 -f "$SUPPORT_BOT_FILE" 2>/dev/null || true

pkill -9 -f "jobs.py" 2>/dev/null || true
pkill -9 -f "resurrection_worker.py" 2>/dev/null || true
pkill -9 -f "support_bot.py" 2>/dev/null || true

sleep 1

echo "🔎 Проверяем, что хвостов не осталось..."
if pgrep -fal "findex_bot\.bot|findex_bot\.jobs|findex_bot\.resurrection_worker|support_bot\.py|run_all\.sh" >/dev/null 2>&1; then
  echo "⛔ После остановки остались процессы:"
  pgrep -fal "findex_bot\.bot|findex_bot\.jobs|findex_bot\.resurrection_worker|support_bot\.py|run_all\.sh" || true
  exit 1
fi

echo "🚀 Запускаем проект..."

cd "$PROJECT_DIR" || exit 1

./run_all.sh

echo "✅ FindexHub запущен"