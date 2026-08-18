"""
AI tool definitions for Gemini function calling.

This module defines the tools (functions) that the AI agent can call.
Each tool maps to a TaskService method. The AI decides when to call
a tool based on the user's natural language input.

Architecture:
    User message → Gemini AI (with tool definitions)
        → function_call response → execute_tool() → TaskService
        → function result → back to Gemini → natural language reply

Security: Tools receive telegram_user_id from the handler (trusted),
NOT from the AI or user input.
"""

from google.genai import types

from app.core.logging import get_logger
from app.services.task_service import TaskService
from app.services.daily_plan_service import DailyPlanService
from app.services.history_service import HistoryService

logger = get_logger(__name__)


# ──────────────────────────────────────────────
# Tool Definitions (Gemini FunctionDeclarations)
# ──────────────────────────────────────────────

TASK_TOOLS = types.Tool(
    function_declarations=[
        types.FunctionDeclaration(
            name="create_task",
            description=(
                "Buat tugas/task baru untuk pengguna. "
                "Gunakan saat pengguna ingin menambahkan tugas, kegiatan, atau jadwal baru. "
                "Contoh: 'Besok jam 7 pagi olahraga', 'Tambahkan tugas mengerjakan project'."
            ),
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "title": types.Schema(
                        type="STRING",
                        description="Judul atau nama tugas. Wajib diisi.",
                    ),
                    "description": types.Schema(
                        type="STRING",
                        description="Deskripsi atau catatan tambahan untuk tugas (opsional).",
                    ),
                    "due_date": types.Schema(
                        type="STRING",
                        description=(
                            "Tanggal dan waktu deadline dalam format ISO 8601 "
                            "(contoh: '2026-08-15T07:00:00+07:00'). "
                            "Konversikan tanggal relatif seperti 'besok', 'lusa', "
                            "'minggu depan' ke format absolut berdasarkan waktu saat ini."
                        ),
                    ),
                    "priority": types.Schema(
                        type="STRING",
                        description="Prioritas tugas: low, medium, high, atau urgent. Default: medium.",
                        enum=["low", "medium", "high", "urgent"],
                    ),
                },
                required=["title"],
            ),
        ),
        types.FunctionDeclaration(
            name="list_tasks",
            description=(
                "Tampilkan daftar tugas pengguna. "
                "Gunakan saat pengguna ingin melihat tugas-tugas mereka. "
                "Contoh: 'Apa saja tugas saya besok?', 'Lihat semua tugas', "
                "'Tugas yang belum selesai'."
            ),
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "status": types.Schema(
                        type="STRING",
                        description="Filter berdasarkan status: pending, in_progress, completed, cancelled.",
                        enum=["pending", "in_progress", "completed", "cancelled"],
                    ),
                    "date_from": types.Schema(
                        type="STRING",
                        description="Tampilkan tugas mulai dari tanggal ini (ISO 8601).",
                    ),
                    "date_to": types.Schema(
                        type="STRING",
                        description="Tampilkan tugas sampai tanggal ini (ISO 8601).",
                    ),
                    "title_search": types.Schema(
                        type="STRING",
                        description="Cari tugas berdasarkan judul (substring, case-insensitive).",
                    ),
                },
            ),
        ),
        types.FunctionDeclaration(
            name="update_task",
            description=(
                "Update/ubah tugas yang sudah ada. "
                "Gunakan saat pengguna ingin mengubah detail tugas. "
                "Contoh: 'Ubah tugas olahraga menjadi jam 8 pagi'. "
                "Perlu task_id — jika belum tahu, gunakan list_tasks dulu untuk mencarinya."
            ),
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "task_id": types.Schema(
                        type="INTEGER",
                        description="ID tugas yang ingin diubah. Wajib diisi.",
                    ),
                    "title": types.Schema(
                        type="STRING",
                        description="Judul baru (opsional).",
                    ),
                    "description": types.Schema(
                        type="STRING",
                        description="Deskripsi baru (opsional).",
                    ),
                    "due_date": types.Schema(
                        type="STRING",
                        description="Tanggal/waktu baru dalam format ISO 8601 (opsional).",
                    ),
                    "priority": types.Schema(
                        type="STRING",
                        description="Prioritas baru: low, medium, high, urgent (opsional).",
                        enum=["low", "medium", "high", "urgent"],
                    ),
                },
                required=["task_id"],
            ),
        ),
        types.FunctionDeclaration(
            name="complete_task",
            description=(
                "Tandai tugas sebagai selesai/completed. "
                "Gunakan saat pengguna ingin menyelesaikan tugas. "
                "Contoh: 'Selesaikan tugas mengerjakan project'. "
                "Perlu task_id — jika belum tahu, gunakan list_tasks dulu."
            ),
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "task_id": types.Schema(
                        type="INTEGER",
                        description="ID tugas yang ingin diselesaikan. Wajib diisi.",
                    ),
                },
                required=["task_id"],
            ),
        ),
        types.FunctionDeclaration(
            name="cancel_task",
            description=(
                "Batalkan tugas. "
                "Gunakan saat pengguna ingin membatalkan tugas. "
                "Contoh: 'Batalkan tugas belajar malam ini'. "
                "Perlu task_id — jika belum tahu, gunakan list_tasks dulu."
            ),
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "task_id": types.Schema(
                        type="INTEGER",
                        description="ID tugas yang ingin dibatalkan. Wajib diisi.",
                    ),
                },
                required=["task_id"],
            ),
        ),
        types.FunctionDeclaration(
            name="generate_daily_plan",
            description=(
                "Buat rencana/jadwal harian berdasarkan tugas pengguna. "
                "Gunakan saat pengguna meminta jadwal, rencana, atau agenda harian. "
                "Contoh: 'Jadwal hari ini', 'Buat jadwal besok', "
                "'Apa agenda saya minggu depan?', 'Plan my day'. "
                "JANGAN gunakan list_tasks untuk permintaan jadwal harian — "
                "gunakan generate_daily_plan yang memberikan data terstruktur "
                "termasuk tugas terjadwal, overdue, dan backlog."
            ),
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "target_date": types.Schema(
                        type="STRING",
                        description=(
                            "Tanggal yang diminta dalam format ISO 8601 "
                            "(contoh: '2026-08-18'). "
                            "Jika pengguna bilang 'hari ini', gunakan tanggal hari ini. "
                            "Jika 'besok', gunakan tanggal besok. "
                            "Jika tidak disebutkan, default ke hari ini."
                        ),
                    ),
                },
            ),
        ),
        types.FunctionDeclaration(
            name="get_productivity_statistics",
            description=(
                "Dapatkan statistik produktivitas dan history tugas pengguna. "
                "Gunakan INI SAJA saat pengguna menanyakan statistik, produktivitas, "
                "completion rate, atau performa mereka (misal: 'Bagaimana produktivitas "
                "saya minggu ini?', 'Berapa task yang selesai bulan ini?'). "
                "JANGAN gunakan untuk melihat daftar tugas biasa."
            ),
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "start_date": types.Schema(
                        type="STRING",
                        description=(
                            "Tanggal awal rentang waktu dalam format ISO 8601 "
                            "(contoh: '2026-08-12'). "
                            "Tentukan berdasarkan ucapan pengguna seperti 'minggu ini', "
                            "'bulan lalu', dsb."
                        ),
                    ),
                    "end_date": types.Schema(
                        type="STRING",
                        description=(
                            "Tanggal akhir rentang waktu dalam format ISO 8601 "
                            "(contoh: '2026-08-18'). "
                            "Seringkali adalah hari ini jika rentangnya 'minggu ini'."
                        ),
                    ),
                },
            ),
        ),
    ]
)


# ──────────────────────────────────────────────
# Tool Execution
# ──────────────────────────────────────────────

def _safe_int(val, default: int = 0) -> int:
    """Safely convert value to int without raising ValueError/TypeError."""
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


async def execute_tool(
    tool_name: str,
    tool_args: dict,
    telegram_user_id: int,
) -> dict:
    """
    Execute a tool call from the AI and return the result.

    The telegram_user_id is injected by the handler (trusted source),
    not from AI output, ensuring user isolation.

    Args:
        tool_name: Name of the tool to execute.
        tool_args: Arguments from the AI's function_call.
        telegram_user_id: Authenticated user ID from Telegram.

    Returns:
        Tool execution result as a dictionary.
    """
    logger.info(f"Executing tool '{tool_name}' for user {telegram_user_id} with args: {tool_args}")

    try:
        if tool_name == "create_task":
            return await TaskService.create_task(
                telegram_user_id=telegram_user_id,
                title=tool_args.get("title", ""),
                description=tool_args.get("description"),
                due_date=tool_args.get("due_date"),
                priority=tool_args.get("priority", "medium"),
            )

        elif tool_name == "list_tasks":
            return await TaskService.list_tasks(
                telegram_user_id=telegram_user_id,
                status=tool_args.get("status"),
                date_from=tool_args.get("date_from"),
                date_to=tool_args.get("date_to"),
                title_search=tool_args.get("title_search"),
            )

        elif tool_name == "update_task":
            return await TaskService.update_task(
                telegram_user_id=telegram_user_id,
                task_id=_safe_int(tool_args.get("task_id")),
                title=tool_args.get("title"),
                description=tool_args.get("description"),
                due_date=tool_args.get("due_date"),
                priority=tool_args.get("priority"),
            )

        elif tool_name == "complete_task":
            return await TaskService.complete_task(
                telegram_user_id=telegram_user_id,
                task_id=_safe_int(tool_args.get("task_id")),
            )

        elif tool_name == "cancel_task":
            return await TaskService.cancel_task(
                telegram_user_id=telegram_user_id,
                task_id=_safe_int(tool_args.get("task_id")),
            )

        elif tool_name == "generate_daily_plan":
            return await DailyPlanService.get_daily_plan(
                telegram_user_id=telegram_user_id,
                target_date=tool_args.get("target_date"),
            )

        elif tool_name == "get_productivity_statistics":
            return await HistoryService.get_statistics(
                telegram_user_id=telegram_user_id,
                start_date=tool_args.get("start_date"),
                end_date=tool_args.get("end_date"),
            )

        else:
            logger.warning(f"Unknown tool called: {tool_name}")
            return {"success": False, "error": f"Tool '{tool_name}' tidak dikenal."}

    except Exception as e:
        logger.error(f"Tool execution error ({tool_name}): {e}")
        return {"success": False, "error": "Terjadi kesalahan saat menjalankan operasi."}
