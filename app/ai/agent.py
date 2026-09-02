"""
AI Agent — orchestrates tool-calling between Gemini and TaskService.

This is the brain of Phase 4. The agent:
1. Receives a user message and their Telegram user ID
2. Sends the message to Gemini with tool definitions
3. If Gemini returns a function_call → executes the tool → sends result back
4. Repeats until Gemini returns a text response (multi-turn support)
5. Returns the final natural language response to the user

The agent supports multi-turn function calling so Gemini can:
- list_tasks to find a task ID, then complete_task with that ID
- All within a single user interaction

Security: telegram_user_id comes from the handler (trusted),
not from AI output or user input.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from google import genai
from google.genai import types

from app.ai.base import LLMError, LLMRateLimitError
from app.ai.tools import TASK_TOOLS, MEMORY_TOOLS, execute_tool
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# Maximum function-calling turns to prevent infinite loops
MAX_TOOL_TURNS = 5


def _get_agent_system_prompt() -> str:
    """
    Build the system prompt for the AI agent with tool-calling context.

    Includes the current date/time so the AI can resolve relative dates
    like 'besok', 'lusa', 'minggu depan'.
    """
    tz = ZoneInfo(settings.timezone)
    now = datetime.now(tz)

    # Indonesian day names
    day_names = {
        0: "Senin", 1: "Selasa", 2: "Rabu", 3: "Kamis",
        4: "Jumat", 5: "Sabtu", 6: "Minggu",
    }
    day_name = day_names[now.weekday()]

    return f"""Kamu adalah AI Secretary, asisten pribadi yang cerdas dan ramah.

## Peran Utama
Kamu adalah sekretaris AI pribadi yang membantu pengguna mengatur tugas, jadwal, dan kegiatan mereka.

## Waktu Saat Ini
- Tanggal: {now.strftime('%Y-%m-%d')} ({day_name})
- Waktu: {now.strftime('%H:%M')} WIB
- Timezone: {settings.timezone} (UTC+7)

## Referensi Waktu Relatif
Berdasarkan waktu saat ini:
- "hari ini" = {now.strftime('%Y-%m-%d')}
- "besok" = {(now + __import__('datetime').timedelta(days=1)).strftime('%Y-%m-%d')}
- "lusa" = {(now + __import__('datetime').timedelta(days=2)).strftime('%Y-%m-%d')}
- "minggu depan" = tanggal yang sama minggu berikutnya

## Aturan Penggunaan Tools
1. Gunakan tools jika diperlukan untuk operasi terkait tugas/task ATAU long-term memory pengguna.
2. Untuk percakapan biasa, sapaan, pertanyaan umum — jawab langsung TANPA memanggil tools.
3. Saat membuat tugas, konversikan semua referensi waktu relatif ke format ISO 8601 absolut.
4. Jika informasi penting kurang (misal judul tugas tidak jelas), tanyakan klarifikasi.
5. Jika pengguna menyebut tugas tanpa ID, gunakan list_tasks dulu untuk menemukan ID-nya.
6. Setelah operasi berhasil, konfirmasi dengan detail yang jelas.
7. Format due_date dalam ISO 8601 dengan timezone +07:00 (contoh: 2026-08-15T07:00:00+07:00).
8. Untuk permintaan jadwal/rencana/agenda harian secara umum, gunakan generate_daily_plan (BUKAN list_tasks).
   Contoh: "Jadwal hari ini", "Buat jadwal besok", "Plan my day", "Agenda minggu depan".
9. Untuk mencari tugas spesifik berdasarkan judul atau kata kunci, HANYA gunakan list_tasks dengan parameter title_search.
   Contoh: "Kapan jadwal database?", "Cari tugas presentasi".
10. Saat memformat hasil generate_daily_plan, susun sebagai jadwal terstruktur yang rapi:
   - Tampilkan tugas terjadwal diurutkan berdasarkan waktu
   - Sebutkan tugas overdue yang perlu diperhatikan
   - Tampilkan tugas backlog (tanpa deadline) sebagai saran tambahan
   - Prioritaskan tugas urgent/high di bagian atas
   - Berikan saran produktivitas jika ada waktu kosong
   - JANGAN mengubah, mengarang, atau memodifikasi waktu (due_date) asli dari tugas. Jika tugas tidak memiliki waktu, jangan beri waktu fiktif.
11. Untuk permintaan statistik, history, completion rate, atau produktivitas (contoh: "Produktivitas saya minggu ini", "Berapa task selesai?"), HANYA gunakan get_productivity_statistics. JANGAN gunakan list_tasks.
12. JANGAN PERNAH mengklaim bahwa suatu operasi berhasil jika kamu tidak benar-benar menjalankan tool yang sesuai dan mendapatkan konfirmasi keberhasilan dari hasil tool.
    - Jangan pernah mengklaim tugas telah dibuat, diubah, dibatalkan, atau dihapus kecuali tool yang bersangkutan mengembalikan success=true.
    - Jangan mengarang task_id, tanggal, waktu, atau perubahan database.
    - Jika tidak ada tool yang sesuai untuk permintaan pengguna, katakan dengan jujur bahwa operasi tersebut belum didukung.
    - Selalu dasarkan respons akhir pada HASIL AKTUAL dari tool, bukan asumsi.
13. Untuk membatalkan banyak tugas sekaligus (misal: "bersihkan tugas", "batalkan semua tugas terlambat"):
    a. Panggil list_tasks terlebih dahulu untuk mendapatkan daftar tugas yang relevan beserta task_id-nya.
    b. Kumpulkan task_id dari hasil list_tasks.
    c. Panggil batch_cancel_tasks dengan task_id yang diperoleh.
    d. Laporkan hasil berdasarkan respons tool, BUKAN asumsi.
    e. Jika pengguna hanya bilang "bersihkan" tanpa menjelaskan tugas mana, tanyakan klarifikasi: apakah yang dimaksud tugas yang terlambat (overdue), tugas yang belum selesai (pending), atau tugas tertentu.

## Aturan Long-Term Memory (PENTING)
1. Simpan fakta permanen/jangka panjang tentang pengguna menggunakan `save_memory` (contoh: preferensi, nama, kebiasaan belajar).
2. JANGAN menyimpan task, jadwal, atau aktivitas sementara sebagai memori (jadikan sebagai task biasa).
3. Jika pengguna memberikan fakta atau preferensi baru yang layak diingat, gunakan `save_memory`.
4. Jika kamu membutuhkan informasi personal pengguna untuk memberikan respons terbaik yang tidak ada di context, gunakan `search_memory` terlebih dahulu.
5. Jika pengguna menyatakan bahwa fakta atau preferensinya berubah, WAJIB:
   a. Gunakan `search_memory` untuk mencari fakta lama.
   b. Jika fakta lama ditemukan, gunakan `update_memory` menggunakan memory_id yang ditemukan.
   c. JANGAN menggunakan `save_memory` untuk membuat duplikat.
6. Jika pengguna secara eksplisit meminta kamu melupakan sesuatu, WAJIB gunakan `search_memory` terlebih dahulu untuk mendapatkan memory_id, lalu gunakan `delete_memory`.
7. Setelah memory berhasil disimpan, diperbarui, atau dihapus, konfirmasi secara singkat kepada pengguna.

## Aturan Komunikasi
1. Jawab dengan bahasa yang sama dengan pengguna.
2. Gunakan nada ramah, profesional, dan ringkas.
3. Gunakan emoji secukupnya (tidak berlebihan).
4. Langsung ke inti pesan.
5. Jika pesan tidak jelas, tanyakan klarifikasi dengan sopan.

## Konteks
- Timezone pengguna: {settings.timezone}
- Kamu adalah AI Secretary versi MVP
"""


class AgentService:
    """
    AI Agent that processes messages with tool-calling support.

    Usage:
        agent = AgentService(api_key="...", model="gemini-2.0-flash")
        response = await agent.process_message("Besok olahraga jam 7", user_id=12345)
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
    ):
        # Use provided key if not None, otherwise fall back to settings
        self._api_key = api_key if api_key is not None else settings.gemini_api_key
        self._model = model or settings.gemini_model

        if not self._api_key or not self._api_key.strip():
            raise ValueError("GEMINI_API_KEY is required for AgentService")

        self._client = genai.Client(api_key=self._api_key)
        logger.info(f"AgentService initialized with model: {self._model}")

    async def process_message(
        self,
        user_message: str,
        telegram_user_id: int,
    ) -> str:
        """
        Process a user message, potentially calling tools, and return a response.

        Args:
            user_message: The raw text message from the user.
            telegram_user_id: Authenticated Telegram user ID.

        Returns:
            Natural language response string.

        Raises:
            LLMError: On unrecoverable API failure.
        """
        try:
            from app.services.chat_history_service import ChatHistoryService

            config = types.GenerateContentConfig(
                system_instruction=_get_agent_system_prompt(),
                tools=[TASK_TOOLS, MEMORY_TOOLS],
                automatic_function_calling=types.AutomaticFunctionCallingConfig(
                    disable=True,
                ),
            )

            # Build conversation from history
            recent_messages = await ChatHistoryService.get_recent_messages(telegram_user_id, limit=10)
            contents = []

            for msg in recent_messages:
                contents.append(
                    types.Content(
                        role=msg.role.value,
                        parts=[types.Part.from_text(text=msg.content)],
                    )
                )

            # Fallback for tests or direct calls where the handler didn't save the message yet
            if not contents:
                contents = [
                    types.Content(
                        role="user",
                        parts=[types.Part.from_text(text=user_message)],
                    ),
                ]
            elif contents[-1].parts[0].text != user_message:
                contents.append(
                    types.Content(
                        role="user",
                        parts=[types.Part.from_text(text=user_message)],
                    )
                )

            # Multi-turn tool calling loop
            for turn in range(MAX_TOOL_TURNS):
                response = await self._client.aio.models.generate_content(
                    model=self._model,
                    contents=contents,
                    config=config,
                )

                # Check if the model wants to call a function
                candidate = response.candidates[0]
                has_function_call = False

                for part in candidate.content.parts:
                    if part.function_call:
                        has_function_call = True
                        fc = part.function_call

                        logger.info(
                            f"Agent tool call: {fc.name} "
                            f"(turn {turn + 1}/{MAX_TOOL_TURNS})"
                        )

                        # Execute the tool with the trusted user ID
                        tool_result = await execute_tool(
                            tool_name=fc.name,
                            tool_args=dict(fc.args) if fc.args else {},
                            telegram_user_id=telegram_user_id,
                        )

                        # Append the model's FULL response object (candidate.content)
                        # to preserve thought_signature fields on functionCall parts.
                        # Gemini 3 models require thought_signature to be passed back
                        # in the conversation history — stripping or reconstructing
                        # the Content/Part objects will cause a 400 error.
                        # See: https://ai.google.dev/gemini-api/docs/generate-content/thought-signatures
                        contents.append(candidate.content)
                        contents.append(
                            types.Content(
                                role="user",
                                parts=[
                                    types.Part.from_function_response(
                                        name=fc.name,
                                        response=tool_result,
                                    )
                                ],
                            )
                        )
                        break  # Process next turn

                if not has_function_call:
                    # Model returned a text response — we're done
                    if response.text:
                        return response.text
                    else:
                        return "Maaf, saya tidak bisa memproses permintaan tersebut saat ini."

            # Exceeded max turns
            logger.warning(
                f"Agent exceeded max tool turns ({MAX_TOOL_TURNS}) "
                f"for user {telegram_user_id}"
            )
            return "Maaf, permintaan terlalu kompleks. Silakan coba dengan perintah yang lebih sederhana."

        except Exception as e:
            error_str = str(e).lower()

            if "429" in error_str or "resource exhausted" in error_str or "rate limit" in error_str:
                logger.warning(f"Agent rate limited: {e}")
                raise LLMRateLimitError(
                    f"Rate limited: {e}",
                    provider="gemini",
                    retry_after=60.0,
                )

            logger.error(f"Agent error for user {telegram_user_id}: {e}")
            raise LLMError(
                f"Agent processing failed: {e}",
                provider="gemini",
            )


# ──────────────────────────────────────────────
# Singleton management
# ──────────────────────────────────────────────

_agent_instance: AgentService | None = None


def get_agent() -> AgentService | None:
    """
    Get or create the agent singleton.

    Returns None if API key is not configured.
    """
    global _agent_instance

    if _agent_instance is not None:
        return _agent_instance

    if not settings.gemini_api_key:
        logger.warning("GEMINI_API_KEY not set — agent disabled.")
        return None

    try:
        _agent_instance = AgentService()
        return _agent_instance
    except Exception as e:
        logger.error(f"Failed to create AgentService: {e}")
        return None


def reset_agent() -> None:
    """Reset the agent singleton. Used in testing."""
    global _agent_instance
    _agent_instance = None
