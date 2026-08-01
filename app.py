import asyncio
from datetime import datetime
import json
import os
from pathlib import Path
import re
import signal
import threading
import time

import edge_tts
from flask import Flask, Response, jsonify, send_file, request, send_from_directory
from pypinyin import Style, lazy_pinyin


app = Flask(__name__, static_folder="static")

OUTPUT_DIR = Path(__file__).parent / "outputs"
OUTPUT_DIR.mkdir(exist_ok=True)
DICT_DIR = Path(__file__).parent / "dicts"
CEDICT_PATH = DICT_DIR / "cedict_ts.u8"
CVDICT_PATH = DICT_DIR / "CVDICT.u8"
SAVED_WORDS_FILENAME = "saved_words.txt"
CONFIG_FILE = Path(__file__).parent / "config.json"

DEFAULT_SETTINGS = {
    "hidden_pct": 100,
    "backward_sec": 3,
    "forward_sec": 10,
    "pace": 1.0,
}

def load_settings() -> dict:
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                settings = DEFAULT_SETTINGS.copy()
                settings.update(data)
                return settings
        except Exception:
            pass
    return DEFAULT_SETTINGS.copy()

def save_settings(new_settings: dict) -> dict:
    settings = load_settings()
    settings.update(new_settings)
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"Error saving settings: {e}")
    return settings

IDLE_TIMEOUT_SECONDS = int(
    os.environ.get(
        "CHINESE_TTS_IDLE_MINUTES",
        "30",
    )
) * 60
last_activity_at = time.time()


VOICES = {
    "Xiaoxiao — Nữ, tự nhiên": "zh-CN-XiaoxiaoNeural",
    "Xiaoyi — Nữ, trẻ": "zh-CN-XiaoyiNeural",
    "Yunjian — Nam, trầm": "zh-CN-YunjianNeural",
    "Yunxi — Nam, trẻ": "zh-CN-YunxiNeural",
    "Yunyang — Nam, dẫn chuyện": "zh-CN-YunyangNeural",
    "Yunxia — Nam, trẻ": "zh-CN-YunxiaNeural",
}


def update_activity() -> None:
    global last_activity_at

    last_activity_at = time.time()


def parse_dictionary_file(path: Path) -> dict:
    dictionary = {}

    if not path.exists():
        return dictionary

    pattern = re.compile(
        r"^(\S+)\s+(\S+)\s+\[([^\]]*)\]\s+/(.*)/$"
    )

    with path.open("r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()

            if not line or line.startswith("#"):
                continue

            match = pattern.match(line)

            if not match:
                continue

            traditional, simplified, pinyin, meanings_text = (
                match.groups()
            )
            meanings = [
                meaning.strip()
                for meaning in meanings_text.split("/")
                if meaning.strip()
            ]

            if not meanings:
                continue

            entry = {
                "traditional": traditional,
                "simplified": simplified,
                "pinyin": pinyin,
                "meanings": meanings,
            }

            for key in {traditional, simplified}:
                dictionary.setdefault(key, []).append(entry)

    return dictionary


EN_DICTIONARY = parse_dictionary_file(CEDICT_PATH)
VN_DICTIONARY = parse_dictionary_file(CVDICT_PATH)


def normalize_lookup_word(word: str) -> str:
    return extract_chinese_text(word)


def summarize_meanings(
    dictionary: dict,
    word: str,
    limit: int = 4,
) -> str:
    entries = dictionary.get(word, [])

    if not entries:
        return ""

    meanings = []

    for entry in entries:
        for meaning in entry["meanings"]:
            if meaning.startswith(("CL:", "LT:")):
                continue

            if meaning in meanings:
                continue

            meanings.append(meaning)

            if len(meanings) >= limit:
                return "; ".join(meanings)

    return "; ".join(meanings)


def lookup_dictionary_word(word: str) -> dict:
    normalized_word = normalize_lookup_word(word)

    if not normalized_word:
        return {
            "word": "",
            "pinyin": "",
            "en": "",
            "vn": "",
        }

    return {
        "word": normalized_word,
        "pinyin": chinese_group_to_pinyin(
            normalized_word
        ),
        "en": summarize_meanings(
            EN_DICTIONARY,
            normalized_word,
        ),
        "vn": summarize_meanings(
            VN_DICTIONARY,
            normalized_word,
        ),
    }


def safe_output_folder_name(text: str) -> str:
    display_text = remove_markdown_marks(text)
    first_line = next(
        (
            line.strip()
            for line in display_text.splitlines()
            if line.strip()
        ),
        "Chinese TTS",
    )
    pinyin_title = chinese_group_to_pinyin(
        extract_chinese_text(first_line)
    )
    title = f"{first_line} - {pinyin_title}".strip(" -")
    title = re.sub(r"[\\/:*?\"<>|]", "-", title)
    title = re.sub(r"\s+", " ", title).strip()

    return title[:90] or "Chinese TTS"


def unique_output_folder(base_name: str) -> Path:
    timestamp = datetime.now().strftime(
        "%d-%m-%Y_%H-%M-%S"
    )
    folder = OUTPUT_DIR / f"{base_name} - {timestamp}"

    counter = 2

    while folder.exists():
        folder = OUTPUT_DIR / f"{base_name} - {timestamp}-{counter}"
        counter += 1

    folder.mkdir(parents=True)

    return folder


def get_safe_output_subfolder(folder_name: str):
    if not folder_name:
        return None

    folder = (OUTPUT_DIR / folder_name).resolve()
    output_root = OUTPUT_DIR.resolve()

    if output_root not in folder.parents:
        return None

    if not folder.is_dir():
        return None

    return folder


def format_saved_words_text(words: list) -> str:
    lines = []
    saved_index = 1

    for item in words:
        word = normalize_lookup_word(str(item.get("word", "")))

        if not word:
            continue

        en = str(item.get("en", "")).strip()
        vn = str(item.get("vn", "")).strip()
        pinyin = str(item.get("pinyin", "")).strip()

        lines.append(
            f"{saved_index}. {word} - {pinyin}\n"
            f"   EN: {en}\n"
            f"   VN: {vn}"
        )
        saved_index += 1

    return "\n\n".join(lines) + ("\n" if lines else "")


def idle_shutdown_watchdog() -> None:
    while True:
        time.sleep(60)

        if time.time() - last_activity_at < IDLE_TIMEOUT_SECONDS:
            continue

        print("Idle timeout reached. Shutting down Chinese TTS.")
        os.kill(os.getpid(), signal.SIGTERM)


@app.before_request
def mark_activity():
    update_activity()




def build_character_items(text: str) -> list:
    """
    Tạo danh sách phần tử để hiển thị phần luyện viết.

    - Chữ Hán: tạo ô input.
    - Dấu câu: hiển thị trực tiếp.
    - Xuống dòng: xuống dòng trên giao diện.
    - Khoảng trắng: tạo khoảng cách.
    """

    items = []

    chinese_pattern = re.compile(
        r"[\u3400-\u4dbf\u4e00-\u9fff]"
    )

    punctuation_characters = (
        "，。！？；：、"
        ",.!?;:"
        "“”‘’"
        "（）()"
        "《》〈〉"
        "【】[]"
        "…—-"
    )

    check_segment = 0

    for character in text:
        if chinese_pattern.fullmatch(character):
            items.append(
                {
                    "type": "input",
                    "character": character,
                    "check_segment": check_segment,
                }
            )

        elif character in punctuation_characters:
            items.append(
                {
                    "type": "punctuation",
                    "character": character,
                    "ends_check_segment":
                        has_sentence_punctuation(character),
                }
            )

            if has_sentence_punctuation(character):
                check_segment += 1

        elif character == "\n":
            items.append(
                {
                    "type": "line_break",
                    "character": "",
                }
            )
            check_segment += 1

        elif character.isspace():
            items.append(
                {
                    "type": "space",
                    "character": " ",
                }
            )

    return items


def extract_chinese_groups(text: str) -> list:
    groups = []

    for group in re.findall(r"\S+", text):
        chinese_group = extract_chinese_text(group)

        if chinese_group:
            groups.append(chinese_group)

    return groups


def extract_chinese_check_segments(text: str) -> list:
    segments = []
    current_segment = []
    current_group = []

    def flush_group() -> None:
        nonlocal current_group

        if not current_group:
            return

        current_segment.append(
            {
                "text": "".join(current_group),
                "check": True,
            }
        )
        current_group = []

    def flush_segment() -> None:
        nonlocal current_segment

        flush_group()

        if not current_segment:
            return

        segments.append(current_segment)
        current_segment = []

    for line in text.splitlines():
        for character in line:
            if re.fullmatch(
                r"[\u3400-\u4dbf\u4e00-\u9fff]",
                character,
            ):
                current_group.append(character)
                continue

            flush_group()

            if character.isspace():
                continue

            current_segment.append(
                {
                    "text": character,
                    "check": False,
                }
            )

            if has_sentence_punctuation(character):
                flush_segment()

        flush_segment()

    return segments


def extract_chinese_characters(text: str) -> list:
    chinese_pattern = re.compile(
        r"[\u3400-\u4dbf\u4e00-\u9fff]"
    )

    return [
        character
        for character in text
        if chinese_pattern.fullmatch(character)
    ]


def remove_markdown_marks(text: str) -> str:
    cleaned_lines = []

    for line in text.splitlines():
        line = re.sub(r"^\s*#+\s*", "", line)
        line = line.replace("**", "")
        cleaned_lines.append(line.rstrip())

    return "\n".join(cleaned_lines).strip()


def remove_chinese_group_spaces(text: str) -> str:
    lines = []

    for line in text.splitlines():
        line = re.sub(r"[ \t]+", "", line)
        lines.append(line)

    return "\n".join(lines).strip()


def count_chinese_characters(text: str) -> int:
    return len(
        re.findall(
            r"[\u3400-\u4dbf\u4e00-\u9fff]",
            text,
        )
    )


def extract_chinese_text(text: str) -> str:
    return "".join(
        re.findall(
            r"[\u3400-\u4dbf\u4e00-\u9fff]",
            text,
        )
    )


def split_grouped_text(text: str) -> list:
    groups = [
        group.strip()
        for group in re.split(r"[ \t]+", text.strip())
        if group.strip()
    ]

    if groups:
        return groups

    return [text.strip()] if text.strip() else []


def build_pinyin_tokens(pinyin_line: str) -> list:
    return [
        {
            "pinyin": group,
            "weight": 1,
        }
        for group in split_grouped_text(pinyin_line)
    ]


def normalize_pinyin_spacing(text: str) -> str:
    text = re.sub(r"\s+([,.;:!?，。！？；：])", r"\1", text)

    return text.strip()


def chinese_group_to_pinyin(chinese_group: str) -> str:
    syllables = lazy_pinyin(
        chinese_group,
        style=Style.TONE,
    )

    return normalize_pinyin_spacing(
        " ".join(syllables)
    )


def build_pinyin_tokens_from_chinese(
    chinese_line: str,
) -> list:
    return [
        {
            "pinyin": chinese_group_to_pinyin(
                chinese_group
            ),
            "weight": 1,
        }
        for chinese_group in split_grouped_text(chinese_line)
    ]


def build_reading_tokens(
    chinese_line: str,
) -> list:
    chinese_groups = split_grouped_text(chinese_line)

    if not chinese_groups:
        return []

    return [
        {
            "chinese": chinese_group,
            "weight": max(
                count_chinese_characters(chinese_group),
                1,
            ),
        }
        for chinese_group in chinese_groups
    ]


def has_sentence_punctuation(text: str) -> bool:
    return bool(
        re.search(
            r"[，。！？；：,!?;:]",
            text,
        )
    )


def clean_pinyin_source(text: str) -> str:
    cleaned_lines = []

    for line in text.splitlines():
        line = re.sub(r"^\s*#+\s*", "", line)
        line = line.replace("**", "").strip()

        if not line:
            cleaned_lines.append("")
            continue

        if re.search(
            r"[\u3400-\u4dbf\u4e00-\u9fff]",
            line,
        ):
            continue

        cleaned_lines.append(line)

    return "\n".join(cleaned_lines).strip()


def strip_format_prefix(line: str, prefix: str) -> str:
    return line.split(prefix, 1)[1].strip()


def clean_chinese_format_line(line: str) -> str:
    content = strip_format_prefix(line, "中文:")

    return (
        content
        .replace("|", "")
        .replace(" ", "")
        .strip()
    )


def clean_pinyin_format_line(line: str) -> str:
    content = strip_format_prefix(line, "Pinyin:")
    content = content.replace("|", " ")
    content = re.sub(r"\s+", " ", content).strip()
    content = re.sub(r"\s+([,.;:!?，。！？；：])", r"\1", content)

    return content


def split_format_groups(line: str, prefix: str) -> list:
    content = strip_format_prefix(line, prefix)

    return [
        group.strip().replace(" ", "")
        if prefix == "中文:"
        else re.sub(r"\s+", " ", group.strip())
        for group in content.split("|")
        if group.strip()
    ]


def parse_aligned_lesson(text: str) -> dict:
    lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip()
    ]

    if not any(
        line.startswith("中文:")
        for line in lines
    ):
        return None

    clean_chinese_lines = []
    clean_pinyin_lines = []
    reading_segments = []

    index = 0

    while index < len(lines):
        chinese_line = lines[index]

        if not chinese_line.startswith("中文:"):
            index += 1
            continue

        if index + 1 >= len(lines):
            break

        pinyin_line = lines[index + 1]

        if not pinyin_line.startswith("Pinyin:"):
            index += 1
            continue

        clean_chinese = clean_chinese_format_line(
            chinese_line
        )

        clean_pinyin = clean_pinyin_format_line(
            pinyin_line
        )

        clean_chinese_lines.append(clean_chinese)
        clean_pinyin_lines.append(clean_pinyin)

        chinese_groups = split_format_groups(
            chinese_line,
            "中文:",
        )

        pinyin_groups = split_format_groups(
            pinyin_line,
            "Pinyin:",
        )

        tokens = [
            {
                "chinese": chinese_group,
                "weight": max(
                    count_chinese_characters(chinese_group),
                    1,
                ),
            }
            for chinese_group in chinese_groups
        ]

        if not tokens:
            tokens = build_reading_tokens(clean_chinese)

        pinyin_tokens = [
            {
                "pinyin": pinyin_group,
                "weight": 1,
            }
            for pinyin_group in pinyin_groups
        ]

        if not pinyin_tokens:
            pinyin_tokens = build_pinyin_tokens(clean_pinyin)

        reading_segments.append(
            {
                "chinese": clean_chinese,
                "pinyin": clean_pinyin,
                "weight": max(len(clean_chinese), 1),
                "tokens": tokens,
                "pinyin_tokens": pinyin_tokens,
            }
        )

        index += 2

    if not clean_chinese_lines:
        return None

    return {
        "text": "\n".join(clean_chinese_lines),
        "pinyin": "\n".join(clean_pinyin_lines),
        "reading_segments": reading_segments,
    }


def build_reading_segments(
    text: str,
) -> list:
    chinese_lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip()
    ]

    if not chinese_lines and text.strip():
        chinese_lines = [text.strip()]

    segments = []

    for chinese_line in chinese_lines:
        tokens = build_reading_tokens(chinese_line)
        pinyin_tokens = build_pinyin_tokens_from_chinese(
            chinese_line
        )
        pinyin_line = " ".join(
            token["pinyin"]
            for token in pinyin_tokens
        )

        segments.append(
            {
                "chinese": chinese_line,
                "pinyin": pinyin_line,
                "weight": max(
                    len(
                        remove_chinese_group_spaces(
                            chinese_line
                        )
                    ),
                    1,
                ),
                "tokens": tokens,
                "pinyin_tokens": pinyin_tokens,
            }
        )

    return segments


def flatten_reading_tokens(reading_segments: list) -> list:
    tokens = []

    for segment in reading_segments:
        tokens.extend(segment.get("tokens", []))

    return tokens


def split_tokens_into_sentence_groups(
    tokens: list,
    text_key: str,
) -> list:
    groups = []
    current_group = []

    for token in tokens:
        current_group.append(token)

        if has_sentence_punctuation(
            token.get(text_key, "")
        ):
            groups.append(current_group)
            current_group = []

    if current_group:
        groups.append(current_group)

    return groups


def distribute_pinyin_groups_by_count(
    pinyin_tokens: list,
    group_count: int,
) -> list:
    if group_count <= 0:
        return []

    groups = []
    token_count = len(pinyin_tokens)
    start_index = 0

    for group_index in range(group_count):
        end_index = round(
            token_count
            * (group_index + 1)
            / group_count
        )

        groups.append(pinyin_tokens[start_index:end_index])
        start_index = end_index

    return groups


def apply_pinyin_timings_to_reading_segments(
    reading_segments: list,
) -> None:
    for segment in reading_segments:
        chinese_tokens = [
            token
            for token in segment.get("tokens", [])
            if (
                token.get("start") is not None
                and token.get("end") is not None
            )
        ]

        pinyin_tokens = segment.get("pinyin_tokens", [])

        if not chinese_tokens or not pinyin_tokens:
            continue

        chinese_groups = split_tokens_into_sentence_groups(
            chinese_tokens,
            "chinese",
        )

        pinyin_groups = split_tokens_into_sentence_groups(
            pinyin_tokens,
            "pinyin",
        )

        if len(pinyin_groups) != len(chinese_groups):
            pinyin_groups = distribute_pinyin_groups_by_count(
                pinyin_tokens,
                len(chinese_groups),
            )

        for group_index, chinese_group in enumerate(
            chinese_groups
        ):
            if group_index >= len(pinyin_groups):
                break

            pinyin_group = pinyin_groups[group_index]

            if not pinyin_group:
                continue

            start_time = chinese_group[0]["start"]
            end_time = chinese_group[-1]["end"]
            duration = max(
                end_time - start_time,
                0.01,
            )
            step = duration / len(pinyin_group)

            for token_index, pinyin_token in enumerate(
                pinyin_group
            ):
                token_start = start_time + (step * token_index)

                pinyin_token["start"] = token_start
                pinyin_token["end"] = token_start + step


def apply_word_boundaries_to_reading_segments(
    reading_segments: list,
    boundaries: list,
) -> None:
    tokens = flatten_reading_tokens(reading_segments)
    character_timings = []

    for boundary in boundaries:
        boundary_text = extract_chinese_text(
            boundary.get("text", "")
        )

        if not boundary_text:
            continue

        character_duration = (
            boundary["end"] - boundary["start"]
        ) / len(boundary_text)

        for index, character in enumerate(boundary_text):
            start = (
                boundary["start"]
                + (character_duration * index)
            )

            character_timings.append(
                {
                    "text": character,
                    "start": start,
                    "end": start + character_duration,
                }
            )

    character_index = 0

    for token in tokens:
        target_text = extract_chinese_text(
            token.get("chinese", "")
        )

        if not target_text:
            continue

        token_timings = character_timings[
            character_index:character_index + len(target_text)
        ]

        if len(token_timings) != len(target_text):
            continue

        token["start"] = token_timings[0]["start"]
        token["end"] = token_timings[-1]["end"]
        character_index += len(target_text)


async def create_mp3(
    text: str,
    voice: str,
    output_path: Path,
) -> list:
    tts = edge_tts.Communicate(
        text=text,
        voice=voice,
        rate="-10%",
        boundary="WordBoundary",
    )

    boundaries = []

    with output_path.open("wb") as audio_file:
        async for chunk in tts.stream():
            if chunk["type"] == "audio":
                audio_file.write(chunk["data"])

            elif chunk["type"] == "WordBoundary":
                start = chunk["offset"] / 10_000_000
                duration = chunk["duration"] / 10_000_000

                boundaries.append(
                    {
                        "text": chunk.get("text", ""),
                        "start": start,
                        "end": start + duration,
                    }
                )

    return boundaries


async def create_mp3_and_track(
    text: str,
    voice: str,
    output_path: Path,
    reading_segments: list,
) -> None:
    boundaries = await create_mp3(
        text=text,
        voice=voice,
        output_path=output_path,
    )

    apply_word_boundaries_to_reading_segments(
        reading_segments,
        boundaries,
    )

    apply_pinyin_timings_to_reading_segments(
        reading_segments
    )




@app.route("/")
def index():
    return send_file("templates/index.html")


@app.route("/api/voices")
def get_voices():
    voice_list = [
        {
            "name": v_name,
            "short": v_code,
            "gender": "Female" if "Nữ" in v_name else "Male",
            "locale": "zh-CN",
        }
        for v_name, v_code in VOICES.items()
    ]
    return jsonify(voice_list)


@app.route("/api/settings", methods=["GET", "POST"])
def api_settings():
    if request.method == "POST":
        data = request.get_json() or {}
        updated = save_settings(data)
        return jsonify(updated)
    return jsonify(load_settings())


@app.route("/api/synthesize", methods=["POST"])
def synthesize():
    data = request.get_json() or {}
    text = data.get("text", "").strip()
    voice = data.get("voice", "zh-CN-XiaoxiaoNeural")

    if not text:
        return jsonify({"error": "Văn bản không được để trống"}), 400

    if voice not in VOICES.values():
        voice = "zh-CN-XiaoxiaoNeural"

    display_text = remove_markdown_marks(text)
    processed_text = remove_chinese_group_spaces(display_text)

    lesson_folder = unique_output_folder(
        safe_output_folder_name(display_text)
    )
    filename = "audio.mp3"
    output_path = lesson_folder / filename

    boundaries_sec = []

    async def _generate():
        tts = edge_tts.Communicate(
            text=processed_text,
            voice=voice,
            rate="-10%",
            boundary="WordBoundary",
        )

        with output_path.open("wb") as audio_file:
            async for chunk in tts.stream():
                if chunk["type"] == "audio":
                    audio_file.write(chunk["data"])

                elif chunk["type"] == "WordBoundary":
                    start = chunk["offset"] / 10_000_000
                    duration = chunk["duration"] / 10_000_000

                    boundaries_sec.append(
                        {
                            "text": chunk.get("text", ""),
                            "start": start,
                            "duration": duration,
                        }
                    )

    try:
        asyncio.run(_generate())
    except Exception as exc:
        print(f"TTS error: {exc}")
        return jsonify({"error": f"Không thể tạo MP3: {exc}"}), 500

    for wb in boundaries_sec:
        txt = wb.get("text", "")
        wb["pinyin"] = chinese_group_to_pinyin(txt) if txt else ""

    chinese_chars = set(re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff]", processed_text))
    pinyin_map = {ch: chinese_group_to_pinyin(ch) for ch in chinese_chars}

    return jsonify(
        {
            "audio_url": f"/outputs/{lesson_folder.name}/{filename}",
            "folder_name": lesson_folder.name,
            "word_boundaries": boundaries_sec,
            "pinyin_map": pinyin_map,
        }
    )


@app.route("/api/lookup", methods=["POST"])
def api_lookup_word():
    data = request.get_json() or {}
    word = data.get("word", "").strip()

    if not word:
        return jsonify({"error": "Word is required"}), 400

    res = lookup_dictionary_word(word)
    return jsonify(
        {
            "word": res.get("word", word),
            "phonetic": res.get("pinyin", ""),
            "pinyin": res.get("pinyin", ""),
            "en": res.get("en", ""),
            "vn": res.get("vn", ""),
        }
    )


@app.route("/lookup")
def lookup_word():
    word = request.args.get("word", "")
    res = lookup_dictionary_word(word)
    return jsonify(
        {
            "word": res.get("word", word),
            "phonetic": res.get("pinyin", ""),
            "pinyin": res.get("pinyin", ""),
            "en": res.get("en", ""),
            "vn": res.get("vn", ""),
        }
    )


@app.route("/api/save-vocab", methods=["POST"])
def api_save_vocab():
    payload = request.get_json(silent=True) or {}
    folder_name = payload.get("folder_name") or payload.get("folder", "")
    folder = get_safe_output_subfolder(str(folder_name)) if folder_name else None

    if folder is None:
        target_dir = OUTPUT_DIR / "general_vocab"
        target_dir.mkdir(exist_ok=True)
        folder = target_dir

    words = payload.get("words", [])

    if not isinstance(words, list):
        return jsonify({"error": "Danh sách từ không hợp lệ."}), 400

    file_path = folder / "vocabulary.txt"
    lines = [
        "==================================================",
        "             SAVED VOCABULARY LIST                ",
        "==================================================\n"
    ]

    for idx, item in enumerate(words, 1):
        stt = item.get("stt", idx)
        w = normalize_lookup_word(str(item.get("word", ""))) or str(item.get("word", "")).strip()

        if not w:
            continue

        pinyin = item.get("phonetic") or item.get("pinyin") or str(item.get("pinyin", "")).strip()
        en = str(item.get("en", "")).strip()
        vn = str(item.get("vn", "")).strip()

        lines.append(f"{stt}. {w} - {pinyin}")
        lines.append(f"   EN: {en}")
        lines.append(f"   VN: {vn}\n")

    file_path.write_text("\n".join(lines), encoding="utf-8")

    return jsonify(
        {
            "success": True,
            "filename": "vocabulary.txt",
            "filepath": str(file_path),
            "path": str(file_path),
            "message": f"Successfully saved {len(words)} word(s) to local file.",
        }
    )


@app.route("/save_words", methods=["POST"])
def save_words():
    return api_save_vocab()


@app.route("/outputs/<path:filename>")
def output_file(filename: str):
    return send_from_directory(
        OUTPUT_DIR,
        filename,
        as_attachment=False,
    )


@app.route("/ping", methods=["POST"])
def ping():
    return Response(status=204)


if __name__ == "__main__":
    debug_mode = os.environ.get(
        "CHINESE_TTS_DEBUG",
        "0",
    ) == "1"

    if (
        not debug_mode
        or os.environ.get("WERKZEUG_RUN_MAIN") == "true"
    ):
        threading.Thread(
            target=idle_shutdown_watchdog,
            daemon=True,
        ).start()

    app.run(
        host="127.0.0.1",
        port=5000,
        debug=debug_mode,
    )
