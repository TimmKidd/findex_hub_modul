import asyncio
from types import SimpleNamespace

from findex_bot.utils.ui_utils import cleanup_tracked_messages_fast


class FakeState:
    def __init__(self, data):
        self._data = dict(data)

    async def get_data(self):
        return dict(self._data)

    async def update_data(self, **kwargs):
        self._data.update(kwargs)

    @property
    def data(self):
        return self._data


class FakeBot:
    def __init__(self, fail_ids=None):
        self.calls = []
        self.fail_ids = set(fail_ids or [])

    async def delete_message(self, chat_id, message_id):
        self.calls.append((chat_id, message_id))
        if message_id in self.fail_ids:
            # имитируем штатную Telegram-ошибку удаления
            raise Exception("message to delete not found")
        return True


async def main():
    # Исходное FSM-состояние с важными рабочими ключами сценария
    original = {
        "ad_id": 35,
        "editing_field": "citizenship",
        "fsm_last_state": "RespondFSM:form_preview",
        "clean_thread_hint_key": "respond_form_preview",
        "clean_thread_hint_ts": 1234567890,
        "draft_cleanup_chat_id": 777000,
        "draft_cleanup_ids": [101, "102", 102, 0, -1, "bad", 103, 104, 104],
        "some_other_key": {"nested": True},
    }

    state = FakeState(original)
    bot = FakeBot(fail_ids={103})

    deleted_count = await cleanup_tracked_messages_fast(
        bot,
        state,
        chunk_size=50,
        pause_between_chunks=0.0,
    )

    # 1. cleanup bucket должен быть очищен
    assert state.data["draft_cleanup_ids"] == [], "draft_cleanup_ids не очистился"

    # 2. chat_id не должен ломаться
    assert state.data["draft_cleanup_chat_id"] == 777000, "draft_cleanup_chat_id изменился"

    # 3. остальные FSM-ключи не должны быть затронуты
    assert state.data["ad_id"] == 35
    assert state.data["editing_field"] == "citizenship"
    assert state.data["fsm_last_state"] == "RespondFSM:form_preview"
    assert state.data["clean_thread_hint_key"] == "respond_form_preview"
    assert state.data["clean_thread_hint_ts"] == 1234567890
    assert state.data["some_other_key"] == {"nested": True}

    # 4. должны уйти только валидные уникальные message_id: 101,102,103,104
    expected_calls = {
        (777000, 101),
        (777000, 102),
        (777000, 103),
        (777000, 104),
    }
    actual_calls = set(bot.calls)

    assert actual_calls == expected_calls, f"delete_message вызван не по контракту: {actual_calls}"
    assert deleted_count == 4, f"deleted_count ожидался 4, получен {deleted_count}"

    print("OK: cleanup_tracked_messages_fast contract is safe")


if __name__ == "__main__":
    asyncio.run(main())
