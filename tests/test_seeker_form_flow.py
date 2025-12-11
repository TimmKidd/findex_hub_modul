"""
Test to verify the seeker form FSM flow works correctly.
This test ensures handlers in forms.py don't intercept normal flow.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from findex_bot.handlers.forms import edit_field_after_reject_seeker
from findex_bot.states.vacancies import SeekerForm


@pytest.mark.asyncio
async def test_forms_handler_returns_early_when_not_inline_edit():
    """
    Test that the forms.py handler returns early when is_inline_edit is False.
    This ensures it doesn't interfere with the normal seeker.py flow.
    """
    # Create mock message
    message = MagicMock(spec=Message)
    message.text = "Test position"
    
    # Create mock state with is_inline_edit=False (normal flow)
    state = MagicMock(spec=FSMContext)
    state.get_data = AsyncMock(return_value={
        "is_inline_edit": False,
        "position": "",
        "schedule": "",
        "salary": "",
        "location": "",
        "contacts": "",
        "description": "",
    })
    state.get_state = AsyncMock(return_value=SeekerForm.position.state)
    state.update_data = AsyncMock()
    state.set_state = AsyncMock()
    
    # Mock send_preview
    with patch('findex_bot.handlers.forms.send_preview', new_callable=AsyncMock) as mock_preview:
        # Call the handler
        await edit_field_after_reject_seeker(message, state)
        
        # Handler should return early without calling update_data or send_preview
        state.update_data.assert_not_called()
        state.set_state.assert_not_called()
        mock_preview.assert_not_called()


@pytest.mark.asyncio
async def test_forms_handler_processes_when_inline_edit():
    """
    Test that the forms.py handler processes the message when is_inline_edit is True.
    This ensures inline editing after rejection still works.
    """
    # Create mock message
    message = MagicMock(spec=Message)
    message.text = "Corrected position"
    message.bot = MagicMock()
    
    # Create mock state with is_inline_edit=True (inline edit after rejection)
    state = MagicMock(spec=FSMContext)
    state.get_data = AsyncMock(return_value={
        "is_inline_edit": True,
        "position": "Old position",
        "schedule": "",
        "salary": "",
        "location": "",
        "contacts": "",
        "description": "",
    })
    state.get_state = AsyncMock(return_value=SeekerForm.position.state)
    state.update_data = AsyncMock()
    state.set_state = AsyncMock()
    
    # Mock send_preview
    with patch('findex_bot.handlers.forms.send_preview', new_callable=AsyncMock) as mock_preview:
        # Call the handler
        await edit_field_after_reject_seeker(message, state)
        
        # Handler should update the position field
        state.update_data.assert_any_call(position="Corrected position")
        # Handler should set is_inline_edit to False
        state.update_data.assert_any_call(is_inline_edit=False)
        # Handler should transition to preview state
        state.set_state.assert_called_once_with(SeekerForm.preview)
        # Handler should call send_preview
        mock_preview.assert_called_once()
