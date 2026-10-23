"""
Unit and security tests for the Todoist FastMCP Server: task tools.
All tests use mocks to ensure zero network calls and deterministic results.
"""

import logging
from datetime import date
from unittest.mock import MagicMock, patch
import httpx
import pytest
from todoist_api_python.api import TodoistAPI
from plugvan import todoist
from plugvan.todoist.limits import (
    MAX_CONTENT_LENGTH,
    MAX_DESCRIPTION_LENGTH,
    MAX_DUE_STRING_LENGTH,
    MAX_FILTER_QUERY_LENGTH,
    MAX_PROJECT_NAME_LENGTH,
    MAX_TASK_ID_LENGTH,
)
from plugvan.todoist.tools.tasks import (
    complete_task,
    create_task,
    delete_task,
    get_task,
    list_tasks,
    reopen_task,
    update_task,
)
from tests.todoist.helpers import (
    MockProject,
    MockSection,
    _make_http_status_error,
    MockTask,
    write_call_count,
)


# =====================================================================
# CREATE_TASK TESTS
# =====================================================================

@patch("plugvan.todoist.client.get_api_client")
def test_create_task_success(mock_get_client):
    mock_api = MagicMock()
    mock_get_client.return_value = mock_api

    mock_project = MockProject("proj_100", "Odak & Gelişim")
    mock_section = MockSection("sec_200", "Acil İşler", project_id="proj_100")
    mock_api.get_projects.return_value = [[mock_project]]
    mock_api.get_sections.return_value = [[mock_section]]
    mock_api.add_task.return_value = MockTask(
        task_id="task_001",
        content="Read 10 pages",
        priority=2,
        due_string="tomorrow at 10:00",
        labels=["kitap", "odak"],
        section_id="sec_200",
    )

    result = create_task(
        content="Read 10 pages",
        description="Daily habit",
        project_name="Odak & Gelişim",
        section_name_or_id="Acil İşler",
        due_string="tomorrow at 10:00",
        priority=2,
        labels=["@kitap", "odak"],
    )

    assert "✅ Task created successfully!" in result
    assert "ID: task_001" in result
    assert "Title: Read 10 pages" in result
    assert "Project: Odak & Gelişim" in result
    assert "Section: Acil İşler (ID: sec_200)" in result
    assert "Priority: p2" in result
    assert "Labels: @kitap, @odak" in result
    mock_api.add_task.assert_called_once_with(
        content="Read 10 pages",
        description="Daily habit",
        project_id="proj_100",
        section_id="sec_200",
        due_string="tomorrow at 10:00",
        priority=2,
        labels=["kitap", "odak"],
    )


@patch("plugvan.todoist.client.get_api_client")
def test_create_task_section_not_found(mock_get_client):
    mock_api = MagicMock()
    mock_get_client.return_value = mock_api
    mock_project = MockProject("proj_100", "İş")
    mock_api.get_projects.return_value = [[mock_project]]
    mock_api.get_sections.return_value = [[]]

    result = create_task(
        content="Task without section",
        project_name="İş",
        section_name_or_id="Olmayan Bölüm",
    )
    assert "⚠️ Section not found: 'Olmayan Bölüm'." in result


@patch("plugvan.todoist.client.get_api_client")
def test_create_task_inbox_default(mock_get_client):
    mock_api = MagicMock()
    mock_get_client.return_value = mock_api

    mock_inbox = MockProject("inbox_id", "Inbox", is_inbox=True)
    mock_api.get_projects.return_value = [[mock_inbox]]
    mock_api.add_task.return_value = MockTask(
        task_id="task_002",
        content="General Task",
        priority=1,
    )

    result = create_task(content="General Task")
    assert "✅ Task created successfully!" in result
    assert "ID: task_002" in result
    mock_api.add_task.assert_called_once_with(
        content="General Task",
        description=None,
        project_id="inbox_id",
        due_string=None,
        priority=1,
    )


@patch("plugvan.todoist.client.get_api_client")
def test_create_task_with_parent_id(mock_get_client):
    """parent_id verildiğinde SDK çağrısına dahil edilmelidir (alt görev/subtask)."""
    mock_api = MagicMock()
    mock_get_client.return_value = mock_api

    mock_api.get_projects.return_value = [[]]
    mock_api.add_task.return_value = MockTask(
        task_id="task_child_001",
        content="Alt görev",
        priority=1,
    )

    result = create_task(content="Alt görev", parent_id="task_parent_999")

    assert "✅ Task created successfully!" in result
    mock_api.add_task.assert_called_once_with(
        content="Alt görev",
        description=None,
        project_id=None,
        due_string=None,
        priority=1,
        parent_id="task_parent_999",
    )


@patch("plugvan.todoist.client.get_api_client")
def test_create_task_without_parent_id_omitted(mock_get_client):
    """parent_id verilmediğinde SDK çağrısında hiç yer almamalıdır."""
    mock_api = MagicMock()
    mock_get_client.return_value = mock_api

    mock_api.get_projects.return_value = [[]]
    mock_api.add_task.return_value = MockTask(
        task_id="task_003",
        content="Bağımsız görev",
        priority=1,
    )

    create_task(content="Bağımsız görev")

    call_kwargs = mock_api.add_task.call_args.kwargs
    assert "parent_id" not in call_kwargs


@patch("plugvan.todoist.client.get_api_client")
def test_create_task_with_deadline_date(mock_get_client):
    """deadline_date verildiğinde bir date nesnesine çevrilip SDK çağrısına dahil edilmelidir."""
    mock_api = MagicMock()
    mock_get_client.return_value = mock_api

    mock_api.get_projects.return_value = [[]]
    mock_api.add_task.return_value = MockTask(
        task_id="task_deadline_001",
        content="Son teslimli görev",
        priority=1,
    )

    result = create_task(content="Son teslimli görev", deadline_date="2026-09-01")

    assert "✅ Task created successfully!" in result
    assert "Deadline: 2026-09-01" in result
    mock_api.add_task.assert_called_once_with(
        content="Son teslimli görev",
        description=None,
        project_id=None,
        due_string=None,
        priority=1,
        deadline_date=date(2026, 9, 1),
    )


@patch("plugvan.todoist.client.get_api_client")
def test_create_task_without_deadline_date_omitted(mock_get_client):
    """deadline_date verilmediğinde SDK çağrısında hiç yer almamalıdır."""
    mock_api = MagicMock()
    mock_get_client.return_value = mock_api

    mock_api.get_projects.return_value = [[]]
    mock_api.add_task.return_value = MockTask(
        task_id="task_004",
        content="Son teslimsiz görev",
        priority=1,
    )

    create_task(content="Son teslimsiz görev")

    call_kwargs = mock_api.add_task.call_args.kwargs
    assert "deadline_date" not in call_kwargs


def test_create_task_invalid_deadline_date_format():
    result = create_task(content="Task", deadline_date="01-09-2026")
    assert "❌ Invalid input: deadline_date must be in YYYY-MM-DD format" in result


@patch("plugvan.todoist.client.get_api_client")
def test_create_task_due_string_and_deadline_date_together(mock_get_client):
    """due_string ve deadline_date aynı anda verildiğinde birbirini geçersiz kılmadan,
    ikisi de bağımsız alanlar olarak SDK çağrısına dahil edilmelidir."""
    mock_api = MagicMock()
    mock_get_client.return_value = mock_api

    mock_api.get_projects.return_value = [[]]
    mock_api.add_task.return_value = MockTask(
        task_id="task_both_001",
        content="Hem tarihli hem son teslimli görev",
        priority=1,
        due_string="tomorrow at 10:00",
    )

    result = create_task(
        content="Hem tarihli hem son teslimli görev",
        due_string="tomorrow at 10:00",
        deadline_date="2026-09-01",
    )

    assert "✅ Task created successfully!" in result
    assert "Due / Recurrence: tomorrow at 10:00" in result
    assert "Deadline: 2026-09-01" in result
    mock_api.add_task.assert_called_once_with(
        content="Hem tarihli hem son teslimli görev",
        description=None,
        project_id=None,
        due_string="tomorrow at 10:00",
        priority=1,
        deadline_date=date(2026, 9, 1),
    )


@patch("plugvan.todoist.client.get_api_client")
def test_create_task_deadline_date_403_reports_plan_restriction(mock_get_client):
    """deadline_date verilen bir istek 403 Forbidden ile reddedilirse, Free/Beginner planında
    Deadline özelliğinin desteklenmediğini açıklayan özel bir hata mesajı dönmelidir."""
    mock_api = MagicMock()
    mock_get_client.return_value = mock_api

    mock_api.get_projects.return_value = [[]]
    mock_api.add_task.side_effect = _make_http_status_error(403, text="Forbidden")

    result = create_task(content="Son teslimli görev", deadline_date="2026-09-01")

    assert result == (
        "❌ The deadline feature is not available on the Todoist Free/Beginner plan "
        "— a Pro or Business plan is required (403 Forbidden)."
    )


@patch("plugvan.todoist.client.get_api_client")
def test_create_task_403_without_deadline_date_uses_generic_message(mock_get_client):
    """deadline_date verilmeden gelen bir 403, plan-kısıtlaması mesajını değil genel hata
    mesajını dönmelidir (deadline dışı 403 sebepleri etkilenmemeli)."""
    mock_api = MagicMock()
    mock_get_client.return_value = mock_api

    mock_api.get_projects.return_value = [[]]
    mock_api.add_task.side_effect = _make_http_status_error(403, text="Forbidden")

    result = create_task(content="Son teslimsiz görev")

    assert result == "❌ Todoist task creation failed. Check server logs for details."


def test_create_task_empty_content():
    result = create_task(content="   ")
    assert "❌ Invalid input: Task content cannot be empty" in result


def test_create_task_content_too_long():
    long_content = "A" * (MAX_CONTENT_LENGTH + 1)
    result = create_task(content=long_content)
    assert "❌ Invalid input: Task content exceeds maximum length" in result


def test_create_task_description_too_long():
    long_desc = "D" * (MAX_DESCRIPTION_LENGTH + 1)
    result = create_task(content="Valid title", description=long_desc)
    assert "❌ Invalid input: Task description exceeds maximum length" in result


def test_create_task_project_name_too_long():
    long_proj = "P" * (MAX_PROJECT_NAME_LENGTH + 1)
    result = create_task(content="Valid title", project_name=long_proj)
    assert "❌ Invalid input: Project name exceeds maximum length" in result


def test_create_task_due_string_too_long():
    long_due = "T" * (MAX_DUE_STRING_LENGTH + 1)
    result = create_task(content="Valid title", due_string=long_due)
    assert "❌ Invalid input: Due date string exceeds maximum length" in result


@pytest.mark.parametrize("invalid_priority", [0, 5, -1, 999, "high"])
def test_create_task_invalid_priority_rejected(invalid_priority):
    result = create_task(content="Valid task", priority=invalid_priority)
    assert "❌ Invalid input: Priority must be an integer between 1" in result


def test_create_task_invalid_labels_type():
    result = create_task(content="Valid task", labels="not_a_list")
    assert "❌ Invalid input: Labels must be a list of strings" in result


@patch("plugvan.todoist.client.get_api_client")
def test_create_task_sanitizes_exception_and_logs_cleanly(mock_get_client, caplog):
    mock_api = MagicMock()
    mock_get_client.return_value = mock_api
    mock_api.get_projects.return_value = []
    mock_api.add_task.side_effect = Exception(
        "TODOIST_API_TOKEN=SUPER_SECRET_TOKEN_123 failed Authorization: Bearer SUPER_SECRET_TOKEN_123"
    )

    with caplog.at_level("INFO"):
        result = create_task(content="Test Task")

    assert result == "❌ Todoist task creation failed. Check server logs for details."
    assert "SUPER_SECRET_TOKEN_123" not in result
    assert "Bearer" not in result
    assert "SUPER_SECRET_TOKEN_123" not in caplog.text
    assert "Bearer" not in caplog.text


# =====================================================================
# LIST_TASKS TESTS
# =====================================================================

@patch("plugvan.todoist.client.get_api_client")
def test_list_tasks_success(mock_get_client):
    mock_api = MagicMock()
    mock_get_client.return_value = mock_api

    task1 = MockTask("t1", "First task", priority=4, due_string="today", description="Note 1", labels=["acil"])
    task2 = MockTask("t2", "Second task", priority=1, due_string=None)
    mock_api.filter_tasks.return_value = [[task1, task2]]

    result = list_tasks(filter_query="today")
    assert "📋 Open Tasks (Filter: 'today', Total: 2):" in result
    assert "[t1] First task [@acil]" in result
    assert "🔴 p4 (Urgent)" in result
    assert "Due: today" in result
    assert "Description: Note 1" in result
    assert "[t2] Second task" in result
    assert "⚪ p1 (Normal)" in result
    assert "Due: No due date" in result


@patch("plugvan.todoist.client.get_api_client")
def test_list_tasks_empty_result(mock_get_client):
    mock_api = MagicMock()
    mock_get_client.return_value = mock_api
    mock_api.filter_tasks.return_value = [[]]

    result = list_tasks(filter_query="overdue")
    assert "ℹ️ No open tasks match the filter 'overdue'." in result


def test_list_tasks_empty_filter():
    result = list_tasks(filter_query="   ")
    assert "❌ Invalid input: Filter query cannot be empty" in result


def test_list_tasks_filter_too_long():
    long_filter = "Q" * (MAX_FILTER_QUERY_LENGTH + 1)
    result = list_tasks(filter_query=long_filter)
    assert "❌ Invalid input: Filter query exceeds maximum length" in result


@patch("plugvan.todoist.client.get_api_client")
def test_list_tasks_sanitizes_exception_and_logs_cleanly(mock_get_client, caplog):
    mock_api = MagicMock()
    mock_get_client.return_value = mock_api
    mock_api.filter_tasks.side_effect = RuntimeError(
        "TODOIST_API_TOKEN=SUPER_SECRET_TOKEN_123 failed Authorization: Bearer SUPER_SECRET_TOKEN_123"
    )

    with caplog.at_level("INFO"):
        result = list_tasks(filter_query="today")

    assert result == "❌ Failed to retrieve tasks from Todoist. Check server logs for details."
    assert "SUPER_SECRET_TOKEN_123" not in result
    assert "SUPER_SECRET_TOKEN_123" not in caplog.text


# =====================================================================
# GET_TASK TESTS
# =====================================================================

@patch("plugvan.todoist.client.get_api_client")
def test_get_task_success(mock_get_client):
    mock_api = MagicMock()
    mock_get_client.return_value = mock_api
    mock_api.get_task.return_value = MockTask(
        task_id="task_777",
        content="Sub-task example",
        priority=3,
        due_string="tomorrow at 09:00",
        description="Details here",
        labels=["work", "urgent"],
        section_id="sec_10",
        project_id="proj_20",
        parent_id="task_parent_5",
    )

    result = get_task(task_id="task_777")

    assert "📄 Task Details (ID: task_777)" in result
    assert "Title: Sub-task example" in result
    assert "Description: Details here" in result
    assert "Project ID: proj_20" in result
    assert "Section ID: sec_10" in result
    assert "Parent Task ID (parent_id): task_parent_5" in result
    assert "Priority: p3" in result
    assert "Due / Recurrence: tomorrow at 09:00" in result
    assert "Labels: @work, @urgent" in result
    mock_api.get_task.assert_called_once_with(task_id="task_777")


@patch("plugvan.todoist.client.get_api_client")
def test_get_task_without_parent_shows_top_level(mock_get_client):
    mock_api = MagicMock()
    mock_get_client.return_value = mock_api
    mock_api.get_task.return_value = MockTask(
        task_id="task_888",
        content="Standalone task",
        project_id="proj_20",
    )

    result = get_task(task_id="task_888")
    assert "Parent Task ID (parent_id): None (top-level task)" in result
    assert "Section ID: None" in result
    assert "Description: None" in result
    assert "Labels: None" in result


def test_get_task_empty_id():
    result = get_task(task_id="   ")
    assert "❌ Invalid input: Task ID cannot be empty or whitespace." in result


def test_get_task_id_too_long():
    result = get_task(task_id="x" * (MAX_TASK_ID_LENGTH + 1))
    assert f"❌ Invalid input: Task ID exceeds maximum length of {MAX_TASK_ID_LENGTH} characters." in result


@patch("plugvan.todoist.client.get_api_client")
def test_get_task_sanitizes_exception_and_logs_cleanly(mock_get_client, caplog):
    mock_api = MagicMock()
    mock_get_client.return_value = mock_api
    mock_api.get_task.side_effect = Exception(
        "TODOIST_API_TOKEN=SUPER_SECRET_TOKEN_123 failed Authorization: Bearer SUPER_SECRET_TOKEN_123"
    )

    with caplog.at_level("INFO"):
        result = get_task(task_id="task_err")

    assert result == "❌ Failed to retrieve task from Todoist (ID: task_err). Check server logs for details."
    assert "SUPER_SECRET_TOKEN_123" not in result
    assert "SUPER_SECRET_TOKEN_123" not in caplog.text


# =====================================================================
# COMPLETE_TASK & REOPEN_TASK TESTS
# =====================================================================

@patch("plugvan.todoist.client.get_api_client")
def test_complete_task_success(mock_get_client):
    mock_api = MagicMock()
    mock_get_client.return_value = mock_api
    mock_api.complete_task.return_value = True

    result = complete_task(task_id="  task_abc123  ")
    assert "✅ Task completed successfully (ID: task_abc123)." in result
    mock_api.complete_task.assert_called_once_with(task_id="task_abc123")


@patch("plugvan.todoist.client.get_api_client")
def test_complete_task_unsuccessful(mock_get_client):
    mock_api = MagicMock()
    mock_get_client.return_value = mock_api
    mock_api.complete_task.return_value = False

    result = complete_task(task_id="task_not_found")
    assert "⚠️ The task could not be completed, or it may already be completed (ID: task_not_found)." in result


def test_complete_task_empty_id():
    result = complete_task(task_id="   ")
    assert "❌ Invalid input: Task ID cannot be empty" in result


def test_complete_task_id_too_long():
    long_id = "X" * (MAX_TASK_ID_LENGTH + 1)
    result = complete_task(task_id=long_id)
    assert "❌ Invalid input: Task ID exceeds maximum length" in result


@patch("plugvan.todoist.client.get_api_client")
def test_complete_task_sanitizes_exception_and_logs_cleanly(mock_get_client, caplog):
    mock_api = MagicMock()
    mock_get_client.return_value = mock_api
    mock_api.complete_task.side_effect = Exception(
        "TODOIST_API_TOKEN=SUPER_SECRET_TOKEN_123 failed Authorization: Bearer SUPER_SECRET_TOKEN_123"
    )

    with caplog.at_level("INFO"):
        result = complete_task(task_id="task_error_123")

    assert result == "❌ Failed to complete task in Todoist (ID: task_error_123). Check server logs for details."
    assert "SUPER_SECRET_TOKEN_123" not in result
    assert "SUPER_SECRET_TOKEN_123" not in caplog.text


@patch("plugvan.todoist.client.get_api_client")
def test_reopen_task_success(mock_get_client):
    mock_api = MagicMock()
    mock_get_client.return_value = mock_api
    mock_api.uncomplete_task.return_value = True

    result = reopen_task(task_id="  task_reopen_1  ")
    assert "🔄 Task reopened successfully (ID: task_reopen_1)." in result
    mock_api.uncomplete_task.assert_called_once_with(task_id="task_reopen_1")


@patch("plugvan.todoist.client.get_api_client")
def test_reopen_task_unsuccessful(mock_get_client):
    mock_api = MagicMock()
    mock_get_client.return_value = mock_api
    mock_api.uncomplete_task.return_value = False

    result = reopen_task(task_id="task_already_active")
    assert "⚠️ The task could not be reopened, or it may already be open (ID: task_already_active)." in result


def test_reopen_task_empty_id():
    result = reopen_task(task_id="   ")
    assert "❌ Invalid input: Task ID cannot be empty" in result


@patch("plugvan.todoist.client.get_api_client")
def test_reopen_task_sanitizes_exception(mock_get_client):
    mock_api = MagicMock()
    mock_get_client.return_value = mock_api
    mock_api.uncomplete_task.side_effect = Exception("TODOIST_API_TOKEN=SECRET")

    result = reopen_task(task_id="task_err")
    assert result == "❌ Failed to reopen task in Todoist (ID: task_err). Check server logs for details."
    assert "SECRET" not in result


# =====================================================================
# UPDATE_TASK TESTS
# =====================================================================

@patch("plugvan.todoist.client.get_api_client")
def test_update_task_success(mock_get_client):
    mock_api = MagicMock()
    mock_get_client.return_value = mock_api
    mock_project = MockProject("proj_99", "İş")
    mock_section = MockSection("sec_55", "Tamamlananlar", project_id="proj_99")
    mock_api.get_projects.return_value = [[mock_project]]
    mock_api.get_sections.return_value = [[mock_section]]

    result = update_task(
        task_id="task_123",
        content="Yeni Başlık",
        description="Yeni Açıklama",
        project_name="İş",
        section_name_or_id="Tamamlananlar",
        due_string="yarın 15:00",
        priority=3,
        labels=["@önemli", "proje"],
    )

    assert "✅ Task updated successfully (ID: task_123)!" in result
    assert "Title: 'Yeni Başlık'" in result
    assert "Description: 'Yeni Açıklama'" in result
    assert "Due: 'yarın 15:00'" in result
    assert "Priority: p3" in result
    assert "Labels: @önemli, @proje" in result
    assert "Target Project: 'İş' (ID: proj_99)" in result
    assert "Target Section: 'Tamamlananlar' (ID: sec_55)" in result

    mock_api.update_task.assert_called_once_with(
        task_id="task_123",
        content="Yeni Başlık",
        description="Yeni Açıklama",
        due_string="yarın 15:00",
        priority=3,
        labels=["önemli", "proje"],
    )
    mock_api.move_task.assert_called_once_with(task_id="task_123", project_id="proj_99", section_id="sec_55")


def test_update_task_no_fields_provided():
    result = update_task(task_id="task_123")
    assert "⚠️ No fields to update were specified" in result


def test_update_task_invalid_priority():
    result = update_task(task_id="task_123", priority=5)
    assert "❌ Invalid input: Priority must be an integer between 1" in result


def test_update_task_invalid_labels_type():
    result = update_task(task_id="task_123", labels="not_a_list")
    assert "❌ Invalid input: Labels must be a list of strings" in result


@patch("plugvan.todoist.client.get_api_client")
def test_update_task_sanitizes_exception(mock_get_client):
    mock_api = MagicMock()
    mock_get_client.return_value = mock_api
    mock_api.update_task.side_effect = Exception("TODOIST_API_TOKEN=SECRET")

    result = update_task(task_id="task_err", content="Updated Content")
    assert result == "❌ Failed to update task in Todoist (ID: task_err). Check server logs for details."
    assert "SECRET" not in result


def test_update_task_parent_id_too_long():
    result = update_task(task_id="task_123", parent_id="x" * (MAX_TASK_ID_LENGTH + 1))
    assert f"❌ Invalid input: Parent task ID exceeds maximum length of {MAX_TASK_ID_LENGTH} characters." in result


@patch("plugvan.todoist.client.get_api_client")
def test_update_task_sets_parent_id(mock_get_client):
    """parent_id dolu bir string olarak verildiğinde move_task ile yeni üst görev atanmalı."""
    mock_api = MagicMock()
    mock_get_client.return_value = mock_api

    result = update_task(task_id="task_child", parent_id="task_parent_1")

    assert "✅ Task updated successfully (ID: task_child)!" in result
    assert "Parent Task (parent_id): 'task_parent_1'" in result
    mock_api.get_task.assert_not_called()
    mock_api.update_task.assert_not_called()
    mock_api.move_task.assert_called_once_with(task_id="task_child", parent_id="task_parent_1")


@patch("plugvan.todoist.client.get_api_client")
def test_update_task_unparent_with_empty_string(mock_get_client):
    """parent_id="" verildiğinde, görevin mevcut projesi (api.get_task ile) çekilip
    move_task(project_id=...) ile üst seviyeye taşınmalı (Todoist API'de parent_id'yi
    null yaparak unparent etme desteklenmediği için)."""
    mock_api = MagicMock()
    mock_get_client.return_value = mock_api
    mock_api.get_task.return_value = MagicMock(project_id="proj_999")

    result = update_task(task_id="task_child", parent_id="")

    assert "✅ Task updated successfully (ID: task_child)!" in result
    assert "Parent Task: Removed (task moved to the top level)" in result
    mock_api.get_task.assert_called_once_with(task_id="task_child")
    mock_api.move_task.assert_called_once_with(task_id="task_child", project_id="proj_999")


@patch("plugvan.todoist.client.get_api_client")
def test_update_task_unparent_with_project_name_skips_current_project_lookup(mock_get_client):
    """parent_id="" ile aynı anda project_name de verilirse, hedef proje zaten
    resolve edildiğinden api.get_task ile mevcut proje sorgusu yapılmamalı."""
    mock_api = MagicMock()
    mock_get_client.return_value = mock_api
    mock_project = MockProject("proj_42", "Kişisel")
    mock_api.get_projects.return_value = [[mock_project]]

    result = update_task(task_id="task_child", project_name="Kişisel", parent_id="")

    assert "Target Project: 'Kişisel' (ID: proj_42)" in result
    assert "Parent Task: Removed (task moved to the top level)" in result
    mock_api.get_task.assert_not_called()
    mock_api.move_task.assert_called_once_with(task_id="task_child", project_id="proj_42")


@patch("plugvan.todoist.client.get_api_client")
def test_update_task_with_deadline_date(mock_get_client):
    """deadline_date verildiğinde bir date nesnesine çevrilip api.update_task çağrısına dahil edilmelidir."""
    mock_api = MagicMock()
    mock_get_client.return_value = mock_api

    result = update_task(task_id="task_123", deadline_date="2026-09-01")

    assert "✅ Task updated successfully (ID: task_123)!" in result
    assert "Deadline: '2026-09-01'" in result
    mock_api.update_task.assert_called_once_with(task_id="task_123", deadline_date=date(2026, 9, 1))


@patch("plugvan.todoist.client.get_api_client")
def test_update_task_without_deadline_date_omitted(mock_get_client):
    """deadline_date verilmediğinde api.update_task çağrısında hiç yer almamalıdır."""
    mock_api = MagicMock()
    mock_get_client.return_value = mock_api

    update_task(task_id="task_123", content="Yeni Başlık")

    call_kwargs = mock_api.update_task.call_args.kwargs
    assert "deadline_date" not in call_kwargs


def test_update_task_invalid_deadline_date_format():
    result = update_task(task_id="task_123", deadline_date="01-09-2026")
    assert "❌ Invalid input: deadline_date must be in YYYY-MM-DD format" in result


@patch("plugvan.todoist.client.get_api_client")
def test_update_task_due_string_and_deadline_date_together(mock_get_client):
    """due_string ve deadline_date aynı anda güncellendiğinde birbirini geçersiz kılmadan,
    ikisi de bağımsız alanlar olarak tek bir api.update_task çağrısına dahil edilmelidir."""
    mock_api = MagicMock()
    mock_get_client.return_value = mock_api

    result = update_task(
        task_id="task_123",
        due_string="tomorrow at 10:00",
        deadline_date="2026-09-01",
    )

    assert "✅ Task updated successfully (ID: task_123)!" in result
    assert "Due: 'tomorrow at 10:00'" in result
    assert "Deadline: '2026-09-01'" in result
    mock_api.update_task.assert_called_once_with(
        task_id="task_123",
        due_string="tomorrow at 10:00",
        deadline_date=date(2026, 9, 1),
    )


@patch("plugvan.todoist.client.get_api_client")
def test_update_task_deadline_date_403_reports_plan_restriction(mock_get_client):
    """deadline_date güncellenirken 403 Forbidden alınırsa, Free/Beginner planında Deadline
    özelliğinin desteklenmediğini açıklayan özel bir hata mesajı dönmelidir."""
    mock_api = MagicMock()
    mock_get_client.return_value = mock_api
    mock_api.update_task.side_effect = _make_http_status_error(403, text="Forbidden")

    result = update_task(task_id="task_123", deadline_date="2026-09-01")

    assert result == (
        "❌ The deadline feature is not available on the Todoist Free/Beginner plan "
        "— a Pro or Business plan is required (403 Forbidden)."
    )


@patch("plugvan.todoist.client.get_api_client")
def test_update_task_403_without_deadline_date_uses_generic_message(mock_get_client):
    """deadline_date olmadan gelen bir 403, plan-kısıtlaması mesajını değil görev-kimliğini
    içeren genel hata mesajını dönmelidir (deadline dışı 403 sebepleri etkilenmemeli)."""
    mock_api = MagicMock()
    mock_get_client.return_value = mock_api
    mock_api.update_task.side_effect = _make_http_status_error(403, text="Forbidden")

    result = update_task(task_id="task_123", content="Updated Content")

    assert result == "❌ Failed to update task in Todoist (ID: task_123). Check server logs for details."


# =====================================================================
# DELETE_TASK TESTS
# =====================================================================

@patch("plugvan.todoist.client.get_api_client")
def test_delete_task_success(mock_get_client):
    mock_api = MagicMock()
    mock_get_client.return_value = mock_api
    mock_api.delete_task.return_value = True

    result = delete_task(task_id="task_to_del")
    assert "🗑️ Task permanently deleted (ID: task_to_del)." in result
    mock_api.delete_task.assert_called_once_with(task_id="task_to_del")


@patch("plugvan.todoist.client.get_api_client")
def test_delete_task_unsuccessful(mock_get_client):
    mock_api = MagicMock()
    mock_get_client.return_value = mock_api
    mock_api.delete_task.return_value = False

    result = delete_task(task_id="task_missing")
    assert "⚠️ The task could not be deleted (ID: task_missing)." in result


def test_delete_task_empty_id():
    result = delete_task(task_id="   ")
    assert "❌ Invalid input: Task ID cannot be empty" in result


@patch("plugvan.todoist.client.get_api_client")
def test_delete_task_sanitizes_exception(mock_get_client):
    mock_api = MagicMock()
    mock_get_client.return_value = mock_api
    mock_api.delete_task.side_effect = Exception("TODOIST_API_TOKEN=SECRET")

    result = delete_task(task_id="task_err")
    assert result == "❌ Failed to delete task in Todoist (ID: task_err). Check server logs for details."
    assert "SECRET" not in result


# =====================================================================
# CREATE_TASK / UPDATE_TASK: VALIDATE BEFORE WRITE
# =====================================================================

def _api(projects=(), sections=()):
    mock_api = MagicMock()
    mock_api.get_projects.return_value = [list(projects)]
    mock_api.get_sections.return_value = [list(sections)]
    mock_api.add_task.return_value = MockTask(task_id="task_new", content="X", priority=1)
    return mock_api


@patch("plugvan.todoist.client.get_api_client")
def test_create_task_unknown_project_creates_nothing(mock_get_client):
    """A typo in project_name must not silently put the task in the Inbox."""
    mock_api = _api(projects=[MockProject("p_work", "Work"), MockProject("inbox_1", "Inbox", is_inbox=True)])
    mock_get_client.return_value = mock_api

    result = create_task(content="X", project_name="Wrok")

    assert result == "⚠️ Project not found: 'Wrok'."
    mock_api.add_task.assert_not_called()


@patch("plugvan.todoist.client.get_api_client")
def test_update_task_unknown_project_writes_nothing(mock_get_client):
    """update_task must resolve the target project before writing any field."""
    mock_api = _api(projects=[MockProject("p_work", "Work")])
    mock_get_client.return_value = mock_api

    result = update_task(task_id="task_1", content="x", project_name="Olmayan Proje")

    assert result == "⚠️ Target project not found: 'Olmayan Proje'."
    assert write_call_count(mock_api) == 0


@patch("plugvan.todoist.client.get_api_client")
def test_create_task_unresolved_project_does_not_use_section_from_other_project(mock_get_client):
    """When the project does not resolve, the section must not be found in some other project."""
    mock_api = _api(
        projects=[MockProject("p_work", "Work")],
        sections=[MockSection("sec_1", "Backlog", project_id="p_work")],
    )
    mock_get_client.return_value = mock_api

    result = create_task(content="X", project_name="Wrok", section_name_or_id="Backlog")

    assert result == "⚠️ Project not found: 'Wrok'."
    mock_api.add_task.assert_not_called()
    mock_api.get_sections.assert_not_called()


@patch("plugvan.todoist.client.get_api_client")
def test_create_task_ambiguous_project_creates_nothing(mock_get_client):
    mock_api = _api(projects=[MockProject("p1", "Proje A"), MockProject("p2", "Proje B")])
    mock_get_client.return_value = mock_api

    result = create_task(content="X", project_name="Proje")

    assert result == (
        "⚠️ Multiple projects found for 'Proje'; please use the project ID:\n"
        "• Proje A (p1)\n"
        "• Proje B (p2)"
    )
    assert write_call_count(mock_api) == 0


@patch("plugvan.todoist.client.get_api_client")
def test_create_task_unique_partial_project_shows_resolved_name(mock_get_client):
    mock_api = _api(projects=[MockProject("p_odak", "Odak & Gelişim"), MockProject("p2", "Kişisel")])
    mock_get_client.return_value = mock_api

    result = create_task(content="X", project_name="odak")

    assert "• Project: Odak & Gelişim" in result
    assert "• Project: odak" not in result
    assert mock_api.add_task.call_args.kwargs["project_id"] == "p_odak"


@pytest.mark.parametrize("alias", ["Inbox", "GELEN KUTUSU", "GelenKutusu", "Gelen Kutusu"])
@patch("plugvan.todoist.client.get_api_client")
def test_create_task_inbox_aliases_use_listed_inbox(mock_get_client, alias):
    mock_api = _api(projects=[MockProject("inbox_1", "Inbox", is_inbox=True), MockProject("p2", "Inbox Zero")])
    mock_get_client.return_value = mock_api

    result = create_task(content="X", project_name=alias)

    assert "✅ Task created successfully!" in result
    assert "• Project: Inbox" in result
    assert mock_api.add_task.call_args.kwargs["project_id"] == "inbox_1"


@patch("plugvan.todoist.client.get_api_client")
def test_create_task_inbox_alias_without_listed_inbox_omits_project_id(mock_get_client):
    mock_api = _api(projects=[MockProject("p2", "Inbox Zero")])
    mock_get_client.return_value = mock_api

    result = create_task(content="X", project_name="Inbox")

    assert "• Project: Inbox" in result
    assert mock_api.add_task.call_args.kwargs["project_id"] is None


@patch("plugvan.todoist.client.get_api_client")
def test_create_task_section_is_searched_only_in_resolved_project(mock_get_client):
    mock_api = _api(
        projects=[MockProject("p1", "Yazılım"), MockProject("p2", "Ev")],
        sections=[MockSection("sec_1", "Backlog", project_id="p1"), MockSection("sec_2", "Backlog", project_id="p2")],
    )
    mock_get_client.return_value = mock_api

    result = create_task(content="X", project_name="Ev", section_name_or_id="Backlog")

    assert "• Section: Backlog (ID: sec_2)" in result
    mock_api.get_sections.assert_called_once_with(project_id="p2")
    assert mock_api.add_task.call_args.kwargs["section_id"] == "sec_2"


@patch("plugvan.todoist.client.get_api_client")
def test_create_task_partial_section_name_is_not_found(mock_get_client):
    mock_api = _api(
        projects=[MockProject("p1", "Yazılım")],
        sections=[MockSection("sec_1", "Backlog", project_id="p1")],
    )
    mock_get_client.return_value = mock_api

    result = create_task(content="X", project_name="Yazılım", section_name_or_id="Back")

    assert result == "⚠️ Section not found: 'Back'."
    assert write_call_count(mock_api) == 0


@patch("plugvan.todoist.client.get_api_client")
def test_create_task_ambiguous_section_creates_nothing(mock_get_client):
    mock_api = _api(
        projects=[MockProject("p1", "Yazılım")],
        sections=[MockSection("sec_1", "Backlog", project_id="p1"), MockSection("sec_2", "backlog", project_id="p1")],
    )
    mock_get_client.return_value = mock_api

    result = create_task(content="X", project_name="Yazılım", section_name_or_id="Backlog")

    assert result.startswith("⚠️ Multiple sections found for 'Backlog'; please use the section ID:")
    assert write_call_count(mock_api) == 0


@patch("plugvan.todoist.client.get_api_client")
def test_create_task_default_project_scopes_section_to_inbox(mock_get_client):
    mock_api = _api(
        projects=[MockProject("inbox_1", "Inbox", is_inbox=True), MockProject("p2", "Ev")],
        sections=[MockSection("sec_in", "Backlog", project_id="inbox_1"), MockSection("sec_ev", "Backlog", project_id="p2")],
    )
    mock_get_client.return_value = mock_api

    result = create_task(content="X", section_name_or_id="Backlog")

    assert "• Section: Backlog (ID: sec_in)" in result
    assert mock_api.add_task.call_args.kwargs["project_id"] == "inbox_1"
    assert mock_api.add_task.call_args.kwargs["section_id"] == "sec_in"


@patch("plugvan.todoist.client.get_api_client")
def test_create_task_default_project_without_listed_inbox_section_not_found(mock_get_client):
    mock_api = _api(
        projects=[MockProject("p2", "Ev")],
        sections=[MockSection("sec_ev", "Backlog", project_id="p2")],
    )
    mock_get_client.return_value = mock_api

    result = create_task(content="X", section_name_or_id="Backlog")

    assert result == "⚠️ Section not found: 'Backlog'."
    mock_api.get_sections.assert_not_called()
    assert write_call_count(mock_api) == 0


@patch("plugvan.todoist.client.get_api_client")
def test_create_task_lookup_failures_are_generic_and_sanitized(mock_get_client, caplog):
    mock_api = _api(projects=[MockProject("p1", "Yazılım")])
    mock_get_client.return_value = mock_api

    mock_api.get_projects.side_effect = _make_http_status_error(500, "upstream secret body")
    with caplog.at_level(logging.ERROR, logger="todoist_mcp"):
        project_failed = create_task(content="X", project_name="Yazılım")

    mock_api.get_projects.side_effect = None
    mock_api.get_sections.side_effect = RuntimeError("section list secret")
    with caplog.at_level(logging.ERROR, logger="todoist_mcp"):
        section_failed = create_task(content="X", project_name="Yazılım", section_name_or_id="Backlog")

    generic = "❌ Todoist task creation failed. Check server logs for details."
    assert project_failed == generic
    assert section_failed == generic
    assert write_call_count(mock_api) == 0
    for text in (project_failed, section_failed, caplog.text):
        assert "upstream secret body" not in text
        assert "500 error" not in text
        assert "section list secret" not in text
    assert "error_type=HTTPStatusError" in caplog.text
    assert "error_type=RuntimeError" in caplog.text


@patch("plugvan.todoist.client.get_api_client")
def test_update_task_ambiguous_project_writes_nothing(mock_get_client):
    mock_api = _api(projects=[MockProject("p1", "Proje A"), MockProject("p2", "Proje B")])
    mock_get_client.return_value = mock_api

    result = update_task(task_id="task_1", content="x", project_name="Proje")

    assert result.startswith("⚠️ Multiple projects found for 'Proje'; please use the project ID:")
    assert write_call_count(mock_api) == 0


@patch("plugvan.todoist.client.get_api_client")
def test_update_task_unique_partial_project_shows_resolved_name(mock_get_client):
    mock_api = _api(projects=[MockProject("p_odak", "Odak & Gelişim")])
    mock_get_client.return_value = mock_api

    result = update_task(task_id="task_1", project_name="odak")

    assert "Target Project: 'Odak & Gelişim' (ID: p_odak)" in result
    mock_api.move_task.assert_called_once_with(task_id="task_1", project_id="p_odak")


@patch("plugvan.todoist.client.get_api_client")
def test_update_task_section_without_project_is_scoped_to_current_project(mock_get_client):
    mock_api = _api(
        sections=[MockSection("sec_1", "Backlog", project_id="p1"), MockSection("sec_2", "Backlog", project_id="p2")],
    )
    mock_api.get_task.return_value = MagicMock(project_id="p2")
    mock_get_client.return_value = mock_api

    result = update_task(task_id="task_1", section_name_or_id="Backlog")

    assert "Target Section: 'Backlog' (ID: sec_2)" in result
    mock_api.get_task.assert_called_once_with(task_id="task_1")
    mock_api.get_sections.assert_called_once_with(project_id="p2")
    mock_api.move_task.assert_called_once_with(task_id="task_1", section_id="sec_2")


@patch("plugvan.todoist.client.get_api_client")
def test_update_task_section_not_found_writes_nothing(mock_get_client):
    mock_api = _api(
        projects=[MockProject("p1", "Yazılım")],
        sections=[MockSection("sec_1", "Backlog", project_id="p1")],
    )
    mock_get_client.return_value = mock_api

    result = update_task(task_id="task_1", content="x", project_name="Yazılım", section_name_or_id="Back")

    assert result == "⚠️ Target section not found: 'Back'."
    assert write_call_count(mock_api) == 0


@patch("plugvan.todoist.client.get_api_client")
def test_update_task_inbox_alias_without_listed_inbox_writes_nothing(mock_get_client):
    """Moving needs a project ID; with no Inbox listed there is none, so nothing is written."""
    mock_api = _api(projects=[MockProject("p1", "Yazılım")])
    mock_get_client.return_value = mock_api

    result = update_task(task_id="task_1", content="x", project_name="Inbox")

    assert result == "⚠️ Target project not found: 'Inbox'."
    assert write_call_count(mock_api) == 0


@patch("plugvan.todoist.client.get_api_client")
def test_update_task_lookup_failures_are_generic_and_sanitized(mock_get_client, caplog):
    mock_api = _api(projects=[MockProject("p1", "Yazılım")])
    mock_get_client.return_value = mock_api
    generic = "❌ Failed to update task in Todoist (ID: task_1). Check server logs for details."

    mock_api.get_projects.side_effect = _make_http_status_error(503, "upstream secret body")
    with caplog.at_level(logging.ERROR, logger="todoist_mcp"):
        project_failed = update_task(task_id="task_1", content="x", project_name="Yazılım")

    mock_api.get_projects.side_effect = None
    mock_api.get_task.side_effect = RuntimeError("current task secret")
    with caplog.at_level(logging.ERROR, logger="todoist_mcp"):
        current_failed = update_task(task_id="task_1", content="x", section_name_or_id="Backlog")

    assert project_failed == generic
    assert current_failed == generic
    assert write_call_count(mock_api) == 0
    for text in (project_failed, current_failed, caplog.text):
        assert "upstream secret body" not in text
        assert "503 error" not in text
        assert "current task secret" not in text
    assert "error_type=HTTPStatusError" in caplog.text
    assert "error_type=RuntimeError" in caplog.text


@patch("plugvan.todoist.client.get_api_client")
def test_update_task_current_project_http_error_logs_error_type_only(mock_get_client, caplog):
    """The get_task lookup used to scope a section is a resolution step, so an HTTP error there
    must not reach the server log as a status code or response body."""
    mock_api = _api()
    mock_api.get_task.side_effect = _make_http_status_error(502, "upstream secret body")
    mock_get_client.return_value = mock_api

    with caplog.at_level(logging.DEBUG, logger="todoist_mcp"):
        result = update_task(task_id="task_1", content="x", section_name_or_id="Backlog")

    assert result == "❌ Failed to update task in Todoist (ID: task_1). Check server logs for details."
    assert write_call_count(mock_api) == 0
    assert "upstream secret body" not in caplog.text
    assert "status=502" not in caplog.text
    assert "502" not in caplog.text
    assert "error_type=HTTPStatusError" in caplog.text


# =====================================================================
# HTTP ERROR DETAIL LOGGING
# =====================================================================
# A failing Todoist HTTP call logs its status at ERROR; the response body, which can echo user
# content and account data, is logged only at DEBUG. The server runs at INFO by default.

RESPONSE_BODY_SENTINEL = "SENTINEL-RESPONSE-BODY-do-not-log"


def _create_task_500(mock_api):
    mock_api.get_projects.return_value = [[]]
    mock_api.add_task.side_effect = _make_http_status_error(500, text=f"upstream: {RESPONSE_BODY_SENTINEL}")
    return create_task(content="Body logging task")


def _update_task_unparent_404(mock_api):
    # parent_id="" without a project or section looks up the task's current project with an
    # unwrapped get_task call; its HTTP error falls through to the generic failure branch.
    mock_api.get_task.side_effect = _make_http_status_error(404, text=f"not found: {RESPONSE_BODY_SENTINEL}")
    return update_task(task_id="task_child", parent_id="")


def _create_task_deadline_403(mock_api):
    mock_api.get_projects.return_value = [[]]
    mock_api.add_task.side_effect = _make_http_status_error(403, text=f"forbidden: {RESPONSE_BODY_SENTINEL}")
    return create_task(content="Deadline task", deadline_date="2026-09-01")


HTTP_FAILURE_SCENARIOS = [
    pytest.param(
        _create_task_500, 500,
        "❌ Todoist task creation failed. Check server logs for details.",
        id="create_task-500",
    ),
    pytest.param(
        _update_task_unparent_404, 404,
        "❌ Failed to update task in Todoist (ID: task_child). Check server logs for details.",
        id="update_task-parent_id-empty-get_task-404",
    ),
    pytest.param(
        _create_task_deadline_403, 403,
        "❌ The deadline feature is not available on the Todoist Free/Beginner plan "
        "— a Pro or Business plan is required (403 Forbidden).",
        id="create_task-deadline-403",
    ),
]


@pytest.mark.parametrize("level", [logging.INFO, logging.WARNING], ids=["INFO", "WARNING"])
@pytest.mark.parametrize("scenario, status, expected_message", HTTP_FAILURE_SCENARIOS)
@patch("plugvan.todoist.client.get_api_client")
def test_http_error_body_is_not_logged_above_debug(mock_get_client, caplog, scenario, status, expected_message, level):
    mock_api = MagicMock()
    mock_get_client.return_value = mock_api

    with caplog.at_level(level, logger="todoist_mcp"):
        result = scenario(mock_api)

    assert result == expected_message
    assert RESPONSE_BODY_SENTINEL not in caplog.text
    assert any(
        record.levelno == logging.ERROR and f"status={status}" in record.getMessage()
        for record in caplog.records
    ), "the HTTP status is no longer logged at ERROR"


@pytest.mark.parametrize("scenario, status, expected_message", HTTP_FAILURE_SCENARIOS)
@patch("plugvan.todoist.client.get_api_client")
def test_http_error_body_is_logged_only_at_debug(mock_get_client, caplog, scenario, status, expected_message):
    mock_api = MagicMock()
    mock_get_client.return_value = mock_api

    with caplog.at_level(logging.DEBUG, logger="todoist_mcp"):
        result = scenario(mock_api)

    assert result == expected_message
    body_records = [record for record in caplog.records if RESPONSE_BODY_SENTINEL in record.getMessage()]
    assert body_records, "the response body is not logged at DEBUG"
    assert all(record.levelno == logging.DEBUG for record in body_records), [
        logging.getLevelName(record.levelno) for record in body_records
    ]


# =====================================================================
# REQUEST URL LOGGING
# =====================================================================
# httpx logs every HTTP response at INFO with the full request URL, which for list_tasks carries
# the user's filter query. The real SDK runs here against a fake transport, so the request and
# any log line about it are httpx's own. The root conftest restores the httpx logger's level.

FILTER_WITH_USER_CONTENT = "#Secret Project & @private_label & search: salary"
# Parts of the request URL and of the filter that survive URL encoding.
LEAK_MARKERS = ("api.todoist.com", "tasks/filter", "Secret", "private_label", "salary")


@pytest.mark.parametrize(
    "status, expected_message",
    [
        pytest.param(200, f"ℹ️ No open tasks match the filter '{FILTER_WITH_USER_CONTENT}'.", id="200"),
        pytest.param(400, "❌ Failed to retrieve tasks from Todoist. Check server logs for details.", id="400"),
    ],
)
@patch("plugvan.todoist.client.get_api_client")
def test_list_tasks_request_url_is_not_logged(mock_get_client, caplog, status, expected_message):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(status, json={"results": [], "next_cursor": None})

    todoist.configure_logging()
    with httpx.Client(transport=httpx.MockTransport(respond)) as http_client:
        mock_get_client.return_value = TodoistAPI("fake-token", client=http_client)
        # The root logger at INFO, the server's default. No level is set on the httpx logger
        # here: that would override the code under test.
        with caplog.at_level(logging.INFO):
            result = list_tasks(filter_query=FILTER_WITH_USER_CONTENT)

    assert result == expected_message
    assert len(requests) == 1, "the fake transport did not answer exactly one request"
    leaked = [marker for marker in LEAK_MARKERS if marker in caplog.text]
    assert not leaked, f"request URL or filter text reached the logs {leaked}:\n{caplog.text}"
